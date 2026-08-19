import re
from datetime import datetime
from urllib.parse import quote, urljoin

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from config import (
    PRACUJ_BASE_URL,
    PRACUJ_MAX_PAGES,
)

from utils import (
    clean_text,
    generate_source_id,
)


# =========================================================
# BLOKADY
# =========================================================

class PracujBlockedError(Exception):
    """
    Oznacza wykrycie blokady / rate limitu
    na Pracuj.pl.
    """


BLOCK_STATUS_CODES = {
    403,
    429,
    503,
}


BLOCK_TEXT_PATTERNS = [
    "access denied",
    "too many requests",
    "request blocked",
    "request has been blocked",
    "verify you are human",
    "verify that you are human",
    "checking your browser",
    "attention required! | cloudflare",
    "unusual traffic",
]


def detect_pracuj_block(
    response,
    page,
):
    """
    Wykrywa blokadę Pracuj.pl.

    Samo wystąpienie słowa captcha
    NIE oznacza blokady.
    """

    # -----------------------------------------------------
    # STATUS HTTP
    # -----------------------------------------------------

    if response is not None:

        status = response.status

        if status in BLOCK_STATUS_CODES:

            return (
                f"HTTP {status}"
            )

    # -----------------------------------------------------
    # TEKST STRONY
    # -----------------------------------------------------

    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        body_text = body_text.lower()

    except Exception:

        return None

    for pattern in BLOCK_TEXT_PATTERNS:

        if pattern in body_text:

            return (
                "wykryto tekst blokady: "
                f"{pattern}"
            )

    return None


# =========================================================
# DATA PUBLIKACJI
# =========================================================

POLISH_MONTHS = {
    "stycznia": 1,
    "lutego": 2,
    "marca": 3,
    "kwietnia": 4,
    "maja": 5,
    "czerwca": 6,
    "lipca": 7,
    "sierpnia": 8,
    "września": 9,
    "października": 10,
    "listopada": 11,
    "grudnia": 12,
}


