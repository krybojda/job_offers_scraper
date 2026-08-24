import argparse
import json
import os
import random
import time

from playwright.sync_api import sync_playwright

from config import (
    DETAIL_MAX_DELAY,
    DETAIL_MIN_DELAY,
    HEADLESS,
    MAX_DETAILS_PER_RUN,
    NOFLUFFJOBS_BLOCK_COOLDOWN,
    MAX_DELAY,
    MIN_DELAY,
    MISSED_THRESHOLD,
    SCRAPE_INTERVAL,
    USER_AGENT,
)

from database import (
    get_jobs_without_details,
    mark_missing_jobs,
    save_job,
    save_job_details,
    wait_for_mysql,
)

from filters import (
    is_ignored_job,
    load_ignored_keywords,
    load_keywords,
)

from justjoin import (
    PortalBlockedError,
    scrape_justjoin_details,
    scrape_justjoin_page,
)

from pracuj import (
    PracujBlockedError,
    scrape_pracuj,
    scrape_pracuj_details,
)

from nofluffjobs import (
    NoFluffJobsBlockedError,
    scrape_nofluffjobs,
    scrape_nofluffjobs_details,
)


# =========================================================
# WŁĄCZANIE / WYŁĄCZANIE PORTALI
# =========================================================

RUN_JUSTJOIN = True
RUN_JUSTJOIN_DETAILS = True

RUN_PRACUJ = True
RUN_PRACUJ_DETAILS = False

RUN_NOFLUFFJOBS = True
RUN_NOFLUFFJOBS_DETAILS = True


# =========================================================
# STAN BLOKADY NO FLUFF JOBS
# =========================================================

NOFLUFFJOBS_STATE_FILE = os.path.join(
    "state",
    "nofluffjobs_details_state.json",
)


