import re
from datetime import datetime
from urllib.parse import quote, urljoin

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from config import NOFLUFFJOBS_BASE_URL

from utils import (
    clean_text,
    generate_source_id,
)


# =========================================================
# BLOKADA
# =========================================================

class NoFluffJobsBlockedError(Exception):
    """
    Oznacza wykrycie blokady / rate limitu
    na No Fluff Jobs.
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


def detect_nofluffjobs_block(
    response,
    page,
):
    """
    Wykrywa typową blokadę.

    Samo słowo captcha nie jest traktowane
    jako blokada.
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

        body_text = (
            body_text
            .lower()
        )

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

def clean_lines(
    text,
):
    """
    Czyści tekst i zachowuje podział na linie.
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
# ELEMENTY UI
# =========================================================

UI_TEXTS = {
    "new",
    "nowa",
    "save",
    "zapisz ofertę",
    "zapisz oferte",
    "apply",
    "aplikuj",
    "check salary",
    "sprawdź wynagrodzenie",
    "sprawdz wynagrodzenie",
}


def is_ui_line(
    line,
):
    """
    Sprawdza, czy linia jest elementem interfejsu.
    """

    normalized = (
        line
        .strip()
        .lower()
    )

    return normalized in UI_TEXTS


# =========================================================
# WYNAGRODZENIE
# =========================================================

def salary_matches(
    text,
):
    """
    Sprawdza, czy tekst wygląda jak wynagrodzenie.
    """

    pattern = re.compile(
        r"""
        \d[\d\s.,]*
        \s*
        (?:[–-]\s*\d[\d\s.,]*)?
        \s*
        (?:PLN|EUR|USD|GBP|CHF)
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    return bool(
        pattern.search(
            text
        )
    )


