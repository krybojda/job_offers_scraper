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
    scrape_justjoin_details,
    scrape_justjoin_page,
)


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

    print(
        f"Słowa kluczowe ({len(keywords)}):"
    )

    for keyword in keywords:
        print(
            f"  - {keyword}"
        )

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

    if not wait_for_mysql():

        raise RuntimeError(
            "Nie udało się połączyć z MySQL."
        )

    total_found = 0
    total_saved = 0
    total_ignored = 0
    total_details = 0

    # Wszystkie oferty, które zostały znalezione
    # przez Just Join w tym przebiegu.
    seen_source_ids = set()

    # Czy wszystkie wyszukiwania Just Join
    # zakończyły się prawidłowo.
    scan_complete = True

    # Kolejka szczegółów.
    details_queue = []

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

            # =================================================
            # JUST JOIN — WYSZUKIWANIE
            # =================================================

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
                        "kolejnym wyszukiwaniem: "
                        f"{delay:.1f} s"
                    )

                    time.sleep(
                        delay
                    )

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

                        # Nawet jeżeli oferta jest
                        # ignorowana, została znaleziona
                        # na portalu.
                        seen_source_ids.add(
                            job["source_id"]
                        )

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

                        result = save_job(
                            job
                        )

                        total_saved += 1

                        # -----------------------------------------
                        # Szczegóły tylko wtedy, gdy potrzebne.
                        # -----------------------------------------

                        if (
                            result["needs_details"]
                            and len(details_queue)
                            < MAX_DETAILS_PER_RUN
                        ):

                            details_queue.append(
                                job
                            )

                except Exception as error:

                    scan_complete = False

                    print(
                        "[ERROR] Just Join IT "
                        f"dla '{keyword}': "
                        f"{error}"
                    )

            # =================================================
            # SZCZEGÓŁY OFERT
            # =================================================

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
                f"Oferta do pobrania szczegółów: "
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

                    if details:

                        save_job_details(
                            portal="justjoin",
                            source_id=job[
                                "source_id"
                            ],
                            details=details,
                        )

                        total_details += 1

                except Exception as error:

                    print(
                        "[ERROR] Szczegóły "
                        f"{job['url']}: "
                        f"{error}"
                    )

            # =================================================
            # AKTYWNOŚĆ OFERT
            # =================================================

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
                    "[AKTYWNOŚĆ] Pominięto "
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

    # =================================================
    # PODSUMOWANIE
    # =================================================

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