def load_nofluffjobs_block_until():
    if not os.path.exists(NOFLUFFJOBS_STATE_FILE):
        return 0

    try:
        with open(NOFLUFFJOBS_STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return float(data.get("blocked_until", 0))
    except Exception as error:
        print(f"[NO FLUFF JOBS] Nie udało się odczytać stanu blokady: {error}")
        return 0


def save_nofluffjobs_block_until(blocked_until):
    try:
        state_directory = os.path.dirname(NOFLUFFJOBS_STATE_FILE)
        if state_directory:
            os.makedirs(state_directory, exist_ok=True)
        with open(NOFLUFFJOBS_STATE_FILE, "w", encoding="utf-8") as file:
            json.dump({"blocked_until": blocked_until}, file, indent=2)
    except Exception as error:
        print(f"[NO FLUFF JOBS] Nie udało się zapisać stanu blokady: {error}")


def nofluffjobs_blocked_by_cooldown():
    blocked_until = load_nofluffjobs_block_until()
    now = time.time()
    if blocked_until <= now:
        return False, 0
    return True, blocked_until - now


def set_nofluffjobs_cooldown():
    blocked_until = time.time() + NOFLUFFJOBS_BLOCK_COOLDOWN
    save_nofluffjobs_block_until(blocked_until)
    return blocked_until


# =========================================================
# STAN PRACUJ
# =========================================================

PRACUJ_STATE_FILE = os.path.join(
    "state",
    "pracuj_state.json",
)


def load_pracuj_state():
    """
    Wczytuje indeks keywordu Pracuj.pl.
    """

    if not os.path.exists(
        PRACUJ_STATE_FILE
    ):

        return 0

    try:

        with open(
            PRACUJ_STATE_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        index = int(
            data.get(
                "keyword_index",
                0,
            )
        )

        if index < 0:

            return 0

        return index

    except Exception as error:

        print(
            "[PRACUJ] Nie udało się "
            "odczytać stanu: "
            f"{error}"
        )

        return 0


def save_pracuj_state(
    keyword_index,
):
    """
    Zapisuje indeks kolejnego keywordu.
    """

    try:

        state_directory = os.path.dirname(
            PRACUJ_STATE_FILE
        )

        if state_directory:

            os.makedirs(
                state_directory,
                exist_ok=True,
            )

        with open(
            PRACUJ_STATE_FILE,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                {
                    "keyword_index": (
                        keyword_index
                    )
                },
                file,
                ensure_ascii=False,
                indent=4,
            )

    except Exception as error:

        print(
            "[PRACUJ] Błąd zapisu "
            "stanu: "
            f"{error}"
        )


def reset_pracuj_state():
    save_pracuj_state(0)


# =========================================================
# WSPÓLNE PRZETWARZANIE OFERT
# =========================================================

def process_jobs(
    jobs,
    ignored_keywords,
    details_queue,
    total_stats,
):
    """
    Zapisuje oferty do MySQL i dodaje je do kolejki
    szczegółów bez duplikowania source_id.
    """

    # Source ID ofert, które już znajdują się
    # w kolejce szczegółów.
    queued_detail_ids = {
        job["source_id"]
        for job in details_queue
    }

    for job in jobs:

        total_stats["seen"] += 1

        # -------------------------------------------------
        # IGNOROWANE
        # -------------------------------------------------

        if is_ignored_job(
            job["title"],
            ignored_keywords,
        ):

            print(
                "[IGNORUJ] "
                f"{job['title']}"
            )

            total_stats["ignored"] += 1

            continue

        # -------------------------------------------------
        # ZAPIS / AKTUALIZACJA
        # -------------------------------------------------

        result = save_job(
            job
        )

        total_stats["saved"] += 1

        # -------------------------------------------------
        # SZCZEGÓŁY
        # -------------------------------------------------

        source_id = job[
            "source_id"
        ]

        if (
            result.get(
                "needs_details",
                False,
            )
            and source_id
            not in queued_detail_ids
            and len(details_queue)
            < MAX_DETAILS_PER_RUN
        ):

            details_queue.append(
                job
            )

            queued_detail_ids.add(
                source_id
            )

# =========================================================
# RETRY SZCZEGÓŁÓW
# =========================================================

def retry_details():
    """
    Ponownie pobiera szczegóły dla ofert,
    które ich jeszcze nie mają.
    """

    print(
        "\n========================================"
    )

    print(
        "PONOWNE POBIERANIE SZCZEGÓŁÓW"
    )

    print(
        "========================================"
    )

    if not wait_for_mysql():

        raise RuntimeError(
            "Nie udało się połączyć z MySQL."
        )

    portals = []

    if (
        RUN_JUSTJOIN
        and RUN_JUSTJOIN_DETAILS
    ):

        portals.append(
            (
                "justjoin",
                scrape_justjoin_details,
                PortalBlockedError,
            )
        )

    if (
        RUN_PRACUJ
        and RUN_PRACUJ_DETAILS
    ):

        portals.append(
            (
                "pracuj",
                scrape_pracuj_details,
                PracujBlockedError,
            )
        )

    if (
        RUN_NOFLUFFJOBS
        and RUN_NOFLUFFJOBS_DETAILS
    ):

        portals.append(
            (
                "nofluffjobs",
                scrape_nofluffjobs_details,
                NoFluffJobsBlockedError,
            )
        )

    if not portals:

        print(
            "Brak portali z włączonym "
            "pobieraniem szczegółów."
        )

        print(
            "\nPONOWNE POBIERANIE ZAKOŃCZONE"
        )

        return

    total_processed = 0

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
            headless=HEADLESS
        )

        try:

            for (
                portal,
                detail_function,
                block_error,
            ) in portals:

                if portal == "nofluffjobs":
                    in_cooldown, remaining = nofluffjobs_blocked_by_cooldown()
                    if in_cooldown:
                        print(
                            "[NO FLUFF JOBS] SZCZEGÓŁY WSTRZYMANE "
                            f"przez cooldown. Pozostało około {remaining / 3600:.1f} h."
                        )
                        continue

                jobs = get_jobs_without_details(
                    portal=portal,
                    limit=MAX_DETAILS_PER_RUN,
                )

                print(
                    f"\nPortal: {portal}"
                )

                print(
                    "Ofert bez szczegółów: "
                    f"{len(jobs)}"
                )

                if not jobs:

                    continue

                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={
                        "width": 1440,
                        "height": 1000,
                    },
                    locale="pl-PL",
                )

                page = context.new_page()

                try:

                    for index, job in enumerate(
                        jobs
                    ):

                        if (
                            index > 0
                            or total_processed > 0
                        ):

                            delay = random.uniform(
                                DETAIL_MIN_DELAY,
                                DETAIL_MAX_DELAY,
                            )

                            print(
                                "\nPrzerwa przed "
                                "kolejną ofertą szczegółową: "
                                f"{delay:.1f} s"
                            )

                            time.sleep(
                                delay
                            )

                        try:

                            details = (
                                detail_function(
                                    page,
                                    job,
                                )
                            )

                            if details is not None:

                                save_job_details(
                                    portal=portal,
                                    source_id=job[
                                        "source_id"
                                    ],
                                    details=details,
                                )

                                total_processed += 1

                        except block_error as error:

                            if portal == "nofluffjobs":
                                blocked_until = set_nofluffjobs_cooldown()
                                print(
                                    "[NO FLUFF JOBS] Ustawiono cooldown "
                                    f"na {NOFLUFFJOBS_BLOCK_COOLDOWN / 3600:.1f} h."
                                )

                            print(
                                "\n"
                                "========================================"
                            )

                            print(
                                f"{portal.upper()} "
                                "- STOP SZCZEGÓŁÓW"
                            )

                            print(
                                "========================================"
                            )

                            print(
                                f"Powód: {error}"
                            )

                            print(
                                f"Przerywam pobieranie "
                                f"szczegółów {portal}."
                            )

                            break

                        except Exception as error:

                            print(
                                "[ERROR] Szczegóły "
                                f"{portal}: "
                                f"{error}"
                            )

                finally:

                    page.close()
                    context.close()

        finally:

            browser.close()

    print(
        "\nPONOWNE POBIERANIE ZAKOŃCZONE"
    )