def parse_published_date_text(
    text,
):
    """
    Parsuje np.:

        Opublikowana: 8 sierpnia 2026

    oraz:

        Opublikowana: 8 sierpnia 2026
    """

    if not text:
        return None

    pattern = re.compile(
        r"""
        opublikowana
        \s*:\s*
        (\d{1,2})
        \s+
        ([a-ząćęłńóśźż]+)
        \s+
        (\d{4})
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    match = pattern.search(
        text
    )

    if not match:
        return None

    day = int(
        match.group(1)
    )

    month_name = (
        match.group(2)
        .lower()
    )

    year = int(
        match.group(3)
    )

    month = POLISH_MONTHS.get(
        month_name
    )

    if month is None:
        return None

    try:

        return datetime(
            year,
            month,
            day,
        )

    except ValueError:

        return None


# =========================================================
# WYNAGRODZENIE
# =========================================================

def find_salary(
    lines,
):
    """
    Szuka wynagrodzenia.

    Obsługuje np.:

        20 000–25 000 zł brutto / mies.

        130–150 zł netto (+ VAT) / godz.

        120–160 zł netto (+ VAT) / godz.
    """

    salary_patterns = [
        re.compile(
            r"""
            \d[\d\s.,]*
            \s*[–-]\s*
            \d[\d\s.,]*
            \s*
            (zł|zl|pln|eur|usd|gbp|chf)
            .*?
            """,
            re.IGNORECASE | re.VERBOSE,
        ),

        re.compile(
            r"""
            \d[\d\s.,]*
            \s*
            (zł|zl|pln|eur|usd|gbp|chf)
            .*?
            """,
            re.IGNORECASE | re.VERBOSE,
        ),
    ]

    for line in lines:

        if not line:
            continue

        for pattern in salary_patterns:

            if pattern.search(
                line
            ):

                return line

    return None


# =========================================================
# LOKALIZACJA
# =========================================================

def find_location(
    lines,
    company=None,
):
    """
    Próbuje rozpoznać lokalizację.

    Przykłady Pracuj:

        Warszawa

        Kraków, Grzegórzki

        Miejsce pracy:Cała Polska (praca zdalna)
        Siedziba firmy:Warszawa

        3 lokalizacje
    """

    location_prefix = (
        "miejsce pracy:"
    )

    company_index = None

    if company:

        company_lower = (
            company.lower()
        )

        for index, line in enumerate(
            lines
        ):

            if (
                line.lower().strip()
                == company_lower.strip()
            ):

                company_index = index
                break

    # -----------------------------------------------------
    # Miejsce pracy:
    # -----------------------------------------------------

    for line in lines:

        normalized = (
            line.lower().strip()
        )

        if normalized.startswith(
            location_prefix
        ):

            value = line[
                len(location_prefix):
            ].strip()

            if value:
                return value

    # -----------------------------------------------------
    # "3 lokalizacje"
    # -----------------------------------------------------

    for line in lines:

        if re.fullmatch(
            r"\d+\s+lokalizacje?",
            line.strip(),
            re.IGNORECASE,
        ):

            return line

    # -----------------------------------------------------
    # Lokalizacja zaraz po firmie.
    # -----------------------------------------------------

    if company_index is not None:

        for index in range(
            company_index + 1,
            min(
                company_index + 5,
                len(lines),
            ),
        ):

            candidate = lines[
                index
            ].strip()

            if not candidate:
                continue

            if candidate.lower().startswith(
                "miejsce pracy:"
            ):
                return candidate

            if candidate.lower() in {
                "superoferta",
                "aplikuj szybko",
            }:
                continue

            if re.search(
                r"\b("
                r"Warszawa|"
                r"Kraków|"
                r"Wrocław|"
                r"Poznań|"
                r"Gdańsk|"
                r"Katowice|"
                r"Łódź|"
                r"Lublin|"
                r"Białystok|"
                r"Rzeszów|"
                r"Bydgoszcz|"
                r"Szczecin|"
                r"Krakow|"
                r"Wroclaw|"
                r"Poznan|"
                r"Gdansk|"
                r"Lodz"
                r")\b",
                candidate,
                re.IGNORECASE,
            ):

                return candidate

    return None


# =========================================================
# TRYB PRACY
# =========================================================

def find_work_mode(
    lines,
):
    """
    Praca zdalna / hybrydowa / stacjonarna.
    """

    found = []

    for line in lines:

        normalized = (
            line.lower()
        )

        if (
            "praca zdalna"
            in normalized
        ):

            found.append(
                "Praca zdalna"
            )

        if (
            "praca hybrydowa"
            in normalized
        ):

            found.append(
                "Praca hybrydowa"
            )

        if (
            "praca stacjonarna"
            in normalized
        ):

            found.append(
                "Praca stacjonarna"
            )

    if not found:
        return None

    return ", ".join(
        dict.fromkeys(found)
    )


# =========================================================
# TYP PRACY
# =========================================================

def find_work_type(
    lines,
):
    """
    Pełny etat / część etatu itd.
    """

    found = []

    for line in lines:

        normalized = (
            line.lower()
            .strip()
        )

        if (
            normalized == "pełny etat"
        ):

            found.append(
                "Pełny etat"
            )

        elif (
            normalized == "część etatu"
        ):

            found.append(
                "Część etatu"
            )

        elif (
            normalized
            == "niepełny etat"
        ):

            found.append(
                "Niepełny etat"
            )

    if not found:
        return None

    return ", ".join(
        dict.fromkeys(found)
    )


# =========================================================
# DOŚWIADCZENIE
# =========================================================

def find_experience_level(
    lines,
):
    """
    Zwraca pełną linię poziomu,
    np.:

        Specjalista / Specjalistka
        (mid / Regular), Starszy ...
    """

    found = []

    for line in lines:

        normalized = (
            line.lower()
        )

        if (
            "(junior)"
            in normalized
            or "(mid"
            in normalized
            or "(regular)"
            in normalized
            or "(senior)"
            in normalized
            or "(expert)"
            in normalized
            or "(ekspert"
            in normalized
        ):

            found.append(
                line
            )

    if not found:
        return None

    return ", ".join(
        dict.fromkeys(found)
    )


# =========================================================
# UMOWA
# =========================================================

def find_contract_type(
    lines,
):
    """
    Zwraca informacje o umowie.
    """

    contract_patterns = [
        "umowa o pracę",
        "umowa zlecenie",
        "kontrakt b2b",
        "umowa o dzieło",
        "kontrakt",
        "b2b",
    ]

    found = []

    for line in lines:

        normalized = (
            line.lower()
        )

        matches = []

        for pattern in contract_patterns:

            if pattern in normalized:
                matches.append(
                    pattern
                )

        if matches:

            found.append(
                line
            )

    if not found:
        return None

    return ", ".join(
        dict.fromkeys(found)
    )


# =========================================================
# POMOCNICZE CZYSZCZENIE LINII
# =========================================================

def clean_lines(
    text,
):
    """
    Czyści tekst, zachowując podział
    na osobne linie.
    """

    if not text:
        return []

    lines = []

    for line in text.splitlines():

        line = " ".join(
            line.split()
        ).strip()

        if line:
            lines.append(
                line
            )

    return lines


# =========================================================
# WYCIĄGANIE SEKCJI
# =========================================================

def extract_section(
    lines,
    start_patterns,
    end_patterns,
):
    """
    Wyciąga zawartość pomiędzy nagłówkami.
    """

    start_index = None

    start_patterns = [
        item.lower()
        for item in start_patterns
    ]

    end_patterns = [
        item.lower()
        for item in end_patterns
    ]

    for index, line in enumerate(
        lines
    ):

        normalized = (
            line.lower()
            .strip()
        )

        if any(
            pattern in normalized
            for pattern in start_patterns
        ):

            start_index = index + 1
            break

    if start_index is None:
        return None

    end_index = len(lines)

    for index in range(
        start_index,
        len(lines),
    ):

        normalized = (
            lines[index]
            .lower()
            .strip()
        )

        if any(
            pattern in normalized
            for pattern in end_patterns
        ):

            end_index = index
            break

    section = lines[
        start_index:end_index
    ]

    if not section:
        return None

    return "\n".join(
        section
    ).strip()


# =========================================================
# WYGAŚNIĘCIE
# =========================================================

def find_expiration(
    lines,
):
    """
    Pracuj nie musi udostępniać terminu
    wygaśnięcia w taki sam sposób jak Just Join.

    Zwraca tekst, jeżeli znajdziemy odpowiednią
    informację.
    """

    for line in lines:

        normalized = (
            line.lower()
        )

        if (
            "oferta wygasa"
            in normalized
            or "ważna do"
            in normalized
            or "ważne do"
            in normalized
        ):

            return (
                line,
                None,
            )

    return (
        None,
        None,
    )


# =========================================================
# BUDOWANIE URL
# =========================================================

def build_pracuj_url(
    keyword,
    page_number=1,
):
    """
    Buduje URL wyszukiwania Pracuj.pl.

    Przykład:

        /praca/devops%20engineer%3Bkw

    Kolejna strona:

        ?pn=2
    """

    encoded_keyword = quote(
        keyword.strip(),
        safe="",
    )

    url = (
        f"{PRACUJ_BASE_URL}/praca/"
        f"{encoded_keyword}%3Bkw"
    )

    if page_number > 1:

        url += (
            f"?pn={page_number}"
        )

    return url


# =========================================================
# PARSOWANIE KARTY
# =========================================================

def extract_job_from_raw_item(
    item,
    keyword,
):
    """
    Zamienia kartę wyników Pracuj.pl
    na wspólny format job.
    """

    href = (
        item.get("href")
        or ""
    ).strip()

    if not href:
        return None

    if ",oferta," not in href.lower():
        return None

    url = urljoin(
        PRACUJ_BASE_URL,
        href,
    )

    source_id = generate_source_id(
        url
    )

    title = clean_text(
        item.get("title")
    )

    if not title:
        return None

    company = clean_text(
        item.get("company")
    )

    raw_card_text = (
        item.get("cardText")
        or ""
    )

    lines = clean_lines(
        raw_card_text
    )

    if not lines:
        return None

    if not company:

        # Awaryjnie szukamy linii znajdującej
        # się po tytule.
        try:

            title_index = (
                lines.index(
                    title
                )
            )

            if (
                title_index + 1
                < len(lines)
            ):

                candidate = lines[
                    title_index + 1
                ]

                if candidate:

                    company = candidate

        except ValueError:

            pass

    location = find_location(
        lines,
        company,
    )

    work_mode = find_work_mode(
        lines
    )

    work_type = find_work_type(
        lines
    )

    experience_level = (
        find_experience_level(
            lines
        )
    )

    contract_type = (
        find_contract_type(
            lines
        )
    )

    salary = find_salary(
        lines
    )

    published_at = (
        parse_published_date_text(
            raw_card_text
        )
    )

    return {
        "portal": "pracuj",
        "source_id": source_id,
        "title": title,
        "company": company,
        "location": location,
        "work_mode": work_mode,
        "work_type": work_type,
        "salary": salary,
        "url": url,
        "keyword": keyword,
        "published_at": published_at,
    }


# =========================================================
# POBRANIE JEDNEJ STRONY
# =========================================================

def scrape_pracuj_page(
    page,
    keyword,
    page_number,
):
    """
    Pobiera jedną stronę wyników Pracuj.pl.

    Zwraca:
        jobs
        page_ok
        current_page
        total_pages
    """

    url = build_pracuj_url(
        keyword,
        page_number,
    )

    print(
        f"\nPracuj.pl → {keyword}"
    )

    print(
        f"Strona: {page_number}"
    )

    print(
        f"URL: {url}"
    )

    # -----------------------------------------------------
    # OTWARCIE
    # -----------------------------------------------------

    try:

        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(
            5000
        )

    except PlaywrightTimeoutError:

        print(
            "[WARN] Timeout podczas "
            f"ładowania: {url}"
        )

        block_reason = (
            detect_pracuj_block(
                None,
                page,
            )
        )

        if block_reason:

            raise PracujBlockedError(
                block_reason
            )

        return [], False, page_number, 0

    # -----------------------------------------------------
    # BLOKADA
    # -----------------------------------------------------

    block_reason = detect_pracuj_block(
        response,
        page,
    )

    if block_reason:

        print(
            "\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
            "!!! BLOKADA PRACUJ.PL !!!\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        print(
            f"Powód: {block_reason}"
        )

        print(
            "Scrapowanie Pracuj.pl "
            "zostało zatrzymane."
        )

        raise PracujBlockedError(
            block_reason
        )

    print(
        f"Załadowany URL: {page.url}"
    )

    # -----------------------------------------------------
    # CZEKAJ NA OFERTY
    # -----------------------------------------------------

    try:

        page.locator(
            "a[href*=',oferta,']"
        ).first.wait_for(
            timeout=30000
        )

    except PlaywrightTimeoutError:

        block_reason = detect_pracuj_block(
            response,
            page,
        )

        if block_reason:

            raise PracujBlockedError(
                block_reason
            )

        print(
            "Nie znaleziono linków "
            "do ofert na stronie."
        )

        return [], False, page_number, 0

    # -----------------------------------------------------
    # LICZBA STRON
    # -----------------------------------------------------

    total_pages = PRACUJ_MAX_PAGES

    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        match = re.search(
            r"Strona\s+\d+\s+z\s+(\d+)",
            body_text,
            re.IGNORECASE,
        )

        if match:

            total_pages = min(
                int(
                    match.group(1)
                ),
                PRACUJ_MAX_PAGES,
            )

    except Exception:

        pass

    # -----------------------------------------------------
    # DOM
    # -----------------------------------------------------

    raw_jobs = page.evaluate(
        """
        () => {

            const links = Array.from(
                document.querySelectorAll(
                    "a[href*=',oferta,']"
                )
            );

            return links
                .map((link) => {

                    const href =
                        link.getAttribute(
                            "href"
                        );

                    if (!href) {
                        return null;
                    }

                    const card =
                        link.closest(
                            "article"
                        ) ||
                        link.closest(
                            "li"
                        ) ||
                        link.parentElement;

                    if (!card) {
                        return null;
                    }

                    const companyLink =
                        card.querySelector(
                            "a[href*='pracodawcy.pracuj.pl']"
                        );

                    return {

                        href:
                            href,

                        title:
                            (
                                link.innerText
                                || ""
                            ).trim(),

                        company:
                            companyLink
                                ? (
                                    companyLink.innerText
                                    || ""
                                ).trim()
                                : "",

                        cardText:
                            (
                                card.innerText
                                || ""
                            ).trim()
                    };
                })
                .filter(Boolean);
        }
        """
    )

    print(
        "Znaleziono elementów "
        "z linkiem ofert: "
        f"{len(raw_jobs)}"
    )

    if not raw_jobs:

        print(
            "Brak ofert na tej stronie."
        )

        return [], False, page_number, total_pages

    # -----------------------------------------------------
    # NORMALIZACJA
    # -----------------------------------------------------

    jobs = []

    seen = set()

    for item in raw_jobs:

        try:

            job = (
                extract_job_from_raw_item(
                    item,
                    keyword,
                )
            )

        except Exception as error:

            print(
                "[WARN] Błąd podczas "
                f"przetwarzania oferty: "
                f"{error}"
            )

            continue

        if not job:
            continue

        if job["source_id"] in seen:
            continue

        seen.add(
            job["source_id"]
        )

        jobs.append(
            job
        )

    print(
        "Unikalnych ofert na stronie: "
        f"{len(jobs)}"
    )

    if jobs:

        first = jobs[0]

        print(
            "\n--- PODGLĄD PRACUJ ---"
        )

        print(
            f"Tytuł: {first['title']}"
        )

        print(
            f"Firma: {first['company']}"
        )

        print(
            f"Lokalizacja: {first['location']}"
        )

        print(
            f"Tryb: {first['work_mode']}"
        )

        print(
            f"Wynagrodzenie: {first['salary']}"
        )

        print(
            f"Opublikowano: "
            f"{first['published_at']}"
        )

        print(
            "--- KONIEC PODGLĄDU ---"
        )

    return (
        jobs,
        True,
        page_number,
        total_pages,
    )


# =========================================================
# PEŁNE WYSZUKIWANIE
# =========================================================

def scrape_pracuj(
    page,
    keyword,
    min_delay,
    max_delay,
):
    """
    Przechodzi przez wszystkie strony wyników
    dla jednego słowa kluczowego.

    Zwraca:
        jobs
        seen_source_ids
        scan_complete
    """

    all_jobs = []

    seen_source_ids = set()

    scan_complete = True

    first_page = 1
    total_pages = 1

    current_page = first_page

    while (
        current_page <= total_pages
        and current_page <= PRACUJ_MAX_PAGES
    ):

        # ---------------------------------------------
        # PRZERWA MIĘDZY STRONAMI
        # ---------------------------------------------

        if current_page > 1:

            import random
            import time

            delay = random.uniform(
                min_delay,
                max_delay,
            )

            print(
                "\nPrzerwa przed "
                "kolejną stroną Pracuj.pl: "
                f"{delay:.1f} s"
            )

            time.sleep(
                delay
            )

        try:

            (
                jobs,
                page_ok,
                current,
                detected_total_pages,
            ) = scrape_pracuj_page(
                page=page,
                keyword=keyword,
                page_number=current_page,
            )

            if detected_total_pages:
                total_pages = min(
                    detected_total_pages,
                    PRACUJ_MAX_PAGES,
                )

            if not page_ok:

                scan_complete = False

                break

            for job in jobs:

                if (
                    job["source_id"]
                    in seen_source_ids
                ):
                    continue

                seen_source_ids.add(
                    job["source_id"]
                )

                all_jobs.append(
                    job
                )

        except PracujBlockedError:

            scan_complete = False

            raise

        except Exception as error:

            print(
                "[ERROR] Pracuj.pl "
                f"strona {current_page}: "
                f"{error}"
            )

            scan_complete = False

            break

        current_page += 1

    print(
        "\nPracuj.pl → "
        f"{keyword}: łącznie "
        f"{len(all_jobs)} unikalnych ofert"
    )

    print(
        f"Pracuj.pl → liczba stron "
        f"przetworzonych: "
        f"{current_page - 1}"
    )

    return (
        all_jobs,
        seen_source_ids,
        scan_complete,
    )


# =========================================================
# SZCZEGÓŁY
# =========================================================

def scrape_pracuj_details(
    page,
    job,
):
    """
    Pobiera szczegóły pojedynczej oferty Pracuj.pl.
    """

    url = job["url"]

    print(
        f"[SZCZEGÓŁY PRACUJ] "
        f"{job['title']}"
    )

    # -----------------------------------------------------
    # OTWARCIE
    # -----------------------------------------------------

    try:

        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(
            5000
        )

    except PlaywrightTimeoutError:

        print(
            "[WARN] Timeout strony "
            f"szczegółowej: {url}"
        )

        block_reason = (
            detect_pracuj_block(
                None,
                page,
            )
        )

        if block_reason:

            raise PracujBlockedError(
                block_reason
            )

        return None

    # -----------------------------------------------------
    # BLOKADA
    # -----------------------------------------------------

    block_reason = detect_pracuj_block(
        response,
        page,
    )

    if block_reason:

        raise PracujBlockedError(
            block_reason
        )

    # -----------------------------------------------------
    # TEKST STRONY
    # -----------------------------------------------------

    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=10000
        )

    except Exception as error:

        print(
            "[WARN] Nie udało się "
            "odczytać strony szczegółowej: "
            f"{error}"
        )

        return None

    lines = clean_lines(
        body_text
    )

    if not lines:
        return None

    # -----------------------------------------------------
    # TYTUŁ
    # -----------------------------------------------------

    title = None

    try:

        title = clean_text(
            page.locator(
                "h1"
            ).first.inner_text(
                timeout=5000
            )
        )

    except Exception:

        pass

    if not title:

        title = job["title"]

    # -----------------------------------------------------
    # FIRMA
    # -----------------------------------------------------

    company = job["company"]

    try:

        company_link = page.locator(
            "a[href*='pracodawcy.pracuj.pl']"
        ).first

        if company_link.count() > 0:

            company_value = clean_text(
                company_link.inner_text(
                    timeout=3000
                )
            )

            if company_value:
                company = company_value

    except Exception:

        pass

    # -----------------------------------------------------
    # DATA PUBLIKACJI
    # -----------------------------------------------------

    published_at = (
        parse_published_date_text(
            body_text
        )
        or job["published_at"]
    )

    # -----------------------------------------------------
    # LOKALIZACJA
    # -----------------------------------------------------

    location = find_location(
        lines,
        company,
    )

    if not location:
        location = job["location"]

    # -----------------------------------------------------
    # PODSTAWOWE DANE
    # -----------------------------------------------------

    work_mode = (
        find_work_mode(lines)
        or job["work_mode"]
    )

    work_type = (
        find_work_type(lines)
        or job["work_type"]
    )

    experience_level = (
        find_experience_level(
            lines
        )
    )

    contract_type = (
        find_contract_type(
            lines
        )
    )

    salary = (
        find_salary(lines)
        or job["salary"]
    )

    # -----------------------------------------------------
    # OPIS
    # -----------------------------------------------------

    job_description = (
        extract_section(
            lines,
            [
                "twój zakres obowiązków",
                "zakres obowiązków",
                "twoje zadania",
                "obowiązki",
                "responsibilities",
            ],
            [
                "nasze wymagania",
                "wymagania",
                "wymagane umiejętności",
                "oferujemy",
                "benefity",
                "benefits",
            ],
        )
    )

    # -----------------------------------------------------
    # WYMAGANIA / TECHNOLOGIE
    # -----------------------------------------------------

    requirements = extract_section(
        lines,
        [
            "nasze wymagania",
            "wymagania",
            "wymagane umiejętności",
            "requirements",
        ],
        [
            "oferujemy",
            "benefity",
            "benefits",
            "o firmie",
            "about the company",
        ],
    )

    # -----------------------------------------------------
    # O FIRMIE
    # -----------------------------------------------------

    about_company = extract_section(
        lines,
        [
            "o firmie",
            "about the company",
            "oferujemy",
        ],
        [
            "benefity",
            "benefits",
            "aplikuj",
            "aplikowanie",
        ],
    )

    # -----------------------------------------------------
    # INFORMACJE O LOKALIZACJI
    # -----------------------------------------------------

    office_location = None

    for line in lines:

        normalized = line.lower()

        if (
            normalized.startswith(
                "miejsce pracy:"
            )
        ):

            office_location = line[
                len("miejsce pracy:"):
            ].strip()

            break

    # -----------------------------------------------------
    # WYGAŚNIĘCIE
    # -----------------------------------------------------

    expires_text, expires_at = (
        find_expiration(lines)
    )

    # -----------------------------------------------------
    # TECH STACK
    # -----------------------------------------------------
    #
    # Pracuj nie ma jednolitego pola "Tech stack"
    # dla wszystkich ofert. Na tym etapie zapisujemy
    # wymagania jako tech_stack, jeżeli są dostępne.
    #

    tech_stack = requirements

    # -----------------------------------------------------
    # WYNIK
    # -----------------------------------------------------

    return {
        "title": title,
        "company": company,
        "location": location,
        "work_mode": work_mode,
        "work_type": work_type,
        "experience_level": experience_level,
        "contract_type": contract_type,
        "salary": salary,
        "published_at": published_at,
        "job_description": job_description,
        "tech_stack": tech_stack,
        "office_location": office_location,
        "about_company": about_company,
        "expires_text": expires_text,
        "expires_at": expires_at,
    }