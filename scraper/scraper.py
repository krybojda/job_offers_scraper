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


SCRAPE_INTERVAL = 3600

# Przerwa między kolejnymi wyszukiwaniami.
MIN_DELAY = 20
MAX_DELAY = 40

BASE_URL = "https://justjoin.it"

HEADLESS = True

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


# =========================================================
# MYSQL
# =========================================================

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
    """Czeka na dostępność MySQL."""

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


# =========================================================
# PLIKI KONFIGURACYJNE
# =========================================================

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
        print(
            "BŁĄD: Nie znaleziono pliku keywords.txt"
        )
        raise


def load_ignored_keywords():
    """
    Wczytuje ignorowane słowa i frazy
    z ignored_keywords.txt.
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
        return []


def is_ignored_job(title, ignored_keywords):
    """
    Sprawdza, czy tytuł zawiera ignorowane
    słowo albo frazę.

    Pojedyncze słowa:
        lead -> pasuje do "Team Lead"
        lead -> NIE pasuje do "Leadership"

    Frazy:
        team lead -> pasuje do "DevOps Team Lead"
    """

    if not title or not ignored_keywords:
        return False

    title_lower = title.lower().strip()

    for keyword in ignored_keywords:

        keyword = keyword.strip().lower()

        if not keyword:
            continue

        # Fraza, np.:
        # team lead
        if " " in keyword:

            if keyword in title_lower:
                return True

            continue

        # Pojedyncze słowo:
        # lead
        pattern = rf"\b{re.escape(keyword)}\b"

        if re.search(
            pattern,
            title_lower,
        ):
            return True

    return False


# =========================================================
# IDENTYFIKACJA OFERTY
# =========================================================

def generate_source_id(url):
    """
    Tworzy stabilny identyfikator oferty
    na podstawie URL.

    Parametry po '?' są pomijane.
    """

    normalized_url = (
        url
        .split("?")[0]
        .rstrip("/")
    )

    return hashlib.sha256(
        normalized_url.encode("utf-8")
    ).hexdigest()


# =========================================================
# ZAPIS DO MYSQL
# =========================================================

def save_job(job):
    """
    Dodaje nową ofertę albo aktualizuje istniejącą.

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


# =========================================================
# TEKST
# =========================================================

def clean_text(value):
    """
    Normalizuje białe znaki.
    """

    if not value:
        return None

    value = " ".join(
        value.split()
    )

    return value if value else None


# =========================================================
# TYTUŁ OFERTY
# =========================================================

def extract_candidate_title(item):
    """
    Próbuje znaleźć tytuł oferty.

    Kolejność:
    1. headingi,
    2. aria-label,
    3. title atrybutu,
    4. tekst linku,
    5. pierwszy sensowny wiersz karty.
    """

    headings = (
        item.get("headings")
        or []
    )

    # -----------------------------------------
    # Headingi
    # -----------------------------------------

    for text in headings:

        text = clean_text(text)

        if text:
            return text

    # -----------------------------------------
    # aria-label
    # -----------------------------------------

    aria_label = clean_text(
        item.get("ariaLabel")
    )

    if aria_label:
        return aria_label

    # -----------------------------------------
    # title atrybutu
    # -----------------------------------------

    link_title = clean_text(
        item.get("linkTitle")
    )

    if link_title:
        return link_title

    # -----------------------------------------
    # tekst linku
    # -----------------------------------------

    link_text = clean_text(
        item.get("linkText")
    )

    if link_text:
        return link_text

    # -----------------------------------------
    # awaryjnie tekst karty
    # -----------------------------------------

    card_text = clean_text(
        item.get("cardText")
    )

    if card_text:

        lines = [
            clean_text(line)
            for line in card_text.split("\n")
            if clean_text(line)
        ]

        if lines:
            return lines[0]

    return None


# =========================================================
# NORMALIZACJA POJEDYNCZEJ OFERTY
# =========================================================

def extract_job_from_raw_item(item, keyword):
    """
    Zamienia surowy rekord pobrany z DOM
    na rekord gotowy do zapisania w MySQL.
    """

    href = clean_text(
        item.get("href")
    )

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

    # -----------------------------------------
    # TYTUŁ
    # -----------------------------------------

    title = extract_candidate_title(
        item
    )

    if not title:
        return None

    # -----------------------------------------
    # TEKST KARTY
    # -----------------------------------------

    card_text = clean_text(
        item.get("cardText")
    )

    lines = []

    if card_text:

        lines = [
            clean_text(line)
            for line in card_text.split("\n")
            if clean_text(line)
        ]

    # -----------------------------------------
    # PUSTE POLA
    # -----------------------------------------

    company = None
    location = None
    work_mode = None
    salary = None

    # -----------------------------------------
    # TRYB PRACY
    # -----------------------------------------

    for line in lines:

        normalized = line.lower()

        if normalized in {
            "remote",
            "hybrid",
            "office",
        }:

            work_mode = line

            break

    # -----------------------------------------
    # WYNAGRODZENIE
    # -----------------------------------------

    salary_tokens = (
        "usd",
        "eur",
        "pln",
        "gbp",
        "chf",
        "/month",
        "/h",
        "month",
    )

    for line in lines:

        line_lower = line.lower()

        if any(
            token in line_lower
            for token in salary_tokens
        ):

            salary = line

            break

    # -----------------------------------------
    # LOKALIZACJA
    # -----------------------------------------

    if work_mode:

        try:

            mode_index = lines.index(
                work_mode
            )

            if mode_index > 0:

                candidate = lines[
                    mode_index - 1
                ]

                if (
                    candidate != title
                    and candidate != salary
                ):

                    location = candidate

        except ValueError:
            pass

    # -----------------------------------------
    # FIRMA
    # -----------------------------------------

    ignored_lines = {
        title,
        location,
        salary,
        work_mode,
        "Remote",
        "Hybrid",
        "Office",
        "New",
        "Super offer",
        "1-click Apply",
    }

    for line in lines:

        if line in ignored_lines:
            continue

        if len(line) <= 1:
            continue

        company = line

        break

    # -----------------------------------------
    # REKORD
    # -----------------------------------------

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