# =========================================================
# GŁÓWNY SCRAPE
# =========================================================

def run_scrape():

    print(
        "\n========================================"
    )

    print(
        "START PRZEBIEGU SCRAPERA"
    )

    print(
        "========================================"
    )

    keywords = load_keywords()

    ignored_keywords = (
        load_ignored_keywords()
    )

    print(
        f"Słowa kluczowe ({len(keywords)}):"
    )

    for keyword in keywords:

        print(
            f"  - {keyword}"
        )

    print(
        "Ignorowane słowa/frazy "
        f"({len(ignored_keywords)}):"
    )

    for keyword in ignored_keywords:

        print(
            f"  - {keyword}"
        )

    # =====================================================
    # STATUS
    # =====================================================

    print(
        "\nAktywne portale:"
    )

    print(
        f"  Just Join IT: "
        f"{'TAK' if RUN_JUSTJOIN else 'NIE'}"
    )

    print(
        f"    szczegóły: "
        f"{'TAK' if RUN_JUSTJOIN_DETAILS else 'NIE'}"
    )

    print(
        f"  Pracuj.pl: "
        f"{'TAK' if RUN_PRACUJ else 'NIE'}"
    )

    print(
        f"    szczegóły: "
        f"{'TAK' if RUN_PRACUJ_DETAILS else 'NIE'}"
    )

    print(
        f"  No Fluff Jobs: "
        f"{'TAK' if RUN_NOFLUFFJOBS else 'NIE'}"
    )

    print(
        f"    szczegóły: "
        f"{'TAK' if RUN_NOFLUFFJOBS_DETAILS else 'NIE'}"
    )

    # =====================================================
    # MYSQL
    # =====================================================

    if not wait_for_mysql():

        raise RuntimeError(
            "Nie udało się połączyć z MySQL."
        )

    total_stats = {
        "seen": 0,
        "saved": 0,
        "ignored": 0,
    }

    # =====================================================
    # ZBIORY / KOLEJKI
    # =====================================================

    justjoin_seen_ids = set()
    justjoin_complete = True
    justjoin_details_queue = []

    pracuj_seen_ids = set()
    pracuj_complete = True
    pracuj_details_queue = []

    nofluffjobs_seen_ids = set()
    nofluffjobs_complete = True
    nofluffjobs_details_queue = []

    # =====================================================
    # PLAYWRIGHT
    # =====================================================

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
            headless=HEADLESS
        )

        # -------------------------------------------------
        # JUST JOIN
        # -------------------------------------------------

        justjoin_context = None
        justjoin_page = None
        justjoin_details_page = None

        if RUN_JUSTJOIN:

            justjoin_context = (
                browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={
                        "width": 1440,
                        "height": 1000,
                    },
                    locale="pl-PL",
                )
            )

            justjoin_page = (
                justjoin_context.new_page()
            )

            if RUN_JUSTJOIN_DETAILS:

                justjoin_details_page = (
                    justjoin_context.new_page()
                )

        try:

            # =================================================
            # JUST JOIN
            # =================================================

            if RUN_JUSTJOIN:

                print(
                    "\n========================================"
                )

                print(
                    "SCRAPOWANIE JUST JOIN IT"
                )

                print(
                    "========================================"
                )

                for index, keyword in enumerate(
                    keywords
                ):

                    if index > 0:

                        delay = random.uniform(
                            MIN_DELAY,
                            MAX_DELAY,
                        )

                        print(
                            "\nPrzerwa przed "
                            "kolejnym wyszukiwaniem "
                            "Just Join: "
                            f"{delay:.1f} s"
                        )

                        time.sleep(
                            delay
                        )

                    try:

                        (
                            jobs,
                            page_ok,
                        ) = scrape_justjoin_page(
                            justjoin_page,
                            keyword,
                        )

                        if not page_ok:

                            justjoin_complete = False

                        for job in jobs:

                            justjoin_seen_ids.add(
                                job["source_id"]
                            )

                        process_jobs(
                            jobs=jobs,
                            ignored_keywords=(
                                ignored_keywords
                            ),
                            details_queue=(
                                justjoin_details_queue
                            ),
                            total_stats=(
                                total_stats
                            ),
                        )

                    except PortalBlockedError as error:

                        justjoin_complete = False

                        print(
                            "\n"
                            "========================================"
                        )

                        print(
                            "JUST JOIN IT - STOP"
                        )

                        print(
                            "========================================"
                        )

                        print(
                            f"Powód: {error}"
                        )

                        break

                    except Exception as error:

                        justjoin_complete = False

                        print(
                            "[ERROR] Just Join IT "
                            f"dla '{keyword}': "
                            f"{error}"
                        )

                if justjoin_complete:

                    mark_missing_jobs(
                        portal="justjoin",
                        seen_source_ids=(
                            justjoin_seen_ids
                        ),
                        threshold=(
                            MISSED_THRESHOLD
                        ),
                    )

            else:

                print(
                    "\n[JUST JOIN] WYŁĄCZONE"
                )

            # =================================================
            # PRACUJ
            # =================================================

            if RUN_PRACUJ:

                print(
                    "\n========================================"
                )

                print(
                    "SCRAPOWANIE PRACUJ.PL"
                )

                print(
                    "========================================"
                )

                start_index = (
                    load_pracuj_state()
                )

                if start_index >= len(
                    keywords
                ):

                    start_index = 0

                    reset_pracuj_state()

                for index in range(
                    start_index,
                    len(keywords),
                ):

                    keyword = keywords[
                        index
                    ]

                    delay = random.uniform(
                        MIN_DELAY,
                        MAX_DELAY,
                    )

                    print(
                        "\nPrzerwa przed "
                        "wyszukiwaniem Pracuj.pl: "
                        f"{delay:.1f} s"
                    )

                    time.sleep(
                        delay
                    )

                    print(
                        "\n[PRACUJ] Nowy kontekst "
                        f"dla keywordu: {keyword}"
                    )

                    pracuj_context = (
                        browser.new_context(
                            user_agent=USER_AGENT,
                            viewport={
                                "width": 1440,
                                "height": 1000,
                            },
                            locale="pl-PL",
                        )
                    )

                    pracuj_page = (
                        pracuj_context.new_page()
                    )

                    keyword_completed = False

                    try:

                        (
                            jobs,
                            seen_ids,
                            scan_complete,
                        ) = scrape_pracuj(
                            page=pracuj_page,
                            keyword=keyword,
                            min_delay=MIN_DELAY,
                            max_delay=MAX_DELAY,
                        )

                        pracuj_seen_ids.update(
                            seen_ids
                        )

                        if scan_complete:

                            keyword_completed = True

                        else:

                            pracuj_complete = False

                        process_jobs(
                            jobs=jobs,
                            ignored_keywords=(
                                ignored_keywords
                            ),
                            details_queue=(
                                pracuj_details_queue
                            ),
                            total_stats=(
                                total_stats
                            ),
                        )

                        if keyword_completed:

                            next_index = (
                                index + 1
                            )

                            if next_index >= len(
                                keywords
                            ):

                                reset_pracuj_state()

                            else:

                                save_pracuj_state(
                                    next_index
                                )

                        else:

                            break

                    except PracujBlockedError as error:

                        pracuj_complete = False

                        print(
                            "\n"
                            "========================================"
                        )

                        print(
                            "PRACUJ.PL - STOP"
                        )

                        print(
                            "========================================"
                        )

                        print(
                            f"Keyword: {keyword}"
                        )

                        print(
                            f"Powód: {error}"
                        )

                        break

                    except Exception as error:

                        pracuj_complete = False

                        print(
                            "[ERROR] Pracuj.pl "
                            f"dla '{keyword}': "
                            f"{error}"
                        )

                        break

                    finally:

                        pracuj_page.close()
                        pracuj_context.close()

                        print(
                            "[PRACUJ] Zamknięto "
                            f"kontekst: {keyword}"
                        )

                if pracuj_complete:

                    mark_missing_jobs(
                        portal="pracuj",
                        seen_source_ids=(
                            pracuj_seen_ids
                        ),
                        threshold=(
                            MISSED_THRESHOLD
                        ),
                    )

                else:

                    print(
                        "[AKTYWNOŚĆ] Pracuj.pl: "
                        "pominięto missed_count."
                    )

            else:

                print(
                    "\n[PRACUJ.PL] WYŁĄCZONE"
                )

            # =================================================
            # NO FLUFF JOBS
            # =================================================

            if RUN_NOFLUFFJOBS:

                print(
                    "\n========================================"
                )

                print(
                    "SCRAPOWANIE NO FLUFF JOBS"
                )

                print(
                    "========================================"
                )

                for index, keyword in enumerate(
                    keywords
                ):

                    delay = random.uniform(
                        MIN_DELAY,
                        MAX_DELAY,
                    )

                    print(
                        "\nPrzerwa przed "
                        "wyszukiwaniem No Fluff Jobs: "
                        f"{delay:.1f} s"
                    )

                    time.sleep(
                        delay
                    )

                    print(
                        "\n[NO FLUFF JOBS] "
                        "Nowy kontekst dla keywordu: "
                        f"{keyword}"
                    )

                    nofluffjobs_context = (
                        browser.new_context(
                            user_agent=USER_AGENT,
                            viewport={
                                "width": 1440,
                                "height": 1000,
                            },
                            locale="pl-PL",
                        )
                    )

                    nofluffjobs_page = (
                        nofluffjobs_context.new_page()
                    )

                    try:

                        (
                            jobs,
                            seen_ids,
                            scan_complete,
                        ) = scrape_nofluffjobs(
                            page=nofluffjobs_page,
                            keyword=keyword,
                            min_delay=MIN_DELAY,
                            max_delay=MAX_DELAY,
                        )

                        nofluffjobs_seen_ids.update(
                            seen_ids
                        )

                        if not scan_complete:

                            nofluffjobs_complete = (
                                False
                            )

                        process_jobs(
                            jobs=jobs,
                            ignored_keywords=(
                                ignored_keywords
                            ),
                            details_queue=(
                                nofluffjobs_details_queue
                            ),
                            total_stats=(
                                total_stats
                            ),
                        )

                        if scan_complete:

                            print(
                                "[NO FLUFF JOBS] "
                                f"Keyword zakończony: "
                                f"{keyword}"
                            )

                        else:

                            print(
                                "[NO FLUFF JOBS] "
                                f"Keyword nie został "
                                f"zakończony: {keyword}"
                            )

                    except NoFluffJobsBlockedError as error:

                        nofluffjobs_complete = False

                        print(
                            "\n"
                            "========================================"
                        )

                        print(
                            "NO FLUFF JOBS - STOP"
                        )

                        print(
                            "========================================"
                        )

                        print(
                            f"Keyword: {keyword}"
                        )

                        print(
                            f"Powód: {error}"
                        )

                        break

                    except Exception as error:

                        nofluffjobs_complete = False

                        print(
                            "[ERROR] No Fluff Jobs "
                            f"dla '{keyword}': "
                            f"{error}"
                        )

                        break

                    finally:

                        nofluffjobs_page.close()
                        nofluffjobs_context.close()

                        print(
                            "[NO FLUFF JOBS] Zamknięto "
                            f"kontekst: {keyword}"
                        )

                if nofluffjobs_complete:

                    mark_missing_jobs(
                        portal="nofluffjobs",
                        seen_source_ids=(
                            nofluffjobs_seen_ids
                        ),
                        threshold=(
                            MISSED_THRESHOLD
                        ),
                    )

                else:

                    print(
                        "[AKTYWNOŚĆ] No Fluff Jobs: "
                        "pominięto missed_count."
                    )

            else:

                print(
                    "\n[NO FLUFF JOBS] WYŁĄCZONE"
                )

            # =================================================
            # SZCZEGÓŁY JUST JOIN
            # =================================================

            if (
                RUN_JUSTJOIN
                and RUN_JUSTJOIN_DETAILS
            ):

                print(
                    "\n========================================"
                )

                print(
                    "SZCZEGÓŁY JUST JOIN IT"
                )

                print(
                    "========================================"
                )

                print(
                    "Ofert do pobrania szczegółów: "
                    f"{len(justjoin_details_queue)}"
                )

                for index, job in enumerate(
                    justjoin_details_queue
                ):

                    if index > 0:

                        delay = random.uniform(
                            DETAIL_MIN_DELAY,
                            DETAIL_MAX_DELAY,
                        )

                        print(
                            "\nPrzerwa przed "
                            "kolejną ofertą szczegółową: "
                            f"{delay:.1f} s"
                        )

                        time.sleep(
                            delay
                        )

                    try:

                        details = (
                            scrape_justjoin_details(
                                justjoin_details_page,
                                job,
                            )
                        )

                        if details is not None:

                            save_job_details(
                                portal="justjoin",
                                source_id=job[
                                    "source_id"
                                ],
                                details=details,
                            )

                    except PortalBlockedError as error:

                        print(
                            "[JUST JOIN] "
                            f"STOP SZCZEGÓŁÓW: {error}"
                        )

                        break

                    except Exception as error:

                        print(
                            "[ERROR] Just Join "
                            f"szczegóły: {error}"
                        )

            # =================================================
            # SZCZEGÓŁY PRACUJ
            # =================================================

            if (
                RUN_PRACUJ
                and RUN_PRACUJ_DETAILS
            ):

                print(
                    "\n========================================"
                )

                print(
                    "SZCZEGÓŁY PRACUJ.PL"
                )

                print(
                    "========================================"
                )

                print(
                    "Szczegóły Pracuj.pl: WYŁĄCZONE"
                )

                print(
                    "Powód: po próbie pobierania szczegółów portal zwrócił HTTP 403. "
                    "Do czasu wdrożenia bezpiecznego mechanizmu pobierania szczegółów "
                    "nie wykonujemy żądań do stron ofert w normalnym przebiegu."
                )

            # =================================================
            # SZCZEGÓŁY NO FLUFF JOBS
            # =================================================

            if (
                RUN_NOFLUFFJOBS
                and RUN_NOFLUFFJOBS_DETAILS
            ):

                print(
                    "\n========================================"
                )

                print(
                    "SZCZEGÓŁY NO FLUFF JOBS"
                )

                print(
                    "========================================"
                )

                in_cooldown, remaining = nofluffjobs_blocked_by_cooldown()
                if in_cooldown:
                    print(
                        "[NO FLUFF JOBS] SZCZEGÓŁY WSTRZYMANE "
                        f"przez cooldown. Pozostało około {remaining / 3600:.1f} h."
                    )
                    nofluffjobs_details_queue.clear()

                if not in_cooldown:
                    # Normalny przebieg dodaje do kolejki przede wszystkim
                    # nowe oferty znalezione podczas bieżącego skanowania.
                    # Istniały jednak rekordy zapisane wcześniej bez szczegółów,
                    # które nigdy nie trafiały do tej kolejki. W efekcie backlog
                    # No Fluff Jobs rósł mimo poprawnie działającego parsera.
                    # Uzupełniamy kolejkę brakującymi rekordami, ale tylko do
                    # MAX_DETAILS_PER_RUN, aby nie zwiększać liczby żądań ponad
                    # ustalony limit i ograniczyć ryzyko blokady portalu.
                    if len(nofluffjobs_details_queue) < MAX_DETAILS_PER_RUN:

                        existing_jobs = get_jobs_without_details(
                            portal="nofluffjobs",
                            limit=MAX_DETAILS_PER_RUN,
                        )

                        queued_ids = {
                            job["source_id"]
                            for job in nofluffjobs_details_queue
                        }

                        for job in existing_jobs:

                            if job["source_id"] in queued_ids:
                                continue

                            nofluffjobs_details_queue.append(job)
                            queued_ids.add(job["source_id"])

                            if len(nofluffjobs_details_queue) >= MAX_DETAILS_PER_RUN:
                                break

                    print(
                        "Ofert do pobrania szczegółów: "
                        f"{len(nofluffjobs_details_queue)}"
                    )

                    if nofluffjobs_details_queue:

                        detail_context = (
                            browser.new_context(
                                user_agent=USER_AGENT,
                                viewport={
                                    "width": 1440,
                                    "height": 1000,
                                },
                                locale="pl-PL",
                            )
                        )

                        detail_page = (
                            detail_context.new_page()
                        )

                        try:

                            for index, job in enumerate(
                                nofluffjobs_details_queue
                            ):

                                if index > 0:

                                    delay = random.uniform(
                                        DETAIL_MIN_DELAY,
                                        DETAIL_MAX_DELAY,
                                    )

                                    print(
                                        "\nPrzerwa przed "
                                        "kolejną ofertą szczegółową: "
                                        f"{delay:.1f} s"
                                    )

                                    time.sleep(
                                        delay
                                    )

                                try:

                                    details = (
                                        scrape_nofluffjobs_details(
                                            detail_page,
                                            job,
                                        )
                                    )

                                    if details is not None:

                                        save_job_details(
                                            portal=(
                                                "nofluffjobs"
                                            ),
                                            source_id=(
                                                job[
                                                    "source_id"
                                                ]
                                            ),
                                            details=details,
                                        )

                                except NoFluffJobsBlockedError as error:

                                    set_nofluffjobs_cooldown()
                                    print(
                                        "[NO FLUFF JOBS] Ustawiono cooldown "
                                        f"na {NOFLUFFJOBS_BLOCK_COOLDOWN / 3600:.1f} h."
                                    )

                                    print(
                                        "\n"
                                        "========================================"
                                    )

                                    print(
                                        "NO FLUFF JOBS "
                                        "- STOP SZCZEGÓŁÓW"
                                    )

                                    print(
                                        "========================================"
                                    )

                                    print(
                                        f"Powód: {error}"
                                    )

                                    break

                                except Exception as error:

                                    print(
                                        "[ERROR] "
                                        "No Fluff Jobs "
                                        f"szczegóły: {error}"
                                    )

                        finally:

                            detail_page.close()
                            detail_context.close()

            elif RUN_NOFLUFFJOBS:

                print(
                    "\n[NO FLUFF JOBS] "
                    "SZCZEGÓŁY WYŁĄCZONE"
                )

        finally:

            if RUN_JUSTJOIN:

                if justjoin_page is not None:

                    justjoin_page.close()

                if justjoin_details_page is not None:

                    justjoin_details_page.close()

                if justjoin_context is not None:

                    justjoin_context.close()

            browser.close()

    # =====================================================
    # PODSUMOWANIE
    # =====================================================

    print(
        "\n========================================"
    )

    print(
        "PODSUMOWANIE"
    )

    print(
        "========================================"
    )

    print(
        f"Znaleziono: "
        f"{total_stats['seen']}"
    )

    print(
        "Zapisano/zaaktualizowano: "
        f"{total_stats['saved']}"
    )

    print(
        f"Zignorowano: "
        f"{total_stats['ignored']}"
    )

    print(
        "PRZEBIEG ZAKOŃCZONY"
    )


