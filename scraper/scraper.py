import argparse
import hashlib
import os
import time
from datetime import datetime
from urllib.parse import quote

import mysql.connector
import requests
from bs4 import BeautifulSoup
from mysql.connector import Error


SCRAPE_INTERVAL = 3600

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    )
}


def get_db_connection():
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def load_keywords():
    with open("keywords.txt", "r", encoding="utf-8") as file:
        return [
            line.strip()
            for line in file
            if line.strip() and not line.lstrip().startswith("#")
        ]


def wait_for_mysql(max_attempts=10, delay=3):
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


def generate_source_id(url):
    """
    Stabilny identyfikator awaryjny na podstawie URL.
    """
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def save_job(job):
    """
    Dodaje nową ofertę lub aktualizuje istniejącą.
    """

    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        sql = """
            INSERT INTO jobs (
                portal,
                source_id,
                title,
                company,
                location,
                work_mode,
                salary,
                url,
                keyword,
                published_at,
                first_seen_at,
                last_seen_at,
                is_active
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, NOW(), NOW(), 1
            )
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                company = VALUES(company),
                location = VALUES(location),
                work_mode = VALUES(work_mode),
                salary = VALUES(salary),
                url = VALUES(url),
                keyword = VALUES(keyword),
                published_at = VALUES(published_at),
                last_seen_at = NOW(),
                is_active = 1
        """

        values = (
            job["portal"],
            job["source_id"],
            job["title"],
            job["company"],
            job["location"],
            job["work_mode"],
            job["salary"],
            job["url"],
            job["keyword"],
            job["published_at"],
        )

        cursor.execute(sql, values)

        connection.commit()

        if cursor.rowcount == 1:
            print(f"[NOWA] {job['title']}")
        else:
            print(f"[AKTUALIZACJA] {job['title']}")

    finally:
        connection.close()


def scrape_justjoin(keyword):
    """
    Pobiera oferty Just Join IT dla pojedynczego słowa kluczowego.
    """

    encoded_keyword = quote(keyword.strip().lower())

    url = (
        "https://justjoin.it/job-offers/"
        f"all-locations/{encoded_keyword}"
    )

    print(f"\nJust Join IT → {keyword}")
    print(f"URL: {url}")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    print(f"HTTP: {response.status_code}")

    soup = BeautifulSoup(
        response.text,
        "lxml",
    )

    jobs = []

    # Tymczasowo zbieramy wszystkie linki prowadzące
    # do pojedynczych ofert.
    offer_links = soup.find_all(
        "a",
        href=True,
    )

    seen_urls = set()

    for link in offer_links:
        href = link.get("href", "").strip()

        if not href:
            continue

        if not href.startswith("/job-offer/"):
            continue

        if href in seen_urls:
            continue

        seen_urls.add(href)

        full_url = (
            "https://justjoin.it"
            + href
        )

        title = link.get_text(
            " ",
            strip=True,
        )

        if not title:
            continue

        jobs.append(
            {
                "portal": "justjoin",
                "source_id": generate_source_id(full_url),
                "title": title,
                "company": None,
                "location": None,
                "work_mode": None,
                "salary": None,
                "url": full_url,
                "keyword": keyword,
                "published_at": None,
            }
        )

    print(
        f"Znaleziono linków do ofert: {len(jobs)}"
    )

    return jobs


def run_scrape():
    print("\n========================================")
    print("START PRZEBIEGU SCRAPERA")
    print("========================================")

    keywords = load_keywords()

    print(
        f"Słowa kluczowe ({len(keywords)}):"
    )

    for keyword in keywords:
        print(f"  - {keyword}")

    if not wait_for_mysql():
        raise RuntimeError(
            "Nie udało się połączyć z MySQL."
        )

    total = 0

    for keyword in keywords:
        try:
            jobs = scrape_justjoin(keyword)

            for job in jobs:
                save_job(job)
                total += 1

        except Exception as error:
            print(
                f"BŁĄD Just Join IT "
                f"dla '{keyword}': {error}"
            )

    print(
        f"\nŁącznie przetworzonych ofert: {total}"
    )

    print("PRZEBIEG ZAKOŃCZONY")


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--once",
        action="store_true",
        help="Wykonaj jeden przebieg.",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=SCRAPE_INTERVAL,
        help="Interwał między przebiegami.",
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

    while True:
        try:
            run_scrape()

        except Exception as error:
            print(
                f"BŁĄD PODCZAS PRZEBIEGU: {error}"
            )

        print(
            f"\nNastępny przebieg za "
            f"{args.interval} sekund."
        )

        time.sleep(args.interval)


if __name__ == "__main__":
    main()