def find_salary(
    lines,
):
    """
    Rozpoznaje wynagrodzenie.
    """

    range_pattern = re.compile(
        r"""
        \d[\d\s.,]*
        \s*[–-]\s*
        \d[\d\s.,]*
        \s*
        (?:PLN|EUR|USD|GBP|CHF)
        .*?
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    single_pattern = re.compile(
        r"""
        \d[\d\s.,]*
        \s*
        (?:PLN|EUR|USD|GBP|CHF)
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

    for line in lines:

        normalized = (
            line
            .strip()
            .lower()
        )

        if (
            "check salary"
            in normalized
            or "sprawdź wynagrodzenie"
            in normalized
            or "sprawdz wynagrodzenie"
            in normalized
        ):

            return line

    return None


# =========================================================
# LOKALIZACJA
# =========================================================

CITY_NAMES = {
    "warszawa",
    "kraków",
    "wrocław",
    "poznań",
    "gdańsk",
    "katowice",
    "łódź",
    "lublin",
    "białystok",
    "rzeszów",
    "bydgoszcz",
    "szczecin",
    "krakow",
    "wroclaw",
    "poznan",
    "gdansk",
    "lodz",
}


def is_location_line(
    line,
):
    """
    Rozpoznaje pojedynczą lokalizację.
    """

    normalized = (
        line
        .strip()
        .lower()
    )

    if normalized in {
        "remote",
        "zdalnie",
    }:

        return True

    if re.fullmatch(
        r"(remote|zdalnie)\s*\+\d+",
        normalized,
    ):

        return True

    if normalized in CITY_NAMES:

        return True

    if re.fullmatch(
        r"(?:"
        r"warszawa|"
        r"kraków|"
        r"wrocław|"
        r"poznań|"
        r"gdańsk|"
        r"katowice|"
        r"łódź|"
        r"lublin|"
        r"białystok|"
        r"rzeszów|"
        r"bydgoszcz|"
        r"szczecin|"
        r"krakow|"
        r"wroclaw|"
        r"poznan|"
        r"gdansk|"
        r"lodz"
        r")"
        r"(?:\s*\+\d+)?",
        normalized,
    ):

        return True

    return False


def find_location(
    lines,
):
    """
    Pobiera lokalizację.

    Jeżeli karta zawiera kilka lokalizacji,
    zwracamy pierwszą właściwą lokalizację,
    a nie technologie występujące wcześniej.
    """

    for line in lines:

        value = clean_text(
            line
        )

        if not value:

            continue

        if is_location_line(
            value
        ):

            return value

    # Fallback dla tekstu typu:
    #
    # Kraków, Zdalnie +1
    # Warszawa, Remote
    #
    for line in lines:

        normalized = (
            line
            .strip()
            .lower()
        )

        if (
            "remote"
            in normalized
            and any(
                city
                in normalized
                for city in CITY_NAMES
            )
        ):

            return line.strip()

        if (
            "zdalnie"
            in normalized
            and any(
                city
                in normalized
                for city in CITY_NAMES
            )
        ):

            return line.strip()

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

    for line in lines:

        normalized = (
            line
            .strip()
            .lower()
        )

        if (
            normalized == "remote"
            or normalized == "zdalnie"
            or re.fullmatch(
                r"(remote|zdalnie)\s*\+\d+",
                normalized,
            )
        ):

            return "Remote"

        if (
            "hybrid"
            in normalized
            or "hybryd"
            in normalized
        ):

            return "Hybrid"

        if (
            "office"
            in normalized
            or "stacjonarn"
            in normalized
        ):

            return "Office"

    return None


# =========================================================
# POZIOM
# =========================================================

def find_experience_level(
    title,
):
    """
    Rozpoznaje poziom wyłącznie na podstawie tytułu.
    """

    if not title:

        return None

    normalized = (
        title
        .lower()
    )

    found = []

    if re.search(
        r"\bjunior\b",
        normalized,
    ):

        found.append(
            "Junior"
        )

    if re.search(
        r"\bmid\b",
        normalized,
    ):

        found.append(
            "Mid"
        )

    if re.search(
        r"\bregular\b",
        normalized,
    ):

        found.append(
            "Regular"
        )

    if re.search(
        r"\bsenior\b",
        normalized,
    ):

        found.append(
            "Senior"
        )

    if re.search(
        r"\bexpert\b",
        normalized,
    ):

        found.append(
            "Expert"
        )

    if re.search(
        r"\btech lead\b",
        normalized,
    ):

        found.append(
            "Tech Lead"
        )

    elif re.search(
        r"\blead\b",
        normalized,
    ):

        found.append(
            "Lead"
        )

    if not found:

        return None

    return ", ".join(
        dict.fromkeys(
            found
        )
    )


# =========================================================
# UMOWA
# =========================================================

def find_contract_type(
    lines,
):
    """
    Rozpoznaje rodzaj umowy.
    """

    found = []

    patterns = [
        (
            r"\bb2b\b",
            "B2B",
        ),
        (
            r"umowa o pracę",
            "Umowa o pracę",
        ),
        (
            r"umowa zlecenie",
            "Umowa zlecenie",
        ),
        (
            r"umowa o dzieło",
            "Umowa o dzieło",
        ),
    ]

    for line in lines:

        normalized = (
            line
            .lower()
        )

        for pattern, value in patterns:

            if re.search(
                pattern,
                normalized,
            ):

                found.append(
                    value
                )

    if not found:

        return None

    return ", ".join(
        dict.fromkeys(
            found
        )
    )


# =========================================================
# TECHNOLOGIE / KATEGORIE
# =========================================================

TECHNOLOGY_WORDS = {
    "aws",
    "azure",
    "gcp",
    "docker",
    "kubernetes",
    "terraform",
    "ansible",
    "jenkins",
    "gitlab",
    "github",
    "python",
    "java",
    "javascript",
    "typescript",
    "node.js",
    "go",
    "c#",
    ".net",
    "linux",
    "sql",
    "postgresql",
    "mysql",
    "oracle",
    "grafana",
    "prometheus",
    "helm",
    "argocd",
    "git",
    "ci/cd",
    "devops",
    "azure devops",
    "aws lambda",
    "cloudformation",
    "bash",
    "powershell",
    "kotlin",
    "ruby",
    "php",
    "react",
    "angular",
    "vue",
    "spring",
    "django",
    "flask",
    "fastapi",
    "redis",
    "mongodb",
    "elasticsearch",
    "kafka",
    "rabbitmq",
    "openstack",
    "cloud",
    "backend",
    "frontend",
    "data",
    "ai/ml",
    "security",
    "testing",
    "fullstack",
    "mobile",
    "erp",
}


def is_technology_or_category(
    line,
):
    """
    Sprawdza, czy linia jest technologią
    albo kategorią z karty.
    """

    normalized = (
        line
        .strip()
        .lower()
    )

    if normalized in TECHNOLOGY_WORDS:
        return True

    return False


# Alias bez ryzyka literówki w dalszym kodzie.
TECHNOLOGY_WORDS = TECHNOLOGY_WORDS


# =========================================================
# TYTUŁ
# =========================================================

def normalize_title(
    title,
):
    """
    Usuwa elementy interfejsu doklejone do tytułu.

    Przykład:

        Cloud DevOps Engineer NOWA

    ->

        Cloud DevOps Engineer
    """

    if not title:

        return None

    value = clean_text(
        title
    )

    if not value:

        return None

    # -----------------------------------------------------
    # UI
    # -----------------------------------------------------

    ui_patterns = [
        r"\s+NOWA$",
        r"\s+NEW$",
        r"\s+Zapisz ofertę$",
        r"\s+Save$",
        r"\s+Sprawdź wynagrodzenie$",
        r"\s+Check Salary$",
        r"\s+Aplikuj$",
        r"\s+Apply$",
    ]

    changed = True

    while changed:

        changed = False

        for pattern in ui_patterns:

            new_value = re.sub(
                pattern,
                "",
                value,
                flags=re.IGNORECASE,
            ).strip()

            if new_value != value:

                value = new_value

                changed = True

    return value or None


def find_title(
    item,
):
    """
    Pobiera właściwy tytuł oferty.

    Priorytet:
        1. nagłówki wewnątrz linku
        2. aria-label
        3. title HTML
        4. pierwsza sensowna linia
    """

    headings = (
        item.get("headings")
        or []
    )

    for heading in headings:

        value = normalize_title(
            heading
        )

        if not value:

            continue

        if len(value) > 250:

            continue

        if is_ui_line(
            value
        ):

            continue

        return value

    aria_label = normalize_title(
        item.get("ariaLabel")
    )

    if (
        aria_label
        and len(aria_label) <= 250
    ):

        return aria_label

    link_title = normalize_title(
        item.get("linkTitle")
    )

    if (
        link_title
        and len(link_title) <= 250
    ):

        return link_title

    card_text = (
        item.get("cardText")
        or ""
    )

    lines = clean_lines(
        card_text
    )

    for line in lines:

        value = normalize_title(
            line
        )

        if not value:

            continue

        if is_ui_line(
            value
        ):

            continue

        if salary_matches(
            value
        ):

            continue

        if is_location_line(
            value
        ):

            continue

        if len(value) > 250:

            continue

        return value

    return None


# =========================================================
# FIRMA
# =========================================================

def find_company(
    item,
    title,
    lines,
):
    """
    Znajduje firmę.

    Na No Fluff Jobs karta ma zwykle układ:

        TYTUŁ
        NOWA
        ZAPISZ OFERTĘ
        WYNAGRODZENIE
        TECHNOLOGIA
        TECHNOLOGIA
        ...
        FIRMA
        LOKALIZACJA

    Dlatego szukamy firmy BEZPOŚREDNIO PRZED
    lokalizacją, pomijając technologie/kategorie.
    """

    # -----------------------------------------------------
    # 1. Bezpośrednia firma z DOM
    # -----------------------------------------------------

    direct_company = clean_text(
        item.get("company")
    )

    if direct_company:

        return direct_company

    # -----------------------------------------------------
    # 2. Znajdź ostatnią lokalizację
    # -----------------------------------------------------

    location_index = None

    for index, line in enumerate(
        lines
    ):

        if is_location_line(
            line
        ):

            location_index = index

    # -----------------------------------------------------
    # 3. Szukaj wstecz od lokalizacji
    # -----------------------------------------------------

    if location_index is not None:

        for index in range(
            location_index - 1,
            max(
                -1,
                location_index - 10,
            ),
            -1,
        ):

            candidate = clean_text(
                lines[index]
            )

            if not candidate:

                continue

            normalized = (
                candidate
                .lower()
            )

            # UI
            if is_ui_line(
                candidate
            ):

                continue

            # Wynagrodzenie
            if salary_matches(
                candidate
            ):

                continue

            # Tytuł
            if (
                title
                and normalized
                == title.lower()
            ):

                continue

            # Lokalizacja
            if is_location_line(
                candidate
            ):

                continue

            # Technologie/kategorie
            if (
                normalized
                in TECHNOLOGY_WORDS
            ):

                continue

            # Długi tekst raczej nie jest nazwą firmy.
            if len(candidate) > 150:

                continue

            return candidate

    # -----------------------------------------------------
    # 4. Awaryjny fallback
    # -----------------------------------------------------

    # Jeżeli lokalizacji nie udało się wykryć,
    # próbujemy znaleźć sensowną linię po tytule.

    title_index = None

    if title:

        for index, line in enumerate(
            lines
        ):

            if (
                clean_text(line).lower()
                == title.lower()
            ):

                title_index = index

                break

    if title_index is not None:

        for candidate in lines[
            title_index + 1:
            title_index + 10
        ]:

            candidate = clean_text(
                candidate
            )

            if not candidate:

                continue

            if is_ui_line(
                candidate
            ):

                continue

            if salary_matches(
                candidate
            ):

                continue

            if is_location_line(
                candidate
            ):

                continue

            if (
                candidate.lower()
                in TECHNOLOGY_WORDS
            ):

                continue

            if len(candidate) > 150:

                continue

            return candidate

    return None


# =========================================================
# KARTA OFERTY
# =========================================================

def extract_job_from_raw_item(
    item,
    keyword,
):
    """
    Parsuje jedną ofertę.

    Dane pochodzą z konkretnego linku
    /job/..., bez parentElement.
    """

    href = (
        item.get("href")
        or ""
    ).strip()

    if not href:

        return None

    if (
        "/job/"
        not in href
        and "/job1/"
        not in href
    ):

        return None

    url = urljoin(
        NOFLUFFJOBS_BASE_URL,
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

    # -----------------------------------------------------
    # TYTUŁ
    # -----------------------------------------------------

    title = find_title(
        item
    )

    if not title:

        return None

    # -----------------------------------------------------
    # WYNAGRODZENIE
    # -----------------------------------------------------

    salary = find_salary(
        lines
    )

    # -----------------------------------------------------
    # LOKALIZACJA
    # -----------------------------------------------------

    location = find_location(
        lines
    )

    # -----------------------------------------------------
    # TRYB
    # -----------------------------------------------------

    work_mode = find_work_mode(
        lines
    )

    # -----------------------------------------------------
    # POZIOM
    # -----------------------------------------------------

    experience_level = (
        find_experience_level(
            title
        )
    )

    # -----------------------------------------------------
    # UMOWA
    # -----------------------------------------------------

    contract_type = (
        find_contract_type(
            lines
        )
    )

    # -----------------------------------------------------
    # FIRMA
    # -----------------------------------------------------

    company = find_company(
        item,
        title,
        lines,
    )

    # -----------------------------------------------------
    # DATA
    # -----------------------------------------------------

    published_at = None

    return {
        "portal": "nofluffjobs",
        "source_id": source_id,
        "title": title,
        "company": company,
        "location": location,
        "work_mode": work_mode,
        "work_type": None,
        "experience_level": experience_level,
        "contract_type": contract_type,
        "salary": salary,
        "url": url,
        "keyword": keyword,
        "published_at": published_at,
    }


# =========================================================
# URL WYSZUKIWANIA
# =========================================================

def build_nofluffjobs_url(
    keyword,
):
    """
    Buduje URL wyszukiwania.
    """

    encoded_keyword = quote(
        keyword.strip(),
        safe="",
    )

    return (
        f"{NOFLUFFJOBS_BASE_URL}/pl"
        f"?criteria={encoded_keyword}"
    )


# =========================================================
# STRONA WYNIKÓW
# =========================================================

def scrape_nofluffjobs_page(
    page,
    keyword,
):
    """
    Pobiera wyniki dla jednego keywordu.
    """

    url = build_nofluffjobs_url(
        keyword
    )

    print(
        f"\nNo Fluff Jobs → {keyword}"
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
            7000
        )

    except PlaywrightTimeoutError:

        print(
            "[WARN] Timeout podczas "
            f"ładowania: {url}"
        )

        block_reason = (
            detect_nofluffjobs_block(
                None,
                page,
            )
        )

        if block_reason:

            raise NoFluffJobsBlockedError(
                block_reason
            )

        return [], False

    # -----------------------------------------------------
    # BLOKADA
    # -----------------------------------------------------

    block_reason = (
        detect_nofluffjobs_block(
            response,
            page,
        )
    )

    if block_reason:

        print(
            "\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
            "!!! BLOKADA NO FLUFF JOBS !!!\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        print(
            f"Powód: {block_reason}"
        )

        raise NoFluffJobsBlockedError(
            block_reason
        )

    print(
        f"Załadowany URL: {page.url}"
    )

    # -----------------------------------------------------
    # LINKI DO OFERT
    # -----------------------------------------------------

    try:

        page.wait_for_function(
            """
            () => document.querySelectorAll(
                "a[href*='/job/'], a[href*='/job1/']"
            ).length > 0
            """,
            timeout=30000,
        )

    except PlaywrightTimeoutError:

        block_reason = (
            detect_nofluffjobs_block(
                response,
                page,
            )
        )

        if block_reason:

            raise NoFluffJobsBlockedError(
                block_reason
            )

        print(
            "Nie znaleziono linków "
            "do ofert."
        )

        return [], False

    # -----------------------------------------------------
    # POBRANIE LINKÓW
    # -----------------------------------------------------

    raw_jobs = page.evaluate(
        """
        () => {

            const links = Array.from(
                document.querySelectorAll(
                    "a[href*='/job/'], a[href*='/job1/']"
                )
            );

            return links
                .map(
                    (link) => {

                        const href =
                            link.getAttribute(
                                "href"
                            );

                        if (!href) {

                            return null;
                        }

                        /*
                         * WAŻNE:
                         * nie pobieramy parentElement.
                         *
                         * Sam <a> jest jednostką oferty.
                         */

                        const headings =
                            Array.from(
                                link.querySelectorAll(
                                    "h1, h2, h3, h4, [role='heading']"
                                )
                            )
                            .map(
                                (element) => (
                                    element.innerText
                                    || ""
                                ).trim()
                            )
                            .filter(Boolean);

                        return {

                            href:
                                href,

                            linkText:
                                (
                                    link.innerText
                                    || ""
                                ).trim(),

                            ariaLabel:
                                link.getAttribute(
                                    "aria-label"
                                ) || "",

                            linkTitle:
                                link.getAttribute(
                                    "title"
                                ) || "",

                            headings:
                                headings,

                            /*
                             * Firma może być dostępna
                             * jako tekst wewnątrz linku.
                             */

                            cardText:
                                (
                                    link.innerText
                                    || ""
                                ).trim()
                        };
                    }
                )
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
    # NORMALIZACJA
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
        "Unikalnych ofert: "
        f"{len(jobs)}"
    )

    # -----------------------------------------------------
    # PODGLĄD
    # -----------------------------------------------------

    if jobs:

        first = jobs[0]

        print(
            "\n--- PODGLĄD NO FLUFF JOBS ---"
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
            f"URL: "
            f"{first.get('url')}"
        )

        print(
            "--- KONIEC PODGLĄDU ---"
        )

    return (
        jobs,
        True,
    )


# =========================================================
# GŁÓWNA FUNKCJA LISTY
# =========================================================

def scrape_nofluffjobs(
    page,
    keyword,
    min_delay=None,
    max_delay=None,
):
    """
    Pobiera jedną stronę wyników.
    """

    try:

        (
            jobs,
            page_ok,
        ) = scrape_nofluffjobs_page(
            page=page,
            keyword=keyword,
        )

    except NoFluffJobsBlockedError:

        raise

    except Exception as error:

        print(
            "[ERROR] No Fluff Jobs "
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

    seen_source_ids = {
        job["source_id"]
        for job in jobs
    }

    print(
        "\nNo Fluff Jobs → "
        f"{keyword}: łącznie "
        f"{len(jobs)} unikalnych ofert"
    )

    return (
        jobs,
        seen_source_ids,
        True,
    )


# =========================================================
# SEKCJE SZCZEGÓŁÓW
# =========================================================

def extract_nofluff_section(
    lines,
    start_patterns,
    end_patterns,
):
    """
    Wyciąga tekst pomiędzy sekcjami.
    """

    start_index = None

    for index, line in enumerate(
        lines
    ):

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


# =========================================================
# TECHNOLOGIE
# =========================================================

def extract_nofluff_technologies(
    lines,
):
    """
    Rozpoznaje technologie.
    """

    technologies = []

    known_technologies = sorted(
        TECHNOLOGY_WORDS,
        key=len,
        reverse=True,
    )

    for line in lines:

        normalized = (
            line
            .lower()
        )

        for technology in known_technologies:

            if (
                technology
                in normalized
            ):

                technologies.append(
                    technology
                )

    if not technologies:

        return None

    # Zachowaj przyjazną pisownię.
    display_names = {
        "aws": "AWS",
        "azure": "Azure",
        "gcp": "GCP",
        "docker": "Docker",
        "kubernetes": "Kubernetes",
        "terraform": "Terraform",
        "ansible": "Ansible",
        "jenkins": "Jenkins",
        "gitlab": "GitLab",
        "github": "GitHub",
        "python": "Python",
        "java": "Java",
        "javascript": "JavaScript",
        "typescript": "TypeScript",
        "node.js": "Node.js",
        "go": "Go",
        "c#": "C#",
        ".net": ".NET",
        "linux": "Linux",
        "sql": "SQL",
        "postgresql": "PostgreSQL",
        "mysql": "MySQL",
        "oracle": "Oracle",
        "grafana": "Grafana",
        "prometheus": "Prometheus",
        "helm": "Helm",
        "argocd": "ArgoCD",
        "git": "Git",
        "ci/cd": "CI/CD",
        "devops": "DevOps",
        "azure devops": "Azure DevOps",
        "aws lambda": "AWS Lambda",
        "cloudformation": "CloudFormation",
        "bash": "Bash",
        "powershell": "PowerShell",
        "kotlin": "Kotlin",
        "ruby": "Ruby",
        "php": "PHP",
        "react": "React",
        "angular": "Angular",
        "vue": "Vue",
        "spring": "Spring",
        "django": "Django",
        "flask": "Flask",
        "fastapi": "FastAPI",
        "redis": "Redis",
        "mongodb": "MongoDB",
        "elasticsearch": "Elasticsearch",
        "kafka": "Kafka",
        "rabbitmq": "RabbitMQ",
        "openstack": "OpenStack",
        "cloud": "Cloud",
        "backend": "Backend",
        "frontend": "Frontend",
        "data": "Data",
        "ai/ml": "AI/ML",
        "security": "Security",
        "testing": "Testing",
        "fullstack": "Fullstack",
        "mobile": "Mobile",
        "erp": "ERP",
    }

    result = []

    for technology in technologies:

        value = display_names.get(
            technology,
            technology,
        )

        if value not in result:

            result.append(
                value
            )

    return ", ".join(
        result
    )


# =========================================================
# SZCZEGÓŁY OFERTY
# =========================================================

def scrape_nofluffjobs_details(
    page,
    job,
):
    """
    Pobiera szczegóły pojedynczej oferty.
    """

    url = job["url"]

    print(
        f"[SZCZEGÓŁY NO FLUFF JOBS] "
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

        block_reason = (
            detect_nofluffjobs_block(
                None,
                page,
            )
        )

        if block_reason:

            raise NoFluffJobsBlockedError(
                block_reason
            )

        return None

    block_reason = (
        detect_nofluffjobs_block(
            response,
            page,
        )
    )

    if block_reason:

        raise NoFluffJobsBlockedError(
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
    # TYTUŁ
    # -----------------------------------------------------

    title = job.get(
        "title"
    )

    try:

        locator = page.locator(
            "h1"
        ).first

        if locator.count() > 0:

            value = clean_text(
                locator.inner_text(
                    timeout=5000
                )
            )

            if value:

                title = normalize_title(
                    value
                )

    except Exception:

        pass

    # -----------------------------------------------------
    # FIRMA
    # -----------------------------------------------------

    company = job.get(
        "company"
    )

    try:

        selectors = [
            "a[href*='/company/']",
            "[class*='company-name']",
            "[class*='companyName']",
        ]

        for selector in selectors:

            locator = page.locator(
                selector
            )

            count = locator.count()

            if count == 0:

                continue

            for index in range(
                min(
                    count,
                    5,
                )
            ):

                try:

                    value = clean_text(
                        locator.nth(
                            index
                        ).inner_text(
                            timeout=2000
                        )
                    )

                except Exception:

                    continue

                if not value:

                    continue

                if (
                    title
                    and value.lower()
                    == title.lower()
                ):

                    continue

                company = value

                break

            if company:

                break

    except Exception:

        pass

    # -----------------------------------------------------
    # LOKALIZACJA
    # -----------------------------------------------------

    location = (
        find_location(
            lines
        )
        or job.get(
            "location"
        )
    )

    # -----------------------------------------------------
    # TRYB
    # -----------------------------------------------------

    work_mode = (
        find_work_mode(
            lines
        )
        or job.get(
            "work_mode"
        )
    )

    # -----------------------------------------------------
    # POZIOM
    # -----------------------------------------------------

    experience_level = (
        find_experience_level(
            title
        )
        or job.get(
            "experience_level"
        )
    )

    # -----------------------------------------------------
    # UMOWA
    # -----------------------------------------------------

    contract_type = (
        find_contract_type(
            lines
        )
        or job.get(
            "contract_type"
        )
    )

    # -----------------------------------------------------
    # WYNAGRODZENIE
    # -----------------------------------------------------

    salary = (
        find_salary(
            lines
        )
        or job.get(
            "salary"
        )
    )

    # -----------------------------------------------------
    # DATA PUBLIKACJI
    # -----------------------------------------------------

    published_at = job.get(
        "published_at"
    )

    # -----------------------------------------------------
    # OPIS
    # -----------------------------------------------------

    job_description = (
        extract_nofluff_section(
            lines,
            [
                "opis stanowiska",
                "job description",
                "description",
                "zakres obowiązków",
                "responsibilities",
            ],
            [
                "obowiązkowe",
                "must have",
                "wymagania",
                "requirements",
                "mile widziane",
                "nice to have",
                "benefity",
                "benefits",
                "o firmie",
                "about the company",
            ],
        )
    )

    # -----------------------------------------------------
    # WYMAGANIA
    # -----------------------------------------------------

    requirements = (
        extract_nofluff_section(
            lines,
            [
                "obowiązkowe",
                "must have",
                "wymagania",
                "requirements",
            ],
            [
                "mile widziane",
                "nice to have",
                "benefity",
                "benefits",
                "o firmie",
                "about the company",
            ],
        )
    )

    # -----------------------------------------------------
    # O FIRMIE
    # -----------------------------------------------------

    about_company = (
        extract_nofluff_section(
            lines,
            [
                "o firmie",
                "about the company",
                "about us",
            ],
            [
                "benefity",
                "benefits",
                "aplikuj",
                "apply",
                "podobne oferty",
                "similar jobs",
            ],
        )
    )

    # -----------------------------------------------------
    # TECHNOLOGIE
    # -----------------------------------------------------

    tech_stack = (
        extract_nofluff_technologies(
            lines
        )
    )

    if not tech_stack:

        tech_stack = requirements

    # -----------------------------------------------------
    # WYGASANIE
    # -----------------------------------------------------

    expires_text = None
    expires_at = None

    expiry_patterns = [
        re.compile(
            r"""
            oferta\s+ważna\s+do:
            \s*
            (\d{1,2})
            [.]
            (\d{1,2})
            [.]
            (\d{4})
            """,
            re.IGNORECASE | re.VERBOSE,
        ),
        re.compile(
            r"""
            valid\s+until:
            \s*
            (\d{1,2})
            [.]
            (\d{1,2})
            [.]
            (\d{4})
            """,
            re.IGNORECASE | re.VERBOSE,
        ),
    ]

    for pattern in expiry_patterns:

        match = pattern.search(
            body_text
        )

        if not match:

            continue

        try:

            expires_at = datetime(
                int(
                    match.group(3)
                ),
                int(
                    match.group(2)
                ),
                int(
                    match.group(1)
                ),
            )

            expires_text = match.group(
                0
            )

            break

        except ValueError:

            pass

    # -----------------------------------------------------
    # WYNIK
    # -----------------------------------------------------

    return {
        "title": title,
        "company": company,
        "location": location,
        "work_mode": work_mode,
        "work_type": None,
        "experience_level": (
            experience_level
        ),
        "contract_type": (
            contract_type
        ),
        "salary": salary,
        "published_at": published_at,
        "job_description": (
            job_description
        ),
        "tech_stack": (
            tech_stack
        ),
        "office_location": (
            location
        ),
        "about_company": (
            about_company
        ),
        "expires_text": (
            expires_text
        ),
        "expires_at": (
            expires_at
        ),
    }