# =========================================================
# URL JUST JOIN IT
# =========================================================

def build_justjoin_url(keyword):
    """
    Buduje URL wyszukiwania Just Join IT.

    Pojedyncze słowo:
        /job-offers/all-locations/devops

    Fraza:
        /job-offers/all-locations/devops
        ?q=devops%20engineer%40keyword
    """

    normalized = keyword.strip()

    # -----------------------------------------
    # POJEDYNCZE SŁOWO
    # -----------------------------------------

    if " " not in normalized:

        slug = quote(
            normalized.lower()
        )

        return (
            f"{BASE_URL}/job-offers/"
            f"all-locations/{slug}"
        )

    # -----------------------------------------
    # FRAZA
    # -----------------------------------------

    encoded = quote(
        normalized
    )

    return (
        f"{BASE_URL}/job-offers/"
        f"all-locations/devops"
        f"?q={encoded}%40keyword"
    )


# =========================================================
# SCRAPOWANIE JUST JOIN IT
# =========================================================

def scrape_justjoin_page(page, keyword):
    """
    Pobiera jedną stronę wyników Just Join IT.

    Dane są najpierw pobierane z DOM do zwykłej
    listy Python. Nie iterujemy później po dynamicznych
    locatorach nth().
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

    # -----------------------------------------
    # OTWARCIE STRONY
    # -----------------------------------------

    try:

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        # Czekamy na renderowanie JS.
        page.wait_for_timeout(
            7000
        )

    except PlaywrightTimeoutError:

        print(
            f"[WARN] Timeout podczas "
            f"ładowania: {url}"
        )

        return []

    print(
        f"Załadowany URL: {page.url}"
    )

    # -----------------------------------------
    # CZEKAJ NA OFERTY
    # -----------------------------------------

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

    # -----------------------------------------
    # ODCZYT DOM JEDNORAZOWO
    # -----------------------------------------

    raw_jobs = page.evaluate(
        """
        () => {
            const links = Array.from(
                document.querySelectorAll(
                    "a[href*='/job-offer/']"
                )
            );

            return links
                .map((link) => {

                    const href =
                        link.getAttribute("href");

                    let card =
                        link.closest("article") ||
                        link.closest("li") ||
                        link.parentElement;

                    if (!card) {
                        return null;
                    }

                    const headings =
                        Array.from(
                            card.querySelectorAll(
                                "h1, h2, h3, h4"
                            )
                        )
                        .map(
                            (el) =>
                                (el.innerText || "")
                                    .trim()
                        )
                        .filter(Boolean);

                    return {
                        href: href || "",
                        linkText:
                            (link.innerText || "")
                                .trim(),
                        linkTitle:
                            link.getAttribute("title")
                            || "",
                        ariaLabel:
                            link.getAttribute(
                                "aria-label"
                            )
                            || "",
                        headings: headings,
                        cardText:
                            (card.innerText || "")
                                .trim()
                    };
                })
                .filter(Boolean);
        }
        """
    )

    print(
        "Znaleziono elementów z linkiem ofert: "
        f"{len(raw_jobs)}"
    )

    if not raw_jobs:
        return []

    # -----------------------------------------
    # DEBUG PIERWSZEGO REKORDU
    # -----------------------------------------

    first = raw_jobs[0]

    print(
        "\n--- DEBUG PIERWSZEJ OFERTY ---"
    )

    print(
        f"href: {first.get('href')}"
    )

    print(
        f"linkText: {first.get('linkText')}"
    )

    print(
        f"linkTitle: {first.get('linkTitle')}"
    )

    print(
        f"ariaLabel: {first.get('ariaLabel')}"
    )

    print(
        f"headings: {first.get('headings')}"
    )

    print(
        "cardText: "
        f"{first.get('cardText', '')[:800]}"
    )

    print(
        "--- KONIEC DEBUG ---\n"
    )

    # -----------------------------------------
    # NORMALIZACJA
    # -----------------------------------------

    jobs = []

    seen = set()

    for item in raw_jobs:

        try:

            job = extract_job_from_raw_item(
                item,
                keyword,
            )

        except Exception as error:

            print(
                "[WARN] Błąd podczas "
                "przetwarzania jednej oferty: "
                f"{error}"
            )

            continue

        if not job:
            continue

        # -----------------------------------------
        # DEDUPLIKACJA
        # -----------------------------------------

        if job["source_id"] in seen:
            continue

        seen.add(
            job["source_id"]
        )

        jobs.append(
            job
        )

    print(
        "Unikalnych ofert do przetworzenia: "
        f"{len(jobs)}"
    )

    return jobs


# =========================================================
# PEŁNY PRZEBIEG
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

    # -----------------------------------------
    # SŁOWA WYSZUKIWANIA
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
    # SŁOWA IGNOROWANE
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
                # SCRAPING
                # -----------------------------------------

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

                    # -----------------------------------------
                    # FILTROWANIE + ZAPIS
                    # -----------------------------------------

                    for job in jobs:

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
            f"\nNastępny przebieg za "
            f"{args.interval} sekund."
        )

        time.sleep(
            args.interval
        )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()