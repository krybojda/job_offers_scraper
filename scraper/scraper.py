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


def retry_details():
    """
    Ponownie pobiera szczegóły ofert,
    które mają details_scraped_at = NULL.

    Nie korzysta z keywords.txt ani
    ignored_keywords.txt.
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

    # -----------------------------------------
    # MYSQL
    # -----------------------------------------

    if not wait_for_mysql():
        raise RuntimeError(
            "Nie udało się połączyć z MySQL."
        )

    jobs = get_jobs_without_details(
        portal="justjoin",
        limit=MAX_DETAILS_PER_RUN,
    )

    print(
        "Ofert bez szczegółów: "
        f"{len(jobs)}"
    )

    if not jobs:

        print(
            "Brak ofert wymagających "
            "ponownego pobrania."
        )

        print(
            "\nPONOWNE POBIERANIE ZAKOŃCZONE"
        )

        return

    # -----------------------------------------
    # PLAYWRIGHT
    # -----------------------------------------

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
                jobs
            ):

                # -----------------------------------------
                # PRZERWA
                # -----------------------------------------

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

                # -----------------------------------------
                # POBRANIE SZCZEGÓŁÓW
                # -----------------------------------------

                try:

                    details = (
                        scrape_justjoin_details(
                            page,
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
                        "========================================\n"
                        "JUST JOIN IT - STOP\n"
                        "========================================"
                    )

                    print(
                        f"Powód: {error}"
                    )

                    print(
                        "Przerywam ponowne "
                        "pobieranie szczegółów."
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
    Wykonuje jeden pełny przebieg scrapera.
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
    # SŁOWA KLUCZOWE
    # =====================================================

    keywords = load_keywords()

    print(
        f"Słowa kluczowe ({len(keywords)}):"
    )

    for keyword in keywords:
        print(
            f"  - {keyword}"
        )

    # =====================================================
    # SŁOWA IGNOROWANE
    # =====================================================

    ignored_keywords = (
        load_ignored_keywords()
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
    # MYSQL
    # =====================================================

    if not wait_for_mysql():

        raise RuntimeError(
            "Nie udało się połączyć z MySQL."
        )

    total_found = 0
    total_saved = 0
    total_ignored = 0
    total_details = 0

    # Wszystkie oferty znalezione w tym
    # pełnym przebiegu Just Join.
    seen_source_ids = set()

    # Jeżeli skan nie zakończy się poprawnie,
    # nie aktualizujemy missed_count.
    scan_complete = True

    # Kolejka ofert wymagających szczegółów.
    details_queue = []

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

        search_page = context.new_page()
        details_page = context.new_page()

        try:

            # =============================================
            # JUST JOIN - LISTA OFERT
            # =============================================

            for index, keyword in enumerate(
                keywords
            ):

                # -----------------------------------------
                # PRZERWA
                # -----------------------------------------

                if index > 0:

                    delay = random.uniform(
                        MIN_DELAY,
                        MAX_DELAY,
                    )

                    print(
                        "\nPrzerwa przed "
                        "kolejnym wyszukiwaniem: "
                        f"{delay:.1f} s"
                    )

                    time.sleep(
                        delay
                    )

                # -----------------------------------------
                # SCRAPOWANIE
                # -----------------------------------------

                try:

                    jobs, page_ok = (
                        scrape_justjoin_page(
                            search_page,
                            keyword,
                        )
                    )

                    if not page_ok:
                        scan_complete = False

                    total_found += len(
                        jobs
                    )

                    for job in jobs:

                        # Oferta została znaleziona.
                        seen_source_ids.add(
                            job["source_id"]
                        )

                        # ---------------------------------
                        # FILTR IGNOROWANYCH
                        # ---------------------------------

                        if is_ignored_job(
                            job["title"],
                            ignored_keywords,
                        ):

                            print(
                                "[IGNORUJ] "
                                f"{job['title']}"
                            )

                            total_ignored += 1

                            continue

                        # ---------------------------------
                        # MYSQL
                        # ---------------------------------

                        result = save_job(
                            job
                        )

                        total_saved += 1

                        # ---------------------------------
                        # SZCZEGÓŁY
                        # ---------------------------------

                        if (
                            result["needs_details"]
                            and len(details_queue)
                            < MAX_DETAILS_PER_RUN
                        ):

                            details_queue.append(
                                job
                            )

                except PortalBlockedError as error:

                    scan_complete = False

                    print(
                        "\n"
                        "========================================\n"
                        "JUST JOIN IT - STOP\n"
                        "========================================"
                    )

                    print(
                        f"Powód zatrzymania: {error}"
                    )

                    print(
                        "Nie wykonujemy kolejnych "
                        "wyszukiwań Just Join IT."
                    )

                    break

                except Exception as error:

                    scan_complete = False

                    print(
                        "[ERROR] Just Join IT "
                        f"dla '{keyword}': "
                        f"{error}"
                    )

            # =============================================
            # SZCZEGÓŁY OFERT
            # =============================================

            print(
                "\n========================================"
            )
            print(
                "POBIERANIE SZCZEGÓŁÓW OFERT"
            )
            print(
                "========================================"
            )

            print(
                "Oferty do pobrania szczegółów: "
                f"{len(details_queue)}"
            )

            for index, job in enumerate(
                details_queue
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
                            details_page,
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

                        total_details += 1

                except PortalBlockedError as error:

                    scan_complete = False

                    print(
                        "\n"
                        "========================================\n"
                        "JUST JOIN IT - STOP\n"
                        "========================================"
                    )

                    print(
                        f"Powód zatrzymania: {error}"
                    )

                    print(
                        "Nie będą pobierane "
                        "kolejne strony szczegółowe."
                    )

                    break

                except Exception as error:

                    scan_complete = False

                    print(
                        "[ERROR] Szczegóły "
                        f"{job['url']}: "
                        f"{error}"
                    )

            # =============================================
            # MISSED COUNT
            # =============================================

            if scan_complete:

                mark_missing_jobs(
                    portal="justjoin",
                    seen_source_ids=(
                        seen_source_ids
                    ),
                    threshold=(
                        MISSED_THRESHOLD
                    ),
                )

            else:

                print(
                    "\n[AKTYWNOŚĆ] Pominięto "
                    "aktualizację missed_count, "
                    "ponieważ pełny skan "
                    "Just Join nie zakończył się "
                    "poprawnie."
                )

        finally:

            search_page.close()
            details_page.close()

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
        f"Znaleziono: {total_found}"
    )

    print(
        "Zapisano/zaaktualizowano: "
        f"{total_saved}"
    )

    print(
        f"Zignorowano: {total_ignored}"
    )

    print(
        f"Pobrano szczegółów: "
        f"{total_details}"
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
            "Pobierz ponownie szczegóły ofert, "
            "które nie mają details_scraped_at."
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