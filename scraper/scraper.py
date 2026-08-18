import argparse
import hashlib
import os
import random
import re
import time
from urllib.parse import quote, urljoin

import mysql.connector
from mysql.connector import Error
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


# ==========================================
# KONFIGURACJA
# ==========================================

# Interwał między pełnymi przebiegami w trybie ciągłym.
# 3600 = 1 godzina.
SCRAPE_INTERVAL = 3600

# Losowa przerwa między kolejnymi wyszukiwaniami.
MIN_DELAY = 10
MAX_DELAY = 20

BASE_URL = "https://justjoin.it"

HEADLESS = True

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


# ==========================================
# MYSQL
# ==========================================

def get_db_connection():
    """Tworzy połączenie z MySQL."""

    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


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


# ==========================================
# PLIKI KONFIGURACYJNE
# ==========================================

def load_keywords():
    """
    Wczytuje słowa wyszukiwania z keywords.txt.

    Puste linie i komentarze zaczynające się od #
    są ignorowane.
    """

    try:
        with open(
            "keywords.txt",
            "r",
            encoding="utf-8",
        ) as file:

            return [
                line.strip()
                for line in file
                if line.strip()
                and not line.lstrip().startswith("#")
            ]

    except FileNotFoundError:
        print("BŁĄD: Nie znaleziono pliku keywords.txt")
        raise


def load_ignored_keywords():
    """
    Wczytuje ignorowane słowa/frazy z
    ignored_keywords.txt.

    Puste linie i komentarze są ignorowane.
    """

    try:
        with open(
            "ignored_keywords.txt",
            "r",
            encoding="utf-8",
        ) as file:

            return [
                line.strip().lower()
                for line in file
                if line.strip()
                and not line.lstrip().startswith("#")
            ]

    except FileNotFoundError:
        # Brak pliku oznacza brak filtrów ignorowania.
        return []


def is_ignored_job(title, ignored_keywords):
    """
    Sprawdza, czy tytuł oferty zawiera ignorowane
    słowo lub frazę.

    Pojedyncze słowa są dopasowywane jako całe słowa.

    Przykład:
        lead → pasuje do "DevOps Team Lead"
        lead → NIE pasuje do "Leadership Engineer"

    Frazy zawierające spacje są dopasowywane jako
    dokładny fragment tekstu.

    Przykład:
        team lead → pasuje do "DevOps Team Lead"
    """

    if not title or not ignored_keywords:
        return False

    title_lower = title.lower().strip()

    for keyword in ignored_keywords:

        keyword = keyword.strip().lower()

        if not keyword:
            continue

        # --------------------------------------
        # FRAZA
        # --------------------------------------

        if " " in keyword:

            if keyword in title_lower:
                return True

            continue

        # --------------------------------------
        # POJEDYNCZE SŁOWO
        # --------------------------------------

        pattern = rf"\b{re.escape(keyword)}\b"

        if re.search(pattern, title_lower):
            return True

    return False


# ==========================================
# IDENTYFIKATOR OFERTY
# ==========================================

def generate_source_id(url):
    """
    Tworzy stabilny identyfikator oferty
    na podstawie jej URL.
    """

    normalized_url = (
        url
        .split("?")[0]
        .rstrip("/")
    )

    return hashlib.sha256(
        normalized_url.encode("utf-8")
    ).hexdigest()


# ==========================================
# ZAPIS DO MYSQL
# ==========================================

