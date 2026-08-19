import argparse
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


# =========================================================
# WŁĄCZANIE / WYŁĄCZANIE PORTALI
# =========================================================
#
# Portal:
#     True  = włączony
#     False = wyłączony
#
# Szczegóły:
#     True  = pobieraj strony szczegółowe
#     False = nie pobieraj stron szczegółowych
#
# Przykład: tylko lista Pracuj:
#
# RUN_JUSTJOIN = False
# RUN_JUSTJOIN_DETAILS = False
#
# RUN_PRACUJ = True
# RUN_PRACUJ_DETAILS = False
#
# =========================================================

RUN_JUSTJOIN = False
RUN_JUSTJOIN_DETAILS = False

RUN_PRACUJ = True
RUN_PRACUJ_DETAILS = False


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


def retry_details():
    """
    Ponownie pobiera szczegóły ofert,
    które mają details_scraped_at = NULL.

    Respektuje niezależne flagi:
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

    # -----------------------------------------------------
    # MYSQL
    # -----------------------------------------------------

    if not wait_for_mysql():

        raise RuntimeError(
            "Nie udało się połączyć z MySQL."
        )

    # -----------------------------------------------------
    # AKTYWNE PORTALE DLA RETRY
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # PLAYWRIGHT
    # -----------------------------------------------------

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
            browser.close()

    print(
        "\nPONOWNE POBIERANIE ZAKOŃCZONE"
    )


def run_scrape():
    """
    Wykonuje jeden pełny przebieg.

    Portale i ich strony szczegółowe
    są sterowane niezależnymi flagami.
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

    # -----------------------------------------------------
    # STATUS PORTALI
    # -----------------------------------------------------

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

    # =====================================================
    # PLAYWRIGHT
    # =====================================================

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

        justjoin_page = context.new_page()
        pracuj_page = context.new_page()

        justjoin_details_page = (
            context.new_page()
        )

        pracuj_details_page = (
            context.new_page()
        )

        try:

            # =================================================
            # JUST JOIN IT
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

                # -------------------------------------------------
                # MISSED COUNT
                # -------------------------------------------------

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

            # =================================================
            # PRACUJ.PL
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

                for index, keyword in enumerate(
                    keywords
                ):

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

                        if not scan_complete:

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

                    except PracujBlockedError as error:

                        pracuj_complete = False

                        print(
                            "\n"
                            "========================================\n"
                            "PRACUJ.PL - STOP\n"
                            "========================================"
                        )

                        print(
                            f"Powód: {error}"
                        )

                        print(
                            "Nie wykonujemy kolejnych "
                            "wyszukiwań Pracuj.pl."
                        )

                        break

                    except Exception as error:

                        pracuj_complete = False

                        print(
                            "[ERROR] Pracuj.pl "
                            f"dla '{keyword}': "
                            f"{error}"
                        )

                # -------------------------------------------------
                # MISSED COUNT
                # -------------------------------------------------

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
                    "Ofert do pobrania szczegółów: "
                    f"{len(pracuj_details_queue)}"
                )

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
                                pracuj_details_page,
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

            elif RUN_PRACUJ:

                print(
                    "\n[PRACUJ.PL] "
                    "SZCZEGÓŁY WYŁĄCZONE"
                )

        finally:

            justjoin_page.close()
            pracuj_page.close()

            justjoin_details_page.close()
            pracuj_details_page.close()

            context.close()
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