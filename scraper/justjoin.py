import re
from datetime import datetime
from urllib.parse import quote, urljoin


from playwright.sync_api import TimeoutError as PlaywrightTimeoutError # type: ignore

from config import JUSTJOIN_BASE_URL
from utils import clean_text, generate_source_id


def find_published_date(lines):
    """
    Szuka daty publikacji na stronie szczegółowej.

    Przykład:
        Published: 19.08.2026

    Zwraca obiekt datetime albo None.
    """

    date_pattern = re.compile(
        r"(?:published|published\s+on)\s*:\s*"
        r"(\d{2}\.\d{2}\.\d{4})",
        re.IGNORECASE,
    )

    for line in lines:

        match = date_pattern.search(line)

        if not match:
            continue

        try:
            return datetime.strptime(
                match.group(1),
                "%d.%m.%Y",
            )

        except ValueError:
            continue

    return None


def find_detail_location(lines, title):
    """
    Próbuje znaleźć właściwą lokalizację oferty
    z sekcji "Summary of the offer".

    Typowy układ Just Join:

    Summary of the offer
    ...
    DevOps Engineer
    -, Warszawa
    Firma
    ...

    albo:

    DevOps Engineer
    centrum, Warszawa
    Firma
    """

    summary_index = None

    for index, line in enumerate(lines):

        if line.lower().strip() == "summary of the offer":
            summary_index = index
            break

    if summary_index is None:
        return None

    normalized_title = (
        title.lower().strip()
        if title
        else ""
    )

    # Szukamy tytułu wewnątrz Summary.
    for index in range(
        summary_index + 1,
        min(
            summary_index + 30,
            len(lines),
        ),
    ):

        line = lines[index]

        if (
            normalized_title
            and line.lower().strip()
            == normalized_title
        ):

            # Kolejna sensowna linia powinna
            # zawierać lokalizację.
            for next_index in range(
                index + 1,
                min(
                    index + 5,
                    len(lines),
                ),
            ):

                candidate = lines[next_index].strip()

                if not candidate:
                    continue

                # Pomijamy elementy interfejsu.
                if candidate.lower() in {
                    "save",
                    "apply",
                    "summary of the offer",
                }:
                    continue

                # Jeżeli kolejna linia jest firmą,
                # będzie trudniej ją odróżnić.
                # Lokalizacja zwykle zawiera przecinek
                # albo zaczyna się od "-,".
                if (
                    "," in candidate
                    or candidate.startswith("-,")
                ):

                    candidate = candidate.strip()

                    # "-, Warszawa" -> "Warszawa"
                    candidate = re.sub(
                        r"^-\s*,\s*",
                        "",
                        candidate,
                    )

                    return candidate

                # Jeżeli mamy zwykłą lokalizację,
                # np. Warszawa.
                if re.search(
                    r"""\b(
                        Warszawa|
                        Kraków|
                        Wrocław|
                        Poznań|
                        Gdańsk|
                        Katowice|
                        Łódź|
                        Lublin|
                        Białystok|
                        Rzeszów|
                        Bydgoszcz|
                        Szczecin|
                        Krakow|
                        Wroclaw|
                        Poznan
                    )\b""",
                    candidate,
                    re.IGNORECASE | re.VERBOSE,
                ):
                    return candidate

    return None

def clean_lines(value):
    """
    Czyści tekst, ale zachowuje podział na linie.

    Jest to ważne przy parsowaniu kart Just Join,
    ponieważ kolejność linii określa znaczenie danych.
    """

    if not value:
        return []

    lines = []

    for line in value.splitlines():
        line = " ".join(line.split()).strip()

        if line:
            lines.append(line)

    return lines

def clean_location(lines):
    """
    Wyciąga lokalizację z karty wyników Just Join.
    """

    # -----------------------------------------
    # PRZYPADEK:
    #
    # Warszawa
    # , +4
    # Locations
    # -----------------------------------------

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

    # -----------------------------------------
    # PRZYPADEK:
    #
    # Warszawa
    # Locations
    # -----------------------------------------

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

    # -----------------------------------------
    # Nie znaleziono
    # -----------------------------------------

    return None

def clean_salary(lines):
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


def find_work_type(lines):
    work_types = {
        "full-time",
        "part-time",
        "practice / internship",
        "internship",
        "freelance",
        "b2b contract",
    }

    found = []

    for line in lines:

        if line.lower().strip() in work_types:
            found.append(line)

    if not found:
        return None

    return ", ".join(
        dict.fromkeys(found)
    )


