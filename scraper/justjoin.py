import re
from urllib.parse import quote, urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError # type: ignore

from config import JUSTJOIN_BASE_URL
from utils import clean_text, generate_source_id


def clean_location(lines):
    """
    Próbuje znaleźć lokalizację.

    Przykład:

    Warszawa
    , +4
    Locations

    wynik:

    Warszawa, +4 Locations
    """

    for index, line in enumerate(lines):

        if not line:
            continue

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
                == "locations"
            ):

                location = (
                    f"{location} "
                    f"{lines[index + 2]}"
                )

            return location

    # Alternatywny przypadek:
    #
    # Warszawa
    # Locations

    for index in range(
        len(lines) - 1
    ):

        if (
            lines[index + 1].lower()
            == "locations"
        ):

            return lines[index]

    return None


def clean_salary(lines):
    """
    Próbuje znaleźć wynagrodzenie.

    Przykład:

    4 553,34 - 6 287,94
    CHF/month

    wynik:

    4 553,34 - 6 287,94 CHF/month
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

    return None


def find_work_mode(lines):
    """
    Szuka trybu pracy.
    """

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


def find_title(
    headings,
    link_title,
    link_text,
    lines,
):
    """
    Znajduje tytuł oferty.

    Priorytet:
    1. heading
    2. title linku
    3. tekst linku
    4. karta
    """

    # -----------------------------------------
    # HEADING
    # -----------------------------------------

    for heading in headings:

        heading = clean_text(
            heading
        )

        if heading:
            return heading

    # -----------------------------------------
    # TITLE ATRYBUTU
    # -----------------------------------------

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

    # -----------------------------------------
    # TEKST LINKU
    # -----------------------------------------

    link_text = clean_text(
        link_text
    )

    if link_text:
        return link_text

    # -----------------------------------------
    # AWARYJNIE KARTA
    # -----------------------------------------

    excluded = {
        "remote",
        "hybrid",
        "office",
        "locations",
        "new",
        "super offer",
        "1-click apply",
        "full-time",
        "part-time",
        "senior",
        "mid",
        "junior",
        "intern",
    }

    for line in lines:

        normalized = (
            line.lower()
        )

        if normalized in excluded:
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


def extract_job_from_raw_item(
    item,
    keyword,
):
    """
    Zamienia surowy rekord DOM
    na wspólny format oferty.
    """

    href = clean_text(
        item.get("href")
    )

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

    headings = (
        item.get("headings")
        or []
    )

    title = find_title(
        headings=headings,
        link_title=item.get(
            "linkTitle"
        ),
        link_text=item.get(
            "linkText"
        ),
        lines=lines,
    )

    if not title:
        return None

    location = clean_location(
        lines
    )

    work_mode = find_work_mode(
        lines
    )

    salary = clean_salary(
        lines
    )

    # Pierwsza linia karty to obecnie
    # firma w strukturze Just Join,
    # np. CloudFerro S.A.

    company = None

    if lines:

        candidate = lines[0]

        if (
            candidate
            and candidate != title
            and candidate != location
        ):

            company = candidate

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


def scrape_justjoin_page(
    page,
    keyword,
):
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

    # -----------------------------------------
    # OTWARCIE STRONY
    # -----------------------------------------

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
    # ODCZYT DOM
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

    if not raw_jobs:
        return []

    # -----------------------------------------
    # DEBUG
    # -----------------------------------------

    first = raw_jobs[0]

    print(
        "\n--- DEBUG PIERWSZEJ OFERTY ---"
    )

    print(
        f"href: {first.get('href')}"
    )

    print(
        f"linkTitle: "
        f"{first.get('linkTitle')}"
    )

    print(
        f"headings: "
        f"{first.get('headings')}"
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

    # -----------------------------------------
    # PODGLĄD PIERWSZEGO REKORDU
    # -----------------------------------------

    if jobs:

        first_job = jobs[0]

        print(
            "\n--- DEBUG "
            "PRZETWORZONEJ OFERTY ---"
        )

        print(
            f"Tytuł: "
            f"{first_job['title']}"
        )

        print(
            f"Firma: "
            f"{first_job['company']}"
        )

        print(
            f"Lokalizacja: "
            f"{first_job['location']}"
        )

        print(
            f"Tryb: "
            f"{first_job['work_mode']}"
        )

        print(
            f"Wynagrodzenie: "
            f"{first_job['salary']}"
        )

        print(
            f"URL: "
            f"{first_job['url']}"
        )

        print(
            "--- KONIEC DEBUG ---\n"
        )

    return jobs