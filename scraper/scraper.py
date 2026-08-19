import argparse
import random
import time

from playwright.sync_api import sync_playwright # type: ignore

from config import (
    HEADLESS,
    MAX_DELAY,
    MIN_DELAY,
    SCRAPE_INTERVAL,
    USER_AGENT,
)

from database import (
    save_job,
    wait_for_mysql,
)

from filters import (
    is_ignored_job,
    load_ignored_keywords,
    load_keywords,
)

from justjoin import (
    scrape_justjoin_page,
)


def run_scrape():
    """
    Jeden pełny przebieg scrapera.
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

    # -----------------------------------------
    # SŁOWA KLUCZOWE
    # -----------------------------------------

    keywords = load_keywords()

    print(
        f"Słowa kluczowe ({len(keywords)}):"
    )

    for keyword in keywords:

        print(
            f"  - {keyword}"
        )

    # -----------------------------------------
    # IGNOROWANE
    # -----------------------------------------

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

    # -----------------------------------------
    # MYSQL
    # -----------------------------------------

    if not wait_for_mysql():

        raise RuntimeError(
            "Nie udało się połączyć z MySQL."
        )

    total_found = 0
    total_saved = 0
    total_ignored = 0

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

            # =====================================
            # JUST JOIN IT
            # =====================================

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

                    jobs = (
                        scrape_justjoin_page(
                            page,
                            keyword,
                        )
                    )

                    total_found += len(
                        jobs
                    )

                    for job in jobs:

                        # -----------------------------
                        # FILTR IGNOROWANYCH
                        # -----------------------------

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

                        # -----------------------------
                        # MYSQL
                        # -----------------------------

                        save_job(
                            job
                        )

                        total_saved += 1

                except Exception as error:

                    print(
                        "[ERROR] Just Join IT "
                        f"dla '{keyword}': "
                        f"{error}"
                    )

        finally:

            context.close()
            browser.close()

    # -----------------------------------------
    # PODSUMOWANIE
    # -----------------------------------------

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
            "Interwał między "
            "pełnymi przebiegami "
            "w sekundach."
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

    # -----------------------------------------
    # JEDEN PRZEBIEG
    # -----------------------------------------

    if args.once:

        print(
            "Tryb: JEDEN PRZEBIEG"
        )

        run_scrape()

        return

    # -----------------------------------------
    # TRYB CIĄGŁY
    # -----------------------------------------

    print(
        "Tryb: CIĄGŁY"
    )

    print(
        "Interwał: "
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