def save_job(job):
    """
    Dodaje nową ofertę lub aktualizuje
    istniejącą.

    Unikalność:
        portal + source_id

    Nowa oferta:
        first_seen_at = NOW()
        last_seen_at = NOW()

    Istniejąca oferta:
        first_seen_at pozostaje bez zmian
        last_seen_at = NOW()
        is_active = 1
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
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                NOW(),
                NOW(),
                1
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

        cursor.execute(
            sql,
            values,
        )

        connection.commit()

        # mysql.connector:
        # rowcount == 1 -> INSERT
        # rowcount == 2 -> UPDATE
        if cursor.rowcount == 1:
            print(
                f"[NOWA] {job['title']}"
            )

        else:
            print(
                f"[AKTUALIZACJA] {job['title']}"
            )

    finally:
        connection.close()


# ==========================================
# POMOCNICZE
# ==========================================

def clean_text(value):
    """
    Czyści tekst ze zbędnych spacji i nowych linii.
    """

    if not value:
        return None

    value = " ".join(
        value.split()
    )

    return (
        value
        if value
        else None
    )


# ==========================================
# ODCZYT KARTY OFERTY
# ==========================================

def extract_offer_from_link(link, keyword):
    """
    Odczytuje podstawowe dane z karty oferty
    znajdującej się na stronie wyników.

    Nie otwiera strony szczegółowej oferty.
    """

    href = link.get_attribute("href")

    if not href:
        return None

    if "/job-offer/" not in href:
        return None

    url = urljoin(
        BASE_URL,
        href,
    )

    source_id = generate_source_id(
        url
    )

    # --------------------------------------
    # TEKST KARTY
    # --------------------------------------

    card_text = None

    candidate_selectors = [
        "xpath=ancestor::article[1]",
        "xpath=ancestor::li[1]",
        "xpath=ancestor::div[@role='article'][1]",
    ]

    for selector in candidate_selectors:

        try:
            locator = link.locator(
                selector
            )

            if locator.count() > 0:

                text = locator.inner_text(
                    timeout=2000
                )

                text = clean_text(
                    text
                )

                if text:
                    card_text = text
                    break

        except Exception:
            continue

    if not card_text:

        try:
            card_text = clean_text(
                link
                .locator("xpath=..")
                .inner_text(timeout=2000)
            )

        except Exception:

            card_text = clean_text(
                link.inner_text(
                    timeout=2000
                )
            )

    # --------------------------------------
    # TYTUŁ
    # --------------------------------------

    title = clean_text(
        link.inner_text(
            timeout=2000
        )
    )

    if not title:
        return None

    # --------------------------------------
    # POZOSTAŁE POLA
    # --------------------------------------

    company = None
    location = None
    work_mode = None
    salary = None

    if card_text:

        lines = [
            clean_text(line)
            for line in card_text.split("\n")
            if clean_text(line)
        ]

        # ----------------------------------
        # TRYB PRACY
        # ----------------------------------

        for line in lines:

            if line in (
                "Remote",
                "Hybrid",
                "Office",
            ):

                work_mode = line
                break

        # ----------------------------------
        # WYNAGRODZENIE
        # ----------------------------------

        for line in lines:

            if any(
                token in line
                for token in (
                    "USD",
                    "EUR",
                    "PLN",
                    "GBP",
                    "CHF",
                    "/month",
                    "/h",
                    "month",
                )
            ):

                salary = line
                break

        # ----------------------------------
        # LOKALIZACJA
        # ----------------------------------

        mode_index = None

        if work_mode:

            try:
                mode_index = lines.index(
                    work_mode
                )

            except ValueError:
                pass

        if (
            mode_index is not None
            and mode_index > 0
        ):

            location = (
                lines[mode_index - 1]
            )

            if location == title:
                location = None

        # ----------------------------------
        # FIRMA
        # ----------------------------------

        for line in lines[:8]:

            if (
                line != title
                and line != location
                and line not in (
                    "Remote",
                    "Hybrid",
                    "Office",
                )
                and len(line) > 1
            ):

                company = line
                break

    # --------------------------------------
    # REKORD
    # --------------------------------------

    return {
        "portal": "justjoin",
        "source_id": source_id,
        "title": title,
        "company": company,
        "location": location,
        "work_mode": work_mode,
        "salary": salary,
        "url": url,
        "keyword": keyword,
        "published_at": None,
    }


# ==========================================
# URL JUST JOIN IT
# ==========================================

def build_justjoin_url(keyword):
    """
    Buduje URL wyszukiwania Just Join IT.

    Pojedyncze słowo:
        /all-locations/devops

    Fraza:
        /all-locations/devops?q=devops%20engineer%40keyword
    """

    normalized = keyword.strip()

    # --------------------------------------
    # POJEDYNCZE SŁOWO
    # --------------------------------------

    if " " not in normalized:

        slug = quote(
            normalized.lower()
        )

        return (
            f"{BASE_URL}/job-offers/"
            f"all-locations/{slug}"
        )

    # --------------------------------------
    # FRAZA
    # --------------------------------------

    encoded = quote(
        normalized
    )

    return (
        f"{BASE_URL}/job-offers/"
        f"all-locations/devops"
        f"?q={encoded}%40keyword"
    )


# ==========================================
# SCRAPOWANIE JUST JOIN IT
# ==========================================

def scrape_justjoin_page(page, keyword):
    """
    Pobiera jedną stronę wyników Just Join IT.
    """

    url = build_justjoin_url(
        keyword
    )

    print(
        f"\nJust Join IT → {keyword}"
    )

    print(
        f"URL: {url}"
    )

    # --------------------------------------
    # OTWARCIE STRONY
    # --------------------------------------

    try:

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        # Czekamy na wyrenderowanie JS.
        page.wait_for_timeout(
            5000
        )

    except PlaywrightTimeoutError:

        print(
            f"[WARN] Timeout podczas "
            f"ładowania: {url}"
        )

        return []

    current_url = page.url

    print(
        f"Załadowany URL: {current_url}"
    )

    # --------------------------------------
    # LINKI DO OFERT
    # --------------------------------------

    try:

        page.locator(
            "a[href*='/job-offer/']"
        ).first.wait_for(
            timeout=30000
        )

    except PlaywrightTimeoutError:

        print(
            "Nie znaleziono linków "
            "do ofert na stronie."
        )

        return []

    links = page.locator(
        "a[href*='/job-offer/']"
    )

    count = links.count()

    print(
        f"Znaleziono elementów z "
        f"linkiem ofert: {count}"
    )

    jobs = []

    seen = set()

    # --------------------------------------
    # ODCZYT OFERT
    # --------------------------------------

    for index in range(count):

        link = links.nth(
            index
        )

        try:

            job = extract_offer_from_link(
                link,
                keyword,
            )

        except Exception as error:

            print(
                f"[WARN] Nie udało się "
                f"odczytać oferty #{index}: "
                f"{error}"
            )

            continue

        if not job:
            continue

        # ----------------------------------
        # DEDUPLIKACJA
        # ----------------------------------

        if job["source_id"] in seen:
            continue

        seen.add(
            job["source_id"]
        )

        jobs.append(
            job
        )

    print(
        f"Unikalnych ofert do "
        f"przetworzenia: {len(jobs)}"
    )

    return jobs


# ==========================================
# GŁÓWNY PRZEBIEG
# ==========================================

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

    # --------------------------------------
    # SŁOWA WYSZUKIWANIA
    # --------------------------------------

    keywords = load_keywords()

    print(
        f"Słowa kluczowe ({len(keywords)}):"
    )

    for keyword in keywords:

        print(
            f"  - {keyword}"
        )

    # --------------------------------------
    # SŁOWA IGNOROWANE
    # --------------------------------------

    ignored_keywords = (
        load_ignored_keywords()
    )

    print(
        f"Ignorowane słowa/frazy "
        f"({len(ignored_keywords)}):"
    )

    for keyword in ignored_keywords:

        print(
            f"  - {keyword}"
        )

    # --------------------------------------
    # MYSQL
    # --------------------------------------

    if not wait_for_mysql():

        raise RuntimeError(
            "Nie udało się połączyć z MySQL."
        )

    total_found = 0
    total_saved = 0
    total_ignored = 0

    # --------------------------------------
    # PLAYWRIGHT
    # --------------------------------------

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

            for index, keyword in enumerate(
                keywords
            ):

                # ----------------------------------
                # PRZERWA MIĘDZY WYSZUKIWANIAMI
                # ----------------------------------

                if index > 0:

                    delay = random.uniform(
                        MIN_DELAY,
                        MAX_DELAY,
                    )

                    print(
                        f"\nPrzerwa przed kolejnym "
                        f"wyszukiwaniem: "
                        f"{delay:.1f} s"
                    )

                    time.sleep(
                        delay
                    )

                # ----------------------------------
                # SCRAPING
                # ----------------------------------

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

                    # ------------------------------
                    # FILTROWANIE I ZAPIS
                    # ------------------------------

                    for job in jobs:

                        if is_ignored_job(
                            job["title"],
                            ignored_keywords,
                        ):

                            print(
                                f"[IGNORUJ] "
                                f"{job['title']}"
                            )

                            total_ignored += 1

                            continue

                        save_job(
                            job
                        )

                        total_saved += 1

                except Exception as error:

                    print(
                        f"[ERROR] Just Join IT "
                        f"dla '{keyword}': "
                        f"{error}"
                    )

        finally:

            context.close()
            browser.close()

    # --------------------------------------
    # PODSUMOWANIE
    # --------------------------------------

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
        f"Zapisano/zaaktualizowano: "
        f"{total_saved}"
    )

    print(
        f"Zignorowano: {total_ignored}"
    )

    print(
        "PRZEBIEG ZAKOŃCZONY"
    )


# ==========================================
# ARGUMENTY
# ==========================================

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
            "Interwał między przebiegami "
            "w sekundach."
        ),
    )

    return parser.parse_args()


# ==========================================
# MAIN
# ==========================================

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

    # --------------------------------------
    # JEDEN PRZEBIEG
    # --------------------------------------

    if args.once:

        print(
            "Tryb: JEDEN PRZEBIEG"
        )

        run_scrape()

        return

    # --------------------------------------
    # TRYB CIĄGŁY
    # --------------------------------------

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
                f"BŁĄD PODCZAS PRZEBIEGU: "
                f"{error}"
            )

        print(
            f"\nNastępny przebieg za "
            f"{args.interval} sekund."
        )

        time.sleep(
            args.interval
        )


# ==========================================
# START
# ==========================================

if __name__ == "__main__":
    main()