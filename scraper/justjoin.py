import re
from datetime import datetime
from urllib.parse import quote, urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from config import JUSTJOIN_BASE_URL
from utils import clean_text, generate_source_id


# =========================================================
# BLOKADY / RATE LIMIT
# =========================================================

class PortalBlockedError(Exception):
    """
    Oznacza wykrycie blokady lub rate limitu portalu.
    """


BLOCK_STATUS_CODES = {
    403,
    429,
    503,
}


# Nie dodajemy tutaj samego "captcha".
# Samo słowo captcha może występować
# w normalnej treści oferty.
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


def detect_portal_block(
    response,
    page,
):
    """
    Wykrywa rzeczywistą blokadę/rate limit.

    Zwraca:
        None - brak blokady
        str  - powód blokady
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
    # WIDOCZNY TEKST STRONY
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
# LOKALIZACJA
# =========================================================

def clean_location(lines):
    """
    Wyciąga lokalizację z karty wyników.
    """

    # -----------------------------------------------------
    # Warszawa
    # , +4
    # Locations
    # -----------------------------------------------------

    for index in range(
        len(lines)
    ):

        if index + 1 >= len(lines):
            break

        current = lines[index]
        next_line = lines[index + 1]

        if not current:
            continue

        if next_line.startswith(","):

            location = (
                f"{current}{next_line}"
            )

            if (
                index + 2 < len(lines)
                and lines[index + 2].lower()
                in {
                    "location",
                    "locations",
                }
            ):

                location += (
                    f" {lines[index + 2]}"
                )

            return location

    # -----------------------------------------------------
    # Warszawa
    # Locations
    # -----------------------------------------------------

    for index in range(
        len(lines) - 1
    ):

        if (
            lines[index + 1].lower()
            in {
                "location",
                "locations",
            }
        ):

            return lines[index]

    return None


# =========================================================
# WYNAGRODZENIE
# =========================================================

def clean_salary(lines):
    """
    Szuka zakresu wynagrodzenia
    lub Undisclosed Salary.
    """

    salary_pattern = re.compile(
        r"""
        \d[\d\s.,]*
        \s*-\s*
        \d[\d\s.,]*
        """,
        re.VERBOSE,
    )

    for index, line in enumerate(lines):

        if not line:
            continue

        if salary_pattern.search(line):

            salary = line

            if (
                index + 1 < len(lines)
            ):

                next_line = lines[
                    index + 1
                ]

                if re.search(
                    r"(usd|eur|pln|gbp|chf|"
                    r"month|/h|/month)",
                    next_line,
                    re.IGNORECASE,
                ):

                    salary = (
                        f"{salary} "
                        f"{next_line}"
                    )

            return salary

        if re.search(
            r"undisclosed\s+salary",
            line,
            re.IGNORECASE,
        ):

            return line

    return None


# =========================================================
# TRYB PRACY
# =========================================================

def find_work_mode(lines):

    for line in lines:

        normalized = (
            line
            .lower()
            .strip()
        )

        if normalized == "remote":
            return "Remote"

        if normalized == "hybrid":
            return "Hybrid"

        if normalized == "office":
            return "Office"

    return None


# =========================================================
# TYP PRACY
# =========================================================

def find_work_type(lines):

    values = {
        "full-time",
        "part-time",
        "practice / internship",
        "internship",
        "freelance",
        "b2b contract",
    }

    found = []

    for line in lines:

        if (
            line.lower().strip()
            in values
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
# POZIOM DOŚWIADCZENIA
# =========================================================

def find_experience_level(lines):

    values = {
        "intern",
        "junior",
        "mid",
        "senior",
        "team leader",
        "manager",
        "c-level",
    }

    found = []

    for line in lines:

        if (
            line.lower().strip()
            in values
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
# RODZAJ UMOWY
# =========================================================

def find_contract_type(lines):

    values = {
        "b2b",
        "permanent",
        "internship",
        "mandate",
        "mandate contract",
        "specific-task contract",
        "contract",
    }

    found = []

    for line in lines:

        if (
            line.lower().strip()
            in values
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
# TYTUŁ
# =========================================================

def find_title(
    headings,
    link_title,
    link_text,
    lines,
):
    """
    Znajduje tytuł oferty.
    """

    # H1-H4

    for heading in headings:

        heading = clean_text(
            heading
        )

        if heading:
            return heading

    # title="View offer ..."

    link_title = clean_text(
        link_title
    )

    if link_title:

        cleaned = re.sub(
            r"^\s*view\s+offer\s*",
            "",
            link_title,
            flags=re.IGNORECASE,
        )

        if cleaned:
            return cleaned

    # Tekst linku.

    link_text = clean_text(
        link_text
    )

    if link_text:
        return link_text

    # Awaryjnie karta.

    for line in lines:

        normalized = line.lower()

        if normalized in {
            "remote",
            "hybrid",
            "office",
            "locations",
            "location",
            "new",
            "super offer",
            "1-click apply",
            "full-time",
            "part-time",
            "senior",
            "mid",
            "junior",
            "intern",
        }:
            continue

        if re.search(
            r"\d+\s*d\s*left",
            normalized,
        ):
            continue

        if re.search(
            r"(chf|eur|usd|pln|gbp)",
            normalized,
        ):
            continue

        if len(line) > 5:
            return line

    return None


# =========================================================
# DATA PUBLIKACJI
# =========================================================

def find_published_date(lines):
    """
    Szuka daty publikacji.

    Przykłady:
        Published: 19.08.2026
        Published on: 19.08.2026
    """

    patterns = [
        re.compile(
            r"published\s*:\s*"
            r"(\d{2}\.\d{2}\.\d{4})",
            re.IGNORECASE,
        ),
        re.compile(
            r"published\s+on\s*:\s*"
            r"(\d{2}\.\d{2}\.\d{4})",
            re.IGNORECASE,
        ),
    ]

    for line in lines:

        for pattern in patterns:

            match = pattern.search(
                line
            )

            if not match:
                continue

            try:

                return datetime.strptime(
                    match.group(1),
                    "%d.%m.%Y",
                )

            except ValueError:

                continue

    # "Published:" oraz data mogą być
    # osobnymi liniami.

    for index, line in enumerate(
        lines
    ):

        if (
            line.lower().strip()
            in {
                "published",
                "published:",
                "published on",
                "published on:",
            }
        ):

            if (
                index + 1 < len(lines)
            ):

                match = re.fullmatch(
                    r"\d{2}\.\d{2}\.\d{4}",
                    lines[index + 1],
                )

                if match:

                    try:

                        return datetime.strptime(
                            lines[index + 1],
                            "%d.%m.%Y",
                        )

                    except ValueError:

                        pass

    return None


# =========================================================
# LOKALIZACJA ZE STRONY SZCZEGÓŁOWEJ
# =========================================================

def find_detail_location(
    lines,
    title,
):
    """
    Próbuje znaleźć właściwą lokalizację
    ze strony szczegółowej.
    """

    normalized_title = (
        title.lower().strip()
        if title
        else ""
    )

    title_indexes = []

    for index, line in enumerate(
        lines
    ):

        if (
            normalized_title
            and line.lower().strip()
            == normalized_title
        ):

            title_indexes.append(
                index
            )

    # Szukamy lokalizacji obok tytułu.

    for title_index in title_indexes:

        start = title_index + 1
        end = min(
            title_index + 8,
            len(lines),
        )

        nearby = lines[
            start:end
        ]

        for candidate in nearby:

            normalized = (
                candidate
                .lower()
                .strip()
            )

            if not candidate:
                continue

            if normalized in {
                "save",
                "apply",
                "summary of the offer",
                "remote",
                "hybrid",
                "office",
                "locations",
            }:
                continue

            # "-, Warszawa"
            candidate_clean = re.sub(
                r"^-\s*,\s*",
                "",
                candidate,
            ).strip()

            if candidate_clean != candidate:

                if candidate_clean:
                    return candidate_clean

            # Typowe lokalizacje.

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
                r"Lodz|"
                r"Zurich|"
                r"Zürich|"
                r"Geneva|"
                r"London|"
                r"Berlin|"
                r"Prague"
                r")\b",
                candidate,
                re.IGNORECASE,
            ):

                return candidate

    # Fallback: Office Location.

    for index, line in enumerate(
        lines
    ):

        if (
            line.lower().strip()
            == "office location"
        ):

            if (
                index + 1 < len(lines)
            ):

                candidate = lines[
                    index + 1
                ]

                if candidate:
                    return candidate

    return None


# =========================================================
# SEKCJE OFERTY
# =========================================================

def _extract_section(
    lines,
    start_titles,
    end_titles,
):
    """
    Wyciąga tekst pomiędzy nagłówkami sekcji.
    """

    start_index = None

    start_titles = {
        item.lower()
        for item in start_titles
    }

    end_titles = {
        item.lower()
        for item in end_titles
    }

    for index, line in enumerate(
        lines
    ):

        normalized = (
            line.lower().strip()
        )

        if normalized in start_titles:

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

        if normalized in end_titles:

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
# WYGAŚNIĘCIE OFERTY
# =========================================================

def parse_expiration(lines):
    """
    Zwraca:
        expires_text
        expires_at
    """

    for line in lines:

        normalized = line.lower()

        # Oferta wygasła.

        if (
            "offer expired"
            in normalized
        ):

            return (
                line,
                None,
            )

        # Data końcowa.

        date_match = re.search(
            r"(\d{2}\.\d{2}\.\d{4})",
            line,
        )

        if (
            date_match
            and re.search(
                r"(until|expires|expiration)",
                line,
                re.IGNORECASE,
            )
        ):

            try:

                expires_at = datetime.strptime(
                    date_match.group(1),
                    "%d.%m.%Y",
                )

                return (
                    line,
                    expires_at,
                )

            except ValueError:
                pass

        # 29d left.

        if re.search(
            r"\b\d+\s*day[s]?\s*left\b",
            normalized,
        ):

            return (
                line,
                None,
            )

        if (
            "expires today"
            in normalized
        ):

            return (
                line,
                None,
            )

        if (
            "expires tomorrow"
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
# URL
# =========================================================

def build_justjoin_url(
    keyword,
):
    """
    Buduje URL wyszukiwania Just Join IT.
    """

    normalized = keyword.strip()

    # Pojedyncze słowo.

    if " " not in normalized:

        slug = quote(
            normalized.lower()
        )

        return (
            f"{JUSTJOIN_BASE_URL}/"
            f"job-offers/all-locations/"
            f"{slug}"
        )

    # Fraza.

    encoded = quote(
        normalized
    )

    return (
        f"{JUSTJOIN_BASE_URL}/"
        f"job-offers/all-locations/devops"
        f"?q={encoded}%40keyword"
    )


# =========================================================
# PARSOWANIE OFERTY Z LISTY
# =========================================================

def extract_job_from_raw_item(
    item,
    keyword,
):
    """
    Zamienia rekord DOM na wspólny format oferty.
    """

    href = item.get(
        "href",
        "",
    ).strip()

    if not href:
        return None

    if "/job-offer/" not in href:
        return None

    url = urljoin(
        JUSTJOIN_BASE_URL,
        href,
    )

    source_id = generate_source_id(
        url
    )

    # -----------------------------------------------------
    # ZACHOWAJ LINIE
    # -----------------------------------------------------

    raw_card_text = item.get(
        "cardText",
        "",
    )

    lines = []

    for line in raw_card_text.splitlines():

        line = clean_text(
            line
        )

        if line:
            lines.append(
                line
            )

    if not lines:
        return None

    # -----------------------------------------------------
    # TYTUŁ
    # -----------------------------------------------------

    headings = (
        item.get("headings")
        or []
    )

    title = find_title(
        headings,
        item.get("linkTitle"),
        item.get("linkText"),
        lines,
    )

    if not title:
        return None

    # -----------------------------------------------------
    # FIRMA
    # -----------------------------------------------------

    company = None

    if lines:

        candidate = lines[0]

        if (
            candidate
            and candidate != title
        ):

            company = candidate

    # -----------------------------------------------------
    # DANE Z LISTY
    # -----------------------------------------------------

    location = clean_location(
        lines
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

    salary = clean_salary(
        lines
    )

    return {
        "portal": "justjoin",
        "source_id": source_id,
        "title": title,
        "company": company,
        "location": location,
        "work_mode": work_mode,
        "work_type": work_type,
        "salary": salary,
        "url": url,
        "keyword": keyword,
        "published_at": None,
    }


# =========================================================
# SCRAPOWANIE LISTY
# =========================================================

def scrape_justjoin_page(
    page,
    keyword,
):
    """
    Pobiera jedną stronę wyników Just Join IT.

    Zwraca:
        (jobs, True)  - poprawny skan
        ([], False)   - błąd/timeout
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

    # -----------------------------------------------------
    # OTWARCIE STRONY
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
            detect_portal_block(
                None,
                page,
            )
        )

        if block_reason:

            raise PortalBlockedError(
                block_reason
            )

        return [], False

    # -----------------------------------------------------
    # SPRAWDŹ BLOKADĘ
    # -----------------------------------------------------

    block_reason = detect_portal_block(
        response,
        page,
    )

    if block_reason:

        print(
            "\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
            "!!! BLOKADA JUST JOIN IT !!!\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        print(
            f"Powód: {block_reason}"
        )

        print(
            "Scrapowanie Just Join IT "
            "zostało zatrzymane."
        )

        raise PortalBlockedError(
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
            "a[href*='/job-offer/']"
        ).first.wait_for(
            timeout=30000
        )

    except PlaywrightTimeoutError:

        block_reason = (
            detect_portal_block(
                response,
                page,
            )
        )

        if block_reason:

            raise PortalBlockedError(
                block_reason
            )

        print(
            "Nie znaleziono linków "
            "do ofert na stronie."
        )

        return [], False

    # -----------------------------------------------------
    # POBIERZ DOM
    # -----------------------------------------------------

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
                        link.getAttribute(
                            "href"
                        );

                    const card =
                        link.closest(
                            "article"
                        ) ||
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
                            (element) =>
                                (
                                    element.innerText
                                    || ""
                                ).trim()
                        )
                        .filter(Boolean);

                    return {

                        href:
                            href || "",

                        linkText:
                            (
                                link.innerText
                                || ""
                            ).trim(),

                        linkTitle:
                            link.getAttribute(
                                "title"
                            ) || "",

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

    # -----------------------------------------------------
    # BRAK OFERT
    # -----------------------------------------------------

    if not raw_jobs:

        block_reason = (
            detect_portal_block(
                response,
                page,
            )
        )

        if block_reason:

            raise PortalBlockedError(
                block_reason
            )

        print(
            "Strona została załadowana, "
            "ale nie znaleziono ofert."
        )

        return [], False

    # -----------------------------------------------------
    # NORMALIZACJA / DEDUPLIKACJA
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
                "przetwarzania oferty: "
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
        "Unikalnych ofert do "
        f"przetworzenia: {len(jobs)}"
    )

    if not jobs:

        print(
            "[WARN] Nie udało się "
            "przetworzyć żadnej oferty."
        )

        return [], False

    return jobs, True