def find_experience_level(lines):
    levels = {
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

        normalized = (
            line
            .lower()
            .strip()
        )

        if normalized in levels:
            found.append(line)

    if not found:
        return None

    return ", ".join(
        dict.fromkeys(found)
    )


def find_contract_type(lines):
    contracts = {
        "b2b",
        "permanent",
        "mandate",
        "specific-task contract",
        "mandate contract",
    }

    found = []

    for line in lines:

        normalized = (
            line
            .lower()
            .strip()
        )

        if normalized in contracts:
            found.append(line)

    if not found:
        return None

    return ", ".join(
        dict.fromkeys(found)
    )


def find_title(
    headings,
    link_title,
    link_text,
    lines,
):
    for heading in headings:

        heading = clean_text(
            heading
        )

        if heading:
            return heading

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

    link_text = clean_text(
        link_text
    )

    if link_text:
        return link_text

    for line in lines:

        if len(line) > 5:
            return line

    return None


def build_justjoin_url(keyword):
    normalized = keyword.strip()

    if " " not in normalized:

        slug = quote(
            normalized.lower()
        )

        return (
            f"{JUSTJOIN_BASE_URL}/"
            f"job-offers/all-locations/"
            f"{slug}"
        )

    encoded = quote(
        normalized
    )

    return (
        f"{JUSTJOIN_BASE_URL}/"
        f"job-offers/all-locations/devops"
        f"?q={encoded}%40keyword"
    )


def extract_job_from_raw_item(item, keyword):
    """
    Zamienia surowy rekord z DOM na wspólny format oferty.

    Zachowujemy strukturę linii karty, ponieważ Just Join
    prezentuje dane w ustalonej kolejności.
    """

    href = item.get("href", "").strip()

    if not href:
        return None

    if "/job-offer/" not in href:
        return None

    url = urljoin(
        JUSTJOIN_BASE_URL,
        href,
    )

    source_id = generate_source_id(url)

    # -------------------------------------------------
    # WAŻNE:
    # tutaj NIE używamy clean_text() przed splitlines()
    # -------------------------------------------------

    lines = clean_lines(
        item.get("cardText")
    )

    if not lines:
        return None

    # -------------------------------------------------
    # TYTUŁ
    # -------------------------------------------------

    headings = item.get("headings") or []

    title = None

    for heading in headings:
        heading = clean_text(heading)

        if heading:
            title = heading
            break

    if not title:

        link_title = clean_text(
            item.get("linkTitle")
        )

        if link_title:

            title = re.sub(
                r"^\s*view\s+offer\s*",
                "",
                link_title,
                flags=re.IGNORECASE,
            )

    if not title:

        link_text = clean_text(
            item.get("linkText")
        )

        if link_text:
            title = link_text

    if not title:
        return None

    # -------------------------------------------------
    # FIRMA
    # -------------------------------------------------

    # W aktualnej karcie Just Join firma znajduje się
    # jako pierwszy sensowny element tekstowy.
    company = lines[0]

    if company == title:
        company = None

    # -------------------------------------------------
    # LOKALIZACJA
    # -------------------------------------------------

    location = None

    for index, line in enumerate(lines):

        # Warszawa
        # , +4
        # Locations

        if (
            index + 1 < len(lines)
            and lines[index + 1].startswith(",")
        ):

            location = (
                f"{line}{lines[index + 1]}"
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

            break

        # Warszawa
        # Locations

        if (
            index + 1 < len(lines)
            and lines[index + 1].lower()
            in {
                "location",
                "locations",
            }
        ):

            location = line

            break

    # -------------------------------------------------
    # TRYB PRACY
    # -------------------------------------------------

    work_mode = None

    for line in lines:

        normalized = line.lower()

        if normalized == "remote":
            work_mode = "Remote"
            break

        if normalized == "hybrid":
            work_mode = "Hybrid"
            break

        if normalized == "office":
            work_mode = "Office"
            break

    # -------------------------------------------------
    # WYNAGRODZENIE
    # -------------------------------------------------

    salary = None

    salary_range = re.compile(
        r"""
        \d[\d\s.,]*
        \s*-\s*
        \d[\d\s.,]*
        """,
        re.VERBOSE,
    )

    for index, line in enumerate(lines):

        if salary_range.search(line):

            salary = line

            if index + 1 < len(lines):

                next_line = lines[index + 1]

                if re.search(
                    r"(usd|eur|pln|gbp|chf|"
                    r"/month|/h|month)",
                    next_line,
                    re.IGNORECASE,
                ):

                    salary = (
                        f"{salary} "
                        f"{next_line}"
                    )

            break

        if re.search(
            r"undisclosed\s+salary",
            line,
            re.IGNORECASE,
        ):

            salary = line
            break

    # -------------------------------------------------
    # WORK TYPE
    # -------------------------------------------------

    work_type_values = {
        "full-time",
        "part-time",
        "practice / internship",
        "freelance",
        "b2b contract",
    }

    work_type_found = []

    for line in lines:

        normalized = line.lower()

        if normalized in work_type_values:
            work_type_found.append(line)

    work_type = ", ".join(
        dict.fromkeys(work_type_found)
    ) or None

    # -------------------------------------------------
    # EXPERIENCE
    # -------------------------------------------------

    experience_values = {
        "intern",
        "junior",
        "mid",
        "senior",
        "team leader",
        "manager",
        "c-level",
    }

    experience_found = []

    for line in lines:

        normalized = line.lower()

        if normalized in experience_values:
            experience_found.append(line)

    experience_level = ", ".join(
        dict.fromkeys(experience_found)
    ) or None

    # -------------------------------------------------
    # CONTRACT TYPE
    # -------------------------------------------------

    contract_values = {
        "b2b",
        "permanent",
        "internship",
        "mandate contract",
        "specific-task contract",
    }

    contract_found = []

    for line in lines:

        normalized = line.lower()

        if normalized in contract_values:
            contract_found.append(line)

    contract_type = ", ".join(
        dict.fromkeys(contract_found)
    ) or None

    # -------------------------------------------------
    # ZWRÓĆ REKORD
    # -------------------------------------------------

    return {
        "portal": "justjoin",
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
        "published_at": None,
    }

def scrape_justjoin_page(
    page,
    keyword,
):
    url = build_justjoin_url(
        keyword
    )

    print(
        f"\nJust Join IT → {keyword}"
    )

    print(
        f"URL: {url}"
    )

    try:

        page.goto(
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

        return [], False

    print(
        f"Załadowany URL: {page.url}"
    )

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

        return [], False

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
                f"przetwarzania: {error}"
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

    # `True` oznacza, że strona została
    # poprawnie zescrapowana.
    return jobs, True


def _extract_section(
    lines,
    start_titles,
    end_titles,
):
    start_index = None

    for index, line in enumerate(lines):

        normalized = line.lower().strip()

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

    return "\n".join(section).strip()


def parse_expiration(lines):
    """
    Wyciąga tekst wygaśnięcia i, jeżeli portal
    pokazuje dokładną datę, zamienia ją na DATETIME.
    """

    for line in lines:

        normalized = line.lower()

        if (
            "offer expired"
            in normalized
        ):

            return (
                "Offer expired",
                None,
            )

        if re.search(
            r"until\s+\d{2}\.\d{2}\.\d{4}",
            line,
            re.IGNORECASE,
        ):

            match = re.search(
                r"(\d{2}\.\d{2}\.\d{4})",
                line,
            )

            if match:

                try:

                    date_value = datetime.strptime(
                        match.group(1),
                        "%d.%m.%Y",
                    )

                    return (
                        line,
                        date_value,
                    )

                except ValueError:
                    pass

        if re.search(
            r"\b\d+\s*day[s]?\s*left\b",
            normalized,
        ):

            return (
                line,
                None,
            )

        if "expires tomorrow" in normalized:

            return (
                line,
                None,
            )

        if "expires today" in normalized:

            return (
                line,
                None,
            )

    return None, None


def scrape_justjoin_details(
    page,
    job,
):
    """
    Otwiera stronę szczegółową jednej oferty
    i pobiera dodatkowe informacje.
    """

    url = job["url"]

    print(
        f"[SZCZEGÓŁY] {job['title']}"
    )

    try:

        page.goto(
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

        return None

    body_text = page.locator(
        "body"
    ).inner_text(
        timeout=10000
    )

    lines = [
        clean_text(line)
        for line in body_text.split("\n")
        if clean_text(line)
    ]

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



    # -----------------------------------------
    # PODSTAWOWE INFORMACJE
    # -----------------------------------------

    published_at = find_published_date(
        lines
    )

    location = find_detail_location(
        lines,
        job["title"]
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
    
    # -----------------------------------------
    # SEKCJE
    # -----------------------------------------

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

    about_company = _extract_section(
        lines,
        {
            "about the company",
        },
        {
            "similar offers",
        },
    )

    # -----------------------------------------
    # WYGAŚNIĘCIE
    # -----------------------------------------

    expires_text, expires_at = (
        parse_expiration(lines)
    )

    return {
        "title": title,
        "company": job["company"],
        "location": location or job["location"],
        "work_mode": work_mode or job["work_mode"],
        "work_type": work_type or job["work_type"],
        "experience_level": experience_level,
        "contract_type": contract_type,
        "salary": salary or job["salary"],
        "published_at": published_at,
        "job_description": job_description,
        "tech_stack": tech_stack,
        "office_location": office_location,
        "about_company": about_company,
        "expires_text": expires_text,
        "expires_at": expires_at,
    }