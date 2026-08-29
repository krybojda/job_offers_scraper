import re
from datetime import datetime
from urllib.parse import quote, urljoin

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from config import (
    PRACUJ_BASE_URL,
)

from utils import (
    clean_text,
    generate_source_id,
)


# =========================================================
# BLOKADA
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
    Wykrywa typową blokadę.

    Samo wystąpienie słowa "captcha"
    NIE jest traktowane jako blokada.
    """

    if response is not None:

        status = response.status

        if status in BLOCK_STATUS_CODES:
            return f"HTTP {status}"

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
# CZYSZCZENIE
# =========================================================

def clean_lines(text):
    """
    Czyści tekst, ale zachowuje podział na linie.
    """

    if not text:
        return []

    lines = []

    for line in text.splitlines():

        line = " ".join(
            line.split()
        ).strip()

        if line:
            lines.append(line)

    return lines


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


def parse_published_date(
    text,
):
    """
    Rozpoznaje:
        Opublikowana: 12 sierpnia 2026
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

    match = pattern.search(text)

    if not match:
        return None

    day = int(match.group(1))

    month_name = (
        match.group(2)
        .lower()
    )

    year = int(match.group(3))

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
    """

    range_pattern = re.compile(
        r"""
        \d[\d\s.,]*
        \s*[–-]\s*
        \d[\d\s.,]*
        \s*
        (?:zł|zl|pln|eur|usd|gbp|chf)
        .*?
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    single_pattern = re.compile(
        r"""
        \d[\d\s.,]*
        \s*
        (?:zł|zl|pln|eur|usd|gbp|chf)
        .*?
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    for line in lines:

        if range_pattern.search(line):
            return line

    for line in lines:

        if single_pattern.search(line):
            return line

    return None


# =========================================================
# LOKALIZACJA
# =========================================================

def find_location(
    lines,
):
    """
    Szuka lokalizacji oferty.
    """

    # Miejsce pracy: ...
    for line in lines:

        normalized = (
            line.lower()
            .strip()
        )

        if normalized.startswith(
            "miejsce pracy:"
        ):

            value = line[
                len("miejsce pracy:"):
            ].strip()

            if value:
                return value

    # np. "2 lokalizacje"
    for line in lines:

        if re.fullmatch(
            r"\d+\s+lokalizacj[ei]",
            line.strip(),
            re.IGNORECASE,
        ):

            return line

    # Siedziba firmy jako fallback
    for line in lines:

        normalized = (
            line.lower()
            .strip()
        )

        if normalized.startswith(
            "siedziba firmy:"
        ):

            value = line[
                len("siedziba firmy:"):
            ].strip()

            if value:
                return value

    # Typowe miasta
    location_pattern = re.compile(
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
        re.IGNORECASE,
    )

    for line in lines:

        if location_pattern.search(line):
            return line

    return None


# =========================================================
# TRYB PRACY
# =========================================================

def find_work_mode(
    lines,
):
    """
    Rozpoznaje tryb pracy.
    """

    found = []

    for line in lines:

        normalized = line.lower()

        if "praca zdalna" in normalized:

            found.append(
                "Praca zdalna"
            )

        if "praca hybrydowa" in normalized:

            found.append(
                "Praca hybrydowa"
            )

        if "praca stacjonarna" in normalized:

            found.append(
                "Praca stacjonarna"
            )

        if "praca mobilna" in normalized:

            found.append(
                "Praca mobilna"
            )

    if not found:
        return None

    return ", ".join(
        dict.fromkeys(found)
    )


# =========================================================
# WYMIAR PRACY
# =========================================================

def find_work_type(
    lines,
):
    """
    Rozpoznaje wymiar pracy.
    """

    found = []

    patterns = [
        (
            "pełny etat",
            "Pełny etat",
        ),
        (
            "część etatu",
            "Część etatu",
        ),
        (
            "dodatkowa / tymczasowa",
            "Dodatkowa / tymczasowa",
        ),
    ]

    for line in lines:

        normalized = line.lower()

        for pattern, value in patterns:

            if pattern in normalized:
                found.append(value)

    if not found:
        return None

    return ", ".join(
        dict.fromkeys(found)
    )


# =========================================================
# POZIOM
# =========================================================

def find_experience_level(
    lines,
):
    """
    Rozpoznaje poziom doświadczenia.
    """

    found = []

    bracket_patterns = [
        (
            r"\(\s*junior\s*\)",
            "Junior",
        ),
        (
            r"\(\s*mid\s*/?\s*regular\s*\)",
            "Mid / Regular",
        ),
        (
            r"\(\s*mid\s*\)",
            "Mid",
        ),
        (
            r"\(\s*regular\s*\)",
            "Regular",
        ),
        (
            r"\(\s*senior\s*\)",
            "Senior",
        ),
        (
            r"\(\s*expert\s*\)",
            "Expert",
        ),
        (
            r"\(\s*ekspert\s*\)",
            "Ekspert",
        ),
    ]

    for line in lines:

        for pattern, value in bracket_patterns:

            if re.search(
                pattern,
                line,
                re.IGNORECASE,
            ):

                found.append(value)

    # Fallback dla pełnych polskich nazw
    if not found:

        for line in lines:

            normalized = line.lower()

            if "młodszy specjalista" in normalized:

                found.append("Junior")

            elif "starszy specjalista" in normalized:

                found.append("Senior")

            elif "ekspert / ekspertka" in normalized:

                found.append("Ekspert")

            elif "specjalista / specjalistka" in normalized:

                found.append("Specjalista")

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
    Rozpoznaje typ umowy.
    """

    found = []

    patterns = [
        (
            "kontrakt b2b",
            "Kontrakt B2B",
        ),
        (
            "umowa o pracę",
            "Umowa o pracę",
        ),
        (
            "umowa o dzieło",
            "Umowa o dzieło",
        ),
        (
            "umowa zlecenie",
            "Umowa zlecenie",
        ),
        (
            "umowa na zastępstwo",
            "Umowa na zastępstwo",
        ),
        (
            "umowa agencyjna",
            "Umowa agencyjna",
        ),
        (
            "umowa o pracę tymczasową",
            "Umowa o pracę tymczasową",
        ),
        (
            "umowa o staż / praktyki",
            "Umowa o staż / praktyki",
        ),
    ]

    for line in lines:

        normalized = line.lower()

        for pattern, value in patterns:

            if pattern in normalized:
                found.append(value)

    if not found:
        return None

    return ", ".join(
        dict.fromkeys(found)
    )


# =========================================================
# TYTUŁ
# =========================================================

def find_title(
    item,
):
    """
    Tytuł pobieramy z linku oferty.
    """

    title = clean_text(
        item.get("title")
    )

    if title:
        return title

    for heading in (
        item.get("headings")
        or []
    ):

        heading = clean_text(
            heading
        )

        if heading:
            return heading

    return None


# =========================================================
# KARTA OFERTY
# =========================================================

def extract_job_from_raw_item(
    item,
    keyword,
):
    """
    Zamienia dane karty HTML na rekord
    w jednolitym formacie.
    """

    href = (
        item.get("href")
        or ""
    ).strip()

    if not href:
        return None

    if ",oferta," not in href.lower():
        return None

    if "projekt-grant" in href.lower() or "button-add-announcement" in href.lower():
        return None

    url = urljoin(
        PRACUJ_BASE_URL,
        href,
    )

    source_id = generate_source_id(
        url
    )

    card_text = (
        item.get("cardText")
        or ""
    )

    lines = clean_lines(
        card_text
    )

    if not lines:
        return None

    title = find_title(
        item
    )

    if not title or title.lower() in {"sprawdź!", "sprawdz!", "aplikuj", "aplikuj szybko", "superoferta", "nowość", "nowosc"}:
        return None

    # -----------------------------------------------------
    # FIRMA
    # -----------------------------------------------------

    company = clean_text(
        item.get("company")
    )

    if not company:
        # Awaryjny fallback.
        title_index = None

        for index, line in enumerate(lines):
            if (
                line.strip()
                == title.strip()
            ):
                title_index = index
                break

        if title_index is not None:
            for candidate in lines[
                title_index + 1:
            ]:
                candidate = clean_text(
                    candidate
                )
                if not candidate:
                    continue

                if "opublikowana:" in candidate.lower():
                    continue

                if re.search(
                    r"\d[\d\s.,]*\s*(?:[–-]\s*\d[\d\s.,]*)?\s*(?:zł|zl|pln|eur|usd|gbp|chf)",
                    candidate,
                    re.IGNORECASE,
                ):
                    continue

                if re.search(r"/\s*(?:godz|mies|m-c|rok|h|month|day)", candidate, re.IGNORECASE):
                    continue

                if candidate.lower() in {
                    "superoferta",
                    "aplikuj szybko",
                    "oferta wygasa",
                    "sprawdź profil firmy",
                    "sprawdz profil firmy",
                    "nowość",
                    "nowosc",
                }:
                    continue

                if re.search(r"^\d+\s+lokalizacj[ei]", candidate, re.IGNORECASE):
                    continue

                company = candidate
                break

    # -----------------------------------------------------
    # POLA
    # -----------------------------------------------------

    location = find_location(lines)

    work_mode = find_work_mode(lines)

    work_type = find_work_type(lines)

    experience_level = (
        find_experience_level(lines)
    )

    contract_type = (
        find_contract_type(lines)
    )

    salary = find_salary(lines)

    published_at = (
        parse_published_date(card_text)
    )

    # -----------------------------------------------------
    # REKORD
    # -----------------------------------------------------

    return {
        "portal": "pracuj",
        "source_id": source_id,
        "title": title,
        "company": company,
        "location": location,
        "work_mode": work_mode,
        "work_type": work_type,
        "experience_level": experience_level,
        "contract_type": contract_type,
        "salary": salary,
        "url": url,
        "keyword": keyword,
        "published_at": published_at,
    }


# =========================================================
# URL
# =========================================================

def build_pracuj_url(
    keyword,
    page_number=1,
):
    """
    Buduje URL wyszukiwania Pracuj.pl.
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
# JEDNA STRONA
# =========================================================

def scrape_pracuj_page(
    page,
    keyword,
    page_number=1,
):
    """
    Pobiera jedną stronę wyników.

    Na obecnym etapie używamy tylko strony 1.
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

        block_reason = detect_pracuj_block(
            None,
            page,
        )

        if block_reason:

            raise PracujBlockedError(
                block_reason
            )

        return [], False

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
            "[data-test='link-offer-title'], [data-test='default-offer'], [data-test='positioned-offer'], a[href*=',oferta,']"
        ).first.wait_for(
            state="attached",
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
            "Nie znaleziono ofert."
        )

        return [], False

    # -----------------------------------------------------
    # POBIERZ LINKI
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

                    /*
                    * Szukamy możliwie najbliższej
                    * karty oferty.
                    *
                    * Kolejność:
                    * 1. article
                    * 2. li
                    * 3. parentElement
                    */

                    const card =
                        link.closest("article") ||
                        link.closest("li") ||
                        link.parentElement;

                    if (!card) {
                        return null;
                    }

                    /*
                    * Firma - próbujemy znaleźć
                    * link do profilu pracodawcy.
                    */

                    const companyLink =
                        card.querySelector("[data-test='link-company-profile']") ||
                        Array.from(
                            card.querySelectorAll(
                                "a"
                            )
                        )
                        .find(
                            (a) =>
                                (
                                    a.getAttribute(
                                        "href"
                                    ) || ""
                                ).includes(
                                    "pracodawcy.pracuj.pl"
                                )
                        );
                    const companyLogoImg = card.querySelector("img[data-test='image-company-logo'], picture img");
                    const companyName = companyLink ? (companyLink.innerText || "").trim() : (companyLogoImg ? (companyLogoImg.getAttribute("alt") || "").trim() : "");

                    /*
                    * Nagłówki znajdujące się
                    * wewnątrz karty.
                    */

                    const headings =
                        Array.from(
                            card.querySelectorAll(
                                "h1, h2, h3, h4"
                            )
                        )
                        .map(
                            (element) =>
                                (
                                    element.innerText
                                    || ""
                                ).trim()
                        )
                        .filter(Boolean);

                    return {

                        href:
                            href,

                        title:
                            (
                                link.innerText
                                || ""
                            ).trim(),

                        company:
                            companyName,

                        headings:
                            headings,

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
            "Brak ofert na stronie."
        )

        return [], False

    # -----------------------------------------------------
    # DEDUPLIKACJA
    # -----------------------------------------------------

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
                f"przetwarzania oferty: "
                f"{error}"
            )

            continue

        if not job:
            continue

        source_id = job[
            "source_id"
        ]

        if source_id in seen:
            continue

        seen.add(
            source_id
        )

        jobs.append(
            job
        )

    print(
        "Unikalnych ofert na stronie: "
        f"{len(jobs)}"
    )

    # -----------------------------------------------------
    # PODGLĄD PIERWSZEJ OFERTY
    # -----------------------------------------------------

    if jobs:

        first = jobs[0]

        print(
            "\n--- PODGLĄD PIERWSZEJ OFERTY ---"
        )

        print(
            f"Tytuł: "
            f"{first.get('title')}"
        )

        print(
            f"Firma: "
            f"{first.get('company')}"
        )

        print(
            f"Lokalizacja: "
            f"{first.get('location')}"
        )

        print(
            f"Tryb: "
            f"{first.get('work_mode')}"
        )

        print(
            f"Typ: "
            f"{first.get('work_type')}"
        )

        print(
            f"Poziom: "
            f"{first.get('experience_level')}"
        )

        print(
            f"Umowa: "
            f"{first.get('contract_type')}"
        )

        print(
            f"Wynagrodzenie: "
            f"{first.get('salary')}"
        )

        print(
            f"Opublikowano: "
            f"{first.get('published_at')}"
        )

        print(
            "--- KONIEC PODGLĄDU ---"
        )

    return (
        jobs,
        True,
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
    Na obecnym etapie pobierana jest tylko pierwsza
    strona danego wyszukiwania.
    """

    all_jobs = []

    seen_source_ids = set()

    try:

        (
            jobs,
            page_ok,
        ) = scrape_pracuj_page(
            page=page,
            keyword=keyword,
            page_number=1,
        )

    except PracujBlockedError:

        raise

    except Exception as error:

        print(
            "[ERROR] Pracuj.pl "
            f"dla '{keyword}': "
            f"{error}"
        )

        return (
            [],
            set(),
            False,
        )

    if not page_ok:

        return (
            [],
            set(),
            False,
        )

    # -----------------------------------------------------
    # ZAPIS ZNALEZIONYCH OFERT
    # -----------------------------------------------------

    for job in jobs:

        source_id = job[
            "source_id"
        ]

        if source_id in seen_source_ids:
            continue

        seen_source_ids.add(
            source_id
        )

        all_jobs.append(
            job
        )

    print(
        "\nPracuj.pl → "
        f"{keyword}: łącznie "
        f"{len(all_jobs)} "
        "unikalnych ofert"
    )

    print(
        "Pracuj.pl → "
        "pobrano tylko stronę 1."
    )

    return (
        all_jobs,
        seen_source_ids,
        True,
    )


# =========================================================
# SZCZEGÓŁY OFERTY
# =========================================================

def scrape_pracuj_details(
    page,
    job,
):
    """
    Pobiera szczegóły pojedynczej oferty.

    Funkcja pozostaje dostępna, ale jest wyłączona
    przez RUN_PRACUJ_DETAILS = False.
    """

    url = job["url"]

    print(
        f"[SZCZEGÓŁY PRACUJ] "
        f"{job['title']}"
    )

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

        block_reason = detect_pracuj_block(
            None,
            page,
        )

        if block_reason:

            raise PracujBlockedError(
                block_reason
            )

        return None

    block_reason = detect_pracuj_block(
        response,
        page,
    )

    if block_reason:

        raise PracujBlockedError(
            block_reason
        )

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
    # PODSTAWOWE DANE
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

    company = job.get(
        "company"
    )

    published_at = (
        parse_published_date(
            body_text
        )
        or job.get("published_at")
    )

    location = (
        find_location(lines)
        or job.get("location")
    )

    work_mode = (
        find_work_mode(lines)
        or job.get("work_mode")
    )

    work_type = (
        find_work_type(lines)
        or job.get("work_type")
    )

    experience_level = (
        find_experience_level(lines)
        or job.get("experience_level")
    )

    contract_type = (
        find_contract_type(lines)
        or job.get("contract_type")
    )

    salary = (
        find_salary(lines)
        or job.get("salary")
    )

    # -----------------------------------------------------
    # SEKCJE
    # -----------------------------------------------------

    job_description = extract_section(
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
            "oferujemy",
            "benefity",
            "benefits",
            "o firmie",
            "about the company",
        ],
    )

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

    about_company = extract_section(
        lines,
        [
            "o firmie",
            "about the company",
        ],
        [
            "benefity",
            "benefits",
            "aplikuj",
        ],
    )

    office_location = None

    for line in lines:

        normalized = line.lower()

        if normalized.startswith(
            "miejsce pracy:"
        ):

            office_location = line[
                len("miejsce pracy:"):
            ].strip()

            break

    expires_text = None
    expires_at = None

    for line in lines:

        normalized = line.lower()

        if (
            "oferta wygasa" in normalized
            or "ważna do" in normalized
            or "ważne do" in normalized
        ):

            expires_text = line

            match = re.search(
                r"(\d{1,2})[.\-/]"
                r"(\d{1,2})[.\-/]"
                r"(\d{4})",
                line,
            )

            if match:

                try:

                    expires_at = datetime(
                        int(match.group(3)),
                        int(match.group(2)),
                        int(match.group(1)),
                    )

                except ValueError:
                    pass

            break

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
        "tech_stack": requirements,
        "office_location": office_location,
        "about_company": about_company,
        "expires_text": expires_text,
        "expires_at": expires_at,
    }


# =========================================================
# SEKCJE
# =========================================================

def extract_section(
    lines,
    start_patterns,
    end_patterns,
):
    """
    Wyciąga tekst pomiędzy sekcjami.
    """

    start_index = None

    for index, line in enumerate(lines):

        normalized = (
            line
            .lower()
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