# =========================================================
# ARGUMENTY
# =========================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description="Scraper ofert pracy"
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Wykonaj jeden przebieg.",
    )

    parser.add_argument(
        "--retry-details",
        action="store_true",
        help=(
            "Ponownie pobierz szczegóły "
            "ofert bez szczegółów."
        ),
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=SCRAPE_INTERVAL,
        help=(
            "Interwał między przebiegami "
            "w sekundach."
        ),
    )

    return parser.parse_args()


# =========================================================
# MAIN
# =========================================================

def main():

    args = parse_args()

    print(
        "========================================"
    )

    print(
        "JOB OFFERS SCRAPER"
    )

    print(
        "========================================"
    )

    if args.retry_details:

        retry_details()

        return

    if args.once:

        print(
            "Tryb: JEDEN PRZEBIEG"
        )

        run_scrape()

        return

    print(
        "Tryb: CIĄGŁY"
    )

    print(
        f"Interwał: "
        f"{args.interval} sekund"
    )

    while True:

        try:

            run_scrape()

        except Exception as error:

            print(
                "BŁĄD PODCZAS PRZEBIEGU: "
                f"{error}"
            )

        print(
            "\nNastępny przebieg za "
            f"{args.interval} sekund."
        )

        time.sleep(
            args.interval
        )


if __name__ == "__main__":
    main()