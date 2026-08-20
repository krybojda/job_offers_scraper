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

RUN_JUSTJOIN = False
RUN_JUSTJOIN_DETAILS = False

RUN_PRACUJ = False
RUN_PRACUJ_DETAILS = False

RUN_NOFLUFFJOBS = True
RUN_NOFLUFFJOBS_DETAILS = False


# =========================================================
# STAN PRACUJ.PL
# =========================================================

PRACUJ_STATE_FILE = os.path.join(
    "state",
    "pracuj_state.json",
)


def load_pracuj_state():
    """
    Wczytuje indeks keywordu, od którego należy
    rozpocząć kolejny przebieg Pracuj.pl.

    Jeżeli pliku nie ma albo jest uszkodzony,
    zaczynamy od pierwszego keywordu.
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

        print(
            "[PRACUJ] Zaczynam od "
            "pierwszego keywordu."
        )

        return 0


def save_pracuj_state(
    keyword_index,
):
    """
    Zapisuje indeks keywordu, który ma zostać
    wykonany przy następnym uruchomieniu.
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
    """
    Wraca do pierwszego keywordu.
    """

    save_pracuj_state(
        0
    )


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
    Wspólna obsługa ofert niezależnie od portalu.
    """

    for job in jobs:

        # -------------------------------------------------
        # ZNALEZIONA OFERTA
        # -------------------------------------------------

        total_stats["seen"] += 1

        # -------------------------------------------------
        # FILTR IGNOROWANYCH
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
        # MYSQL
        # -------------------------------------------------

        result = save_job(
            job
        )

        total_stats["saved"] += 1

        # -------------------------------------------------
        # KOLEJKA SZCZEGÓŁÓW
        # -------------------------------------------------

        if (
            result["needs_details"]
            and len(details_queue)
            < MAX_DETAILS_PER_RUN
        ):

            details_queue.append(
                job
            )


# =========================================================
# RETRY SZCZEGÓŁÓW
# =========================================================

def retry_details():
    """
    Ponownie pobiera szczegóły ofert.

    Respektuje:
        RUN_JUSTJOIN_DETAILS
        RUN_PRACUJ_DETAILS
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

                            print(
                                "\n"
                                "========================================"
                            )

                            print(
                                f"{portal.upper()} - STOP"
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
                                f"{job['url']}: "
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
# GŁÓWNY PRZEBIEG
# =========================================================

def run_scrape():
    """
    Wykonuje jeden pełny przebieg.

    Dla Pracuj.pl:
        - każdy keyword ma osobny context,
        - po poprawnym zakończeniu keywordu
          zapisujemy kolejny indeks,
        - po 403 bieżący keyword NIE jest oznaczany
          jako zakończony,
        - następne uruchomienie zaczyna właśnie
          od tego keywordu.
    """

    print(
        "\n========================================"
    )

    print(
        "START PRZEBIEGU SCRAPERA"
    )

    print(
        "========================================"
    )

    # =====================================================
    # KONFIGURACJA
    # =====================================================

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
    # STATUS PORTALI
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

    # =====================================================
    # STATYSTYKI
    # =====================================================

    total_stats = {
        "seen": 0,
        "saved": 0,
        "ignored": 0,
    }

    # =====================================================
    # ZMIENNE PORTALI
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

        # =================================================
        # JUST JOIN
        # =================================================

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

            # =============================================
            # JUST JOIN IT
            # =============================================

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
                            "========================================\n"
                            "JUST JOIN IT - STOP\n"
                            "========================================"
                        )

                        print(
                            f"Powód: {error}"
                        )

                        print(
                            "Nie wykonujemy kolejnych "
                            "wyszukiwań Just Join."
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
                        "[AKTYWNOŚĆ] Just Join: "
                        "pominięto missed_count "
                        "z powodu niepełnego skanu."
                    )

            else:

                print(
                    "\n[JUST JOIN] WYŁĄCZONE"
                )

            # =============================================
            # PRACUJ.PL
            # =============================================

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

                # -----------------------------------------
                # ODCZYT STANU
                # -----------------------------------------

                start_index = (
                    load_pracuj_state()
                )

                # -----------------------------------------
                # WALIDACJA
                # -----------------------------------------

                if start_index >= len(
                    keywords
                ):

                    print(
                        "[PRACUJ] Zapisany indeks "
                        "jest poza zakresem."
                    )

                    print(
                        "[PRACUJ] Resetuję stan "
                        "do pierwszego keywordu."
                    )

                    start_index = 0

                    reset_pracuj_state()

                print(
                    "\n[PRACUJ] Rozpoczynam od "
                    f"keywordu #{start_index + 1}: "
                    f"{keywords[start_index]}"
                )

                # -----------------------------------------
                # PRZEJŚCIE OD ZAPISANEGO INDEKSU
                # -----------------------------------------

                for index in range(
                    start_index,
                    len(keywords),
                ):

                    keyword = keywords[
                        index
                    ]

                    # -------------------------------------
                    # PRZERWA
                    # -------------------------------------

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

                    # -------------------------------------
                    # NOWY CONTEXT
                    # -------------------------------------

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

                        # ---------------------------------
                        # ZACHOWAJ ZNALEZIONE OFERTY
                        # ---------------------------------

                        pracuj_seen_ids.update(
                            seen_ids
                        )

                        # ---------------------------------
                        # JEŻELI TEN KEYWORD ZAKOŃCZYŁ SIĘ
                        # PRAWIDŁOWO
                        # ---------------------------------

                        if scan_complete:

                            keyword_completed = True

                        else:

                            pracuj_complete = False

                        # ---------------------------------
                        # ZAPIS DO MYSQL
                        # ---------------------------------

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

                        # ---------------------------------
                        # STAN
                        # ---------------------------------
                        #
                        # WAŻNE:
                        #
                        # Zapisujemy kolejny indeks
                        # dopiero po poprawnym ukończeniu
                        # CAŁEGO keywordu.
                        #
                        # Jeżeli był 403, tutaj nie wchodzimy.
                        #

                        if keyword_completed:

                            next_index = (
                                index + 1
                            )

                            if next_index >= len(
                                keywords
                            ):

                                # Cała lista zakończona.
                                # Następny pełny przebieg
                                # zacznie od pierwszego keywordu.

                                reset_pracuj_state()

                                print(
                                    "\n[PRACUJ] "
                                    "Cała lista keywordów "
                                    "została zakończona."
                                )

                                print(
                                    "[PRACUJ] Następny "
                                    "przebieg zacznie "
                                    "od pierwszego keywordu."
                                )

                            else:

                                save_pracuj_state(
                                    next_index
                                )

                                print(
                                    "[PRACUJ] "
                                    "Keyword zakończony."
                                )

                                print(
                                    "[PRACUJ] Następny "
                                    "przy uruchomieniu: "
                                    f"{keywords[next_index]}"
                                )

                        else:

                            print(
                                "[PRACUJ] Keyword "
                                "nie został zakończony."
                            )

                            print(
                                "[PRACUJ] Przy następnym "
                                "uruchomieniu zostanie "
                                "powtórzony: "
                                f"{keyword}"
                            )

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

                        print(
                            "Bieżący keyword NIE został "
                            "oznaczony jako zakończony."
                        )

                        print(
                            "Następne uruchomienie "
                            "powtórzy właśnie ten keyword."
                        )

                        # WAŻNE:
                        # NIE zapisujemy kolejnego indeksu.
                        break

                    except Exception as error:

                        pracuj_complete = False

                        print(
                            "[ERROR] Pracuj.pl "
                            f"dla '{keyword}': "
                            f"{error}"
                        )

                        print(
                            "[PRACUJ] Bieżący keyword "
                            "nie zostanie oznaczony "
                            "jako zakończony."
                        )

                        break

                    finally:

                        # ---------------------------------
                        # ZAMKNIĘCIE CONTEXTU
                        # ---------------------------------

                        pracuj_page.close()

                        pracuj_context.close()

                        print(
                            "[PRACUJ] Zamknięto "
                            f"kontekst: {keyword}"
                        )

                # -----------------------------------------
                # MISSED COUNT
                # -----------------------------------------

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
                        "pominięto missed_count "
                        "z powodu niepełnego skanu."
                    )

            else:

                print(
                    "\n[PRACUJ.PL] WYŁĄCZONE"
                )

            # =====================================================
            # NO FLUFF JOBS
            # =====================================================

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

                    # ---------------------------------------------
                    # PRZERWA
                    # ---------------------------------------------

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

                    # ---------------------------------------------
                    # NOWY CONTEXT DLA KAŻDEGO KEYWORDU
                    # ---------------------------------------------

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

                            nofluffjobs_complete = False

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

                        print(
                            "Nie wykonujemy kolejnych "
                            "keywordów No Fluff Jobs."
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

                # ---------------------------------------------
                # MISSED COUNT
                # ---------------------------------------------

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
                        "pominięto missed_count "
                        "z powodu niepełnego skanu."
                    )

            else:

                print(
                    "\n[NO FLUFF JOBS] WYŁĄCZONE"
                )

            # =============================================
            # SZCZEGÓŁY JUST JOIN
            # =============================================

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
                            "\n"
                            "========================================"
                        )

                        print(
                            "JUST JOIN - STOP SZCZEGÓŁÓW"
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
                            "[ERROR] Just Join "
                            f"szczegóły: {error}"
                        )

            elif RUN_JUSTJOIN:

                print(
                    "\n[JUST JOIN] "
                    "SZCZEGÓŁY WYŁĄCZONE"
                )

        finally:

            # =============================================
            # ZAMKNIĘCIE JUST JOIN
            # =============================================

            if RUN_JUSTJOIN:

                if justjoin_page is not None:
                    justjoin_page.close()

                if justjoin_details_page is not None:
                    justjoin_details_page.close()

                if justjoin_context is not None:
                    justjoin_context.close()

            browser.close()

    # =====================================================
    # SZCZEGÓŁY PRACUJ
    # =====================================================

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
            "Ofert do pobrania szczegółów: "
            f"{len(pracuj_details_queue)}"
        )

        with sync_playwright() as playwright:

            browser = playwright.chromium.launch(
                headless=HEADLESS
            )

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
                    pracuj_details_queue
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
                            scrape_pracuj_details(
                                page,
                                job,
                            )
                        )

                        if details is not None:

                            save_job_details(
                                portal="pracuj",
                                source_id=job[
                                    "source_id"
                                ],
                                details=details,
                            )

                    except PracujBlockedError as error:

                        print(
                            "\n"
                            "========================================"
                        )

                        print(
                            "PRACUJ.PL - STOP SZCZEGÓŁÓW"
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
                            "[ERROR] Pracuj.pl "
                            f"szczegóły: {error}"
                        )

            finally:

                page.close()
                context.close()
                browser.close()

    elif RUN_PRACUJ:

        print(
            "\n[PRACUJ.PL] "
            "SZCZEGÓŁY WYŁĄCZONE"
        )

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


def parse_args():

    parser = argparse.ArgumentParser(
        description="Scraper ofert pracy"
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "Wykonaj jeden przebieg "
            "i zakończ."
        ),
    )

    parser.add_argument(
        "--retry-details",
        action="store_true",
        help=(
            "Pobierz ponownie szczegóły "
            "ofert bez details_scraped_at."
        ),
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=SCRAPE_INTERVAL,
        help=(
            "Interwał między pełnymi "
            "przebiegami w sekundach."
        ),
    )

    return parser.parse_args()


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

    # =====================================================
    # RETRY DETAILS
    # =====================================================

    if args.retry_details:

        retry_details()

        return

    # =====================================================
    # JEDEN PRZEBIEG
    # =====================================================

    if args.once:

        print(
            "Tryb: JEDEN PRZEBIEG"
        )

        run_scrape()

        return

    # =====================================================
    # TRYB CIĄGŁY
    # =====================================================

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