# =========================================================
# SZCZEGÓŁY OFERTY
# =========================================================

def scrape_justjoin_details(
    page,
    job,
):
    """
    Otwiera stronę szczegółową oferty
    i pobiera dodatkowe informacje.
    """

    url = job["url"]

    print(
        f"[SZCZEGÓŁY] {job['title']}"
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
            detect_portal_block(
                None,
                page,
            )
        )

        if block_reason:

            raise PortalBlockedError(
                block_reason
            )

        return None

    # -----------------------------------------------------
    # SPRAWDŹ BLOKADĘ
    # -----------------------------------------------------

    block_reason = detect_portal_block(
        response,
        page,
    )

    if block_reason:

        print(
            "\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
            "!!! BLOKADA JUST JOIN IT !!!\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        print(
            f"Powód: {block_reason}"
        )

        raise PortalBlockedError(
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

    lines = []

    for line in body_text.splitlines():

        line = clean_text(
            line
        )

        if line:
            lines.append(
                line
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
    # PUBLIKACJA
    # -----------------------------------------------------

    published_at = (
        find_published_date(
            lines
        )
    )

    # -----------------------------------------------------
    # LOKALIZACJA
    # -----------------------------------------------------

    location = (
        find_detail_location(
            lines,
            title,
        )
    )

    # -----------------------------------------------------
    # PODSTAWOWE INFORMACJE
    # -----------------------------------------------------

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

    salary = clean_salary(
        lines
    )

    # -----------------------------------------------------
    # OPIS
    # -----------------------------------------------------

    job_description = _extract_section(
        lines,
        {
            "job description",
        },
        {
            "tech stack",
            "office location",
            "about the company",
            "similar offers",
        },
    )

    # -----------------------------------------------------
    # TECH STACK
    # -----------------------------------------------------

    tech_stack = _extract_section(
        lines,
        {
            "tech stack",
        },
        {
            "office location",
            "about the company",
            "similar offers",
        },
    )

    # -----------------------------------------------------
    # LOKALIZACJA BIURA
    # -----------------------------------------------------

    office_location = _extract_section(
        lines,
        {
            "office location",
        },
        {
            "about the company",
            "similar offers",
        },
    )

    # -----------------------------------------------------
    # INFORMACJE O FIRMIE
    # -----------------------------------------------------

    about_company = _extract_section(
        lines,
        {
            "about the company",
        },
        {
            "similar offers",
        },
    )

    # -----------------------------------------------------
    # WYGAŚNIĘCIE
    # -----------------------------------------------------

    expires_text, expires_at = (
        parse_expiration(
            lines
        )
    )

    # -----------------------------------------------------
    # WYNIK
    # -----------------------------------------------------

    return {
        "title": title,

        "company": job["company"],

        "location": (
            location
            or job["location"]
        ),

        "work_mode": (
            work_mode
            or job["work_mode"]
        ),

        "work_type": (
            work_type
            or job["work_type"]
        ),

        "experience_level":
            experience_level,

        "contract_type":
            contract_type,

        "salary": (
            salary
            or job["salary"]
        ),

        "published_at":
            published_at,

        "job_description":
            job_description,

        "tech_stack":
            tech_stack,

        "office_location":
            office_location,

        "about_company":
            about_company,

        "expires_text":
            expires_text,

        "expires_at":
            expires_at,
    }