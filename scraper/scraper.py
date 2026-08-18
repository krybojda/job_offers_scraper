import argparse
import os
import time

import mysql.connector
from mysql.connector import Error


# 1 godzina
SCRAPE_INTERVAL = 3600


def get_db_connection():
    """Połączenie z MySQL."""
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def load_keywords():
    """Wczytuje słowa kluczowe z keywords.txt."""
    try:
        with open("keywords.txt", "r", encoding="utf-8") as file:
            keywords = [
                line.strip()
                for line in file
                if line.strip() and not line.lstrip().startswith("#")
            ]

        return keywords

    except FileNotFoundError:
        print("BŁĄD: Nie znaleziono pliku keywords.txt")
        raise


def wait_for_mysql(max_attempts=10, delay=3):
    """
    Czeka na dostępność MySQL.
    Zwraca True po poprawnym połączeniu.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            connection = get_db_connection()

            if connection.is_connected():
                connection.close()
                print("Połączenie z MySQL: OK")
                return True

        except Error as error:
            print(
                f"MySQL niedostępny "
                f"(próba {attempt}/{max_attempts}): {error}"
            )

            if attempt < max_attempts:
                time.sleep(delay)

    return False


def run_scrape():
    """
    Jeden pełny przebieg scrapera.

    Na tym etapie wykonujemy tylko test połączenia
    i sprawdzenie liczby ofert.
    W kolejnych etapach tutaj dojdzie właściwe scrapowanie.
    """
    print("\n========================================")
    print("START PRZEBIEGU SCRAPERA")
    print("========================================")

    keywords = load_keywords()

    print(f"Słowa kluczowe ({len(keywords)}):")
    for keyword in keywords:
        print(f"  - {keyword}")

    if not wait_for_mysql():
        raise RuntimeError(
            "Nie udało się połączyć z MySQL."
        )

    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("SELECT COUNT(*) FROM jobs")
        count = cursor.fetchone()[0]

        print(f"Liczba ofert w bazie: {count}")

        cursor.close()

    finally:
        connection.close()

    print("PRZEBIEG ZAKOŃCZONY")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scraper ofert pracy"
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Wykonaj jeden przebieg i zakończ program",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=SCRAPE_INTERVAL,
        help=(
            "Czas oczekiwania między przebiegami "
            "w sekundach w trybie ciągłym"
        ),
    )

    return parser.parse_args()


def main():
    args = parse_args()

    print("========================================")
    print("JOB OFFERS SCRAPER")
    print("========================================")

    if args.once:
        print("Tryb: JEDEN PRZEBIEG")
        run_scrape()
        return

    print("Tryb: CIĄGŁY")
    print(
        f"Interwał między przebiegami: "
        f"{args.interval} sekund"
    )

    while True:
        try:
            run_scrape()

        except Exception as error:
            print(f"BŁĄD PODCZAS PRZEBIEGU: {error}")

        print(
            f"\nNastępny przebieg za "
            f"{args.interval} sekund."
        )

        time.sleep(args.interval)


if __name__ == "__main__":
    main()