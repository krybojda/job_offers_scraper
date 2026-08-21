import json
import re
from datetime import datetime
from urllib.parse import quote, urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from config import NOFLUFFJOBS_BASE_URL
from utils import clean_text, generate_source_id


class NoFluffJobsBlockedError(Exception):
    """Wykryto blokadę / rate limit na No Fluff Jobs."""


BLOCK_STATUS_CODES = {403, 429, 503}

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

CITY_NAMES = {
    "warszawa", "kraków", "wrocław", "poznań", "gdańsk",
    "katowice", "łódź", "lublin", "białystok", "rzeszów",
    "bydgoszcz", "szczecin", "krakow", "wroclaw", "poznan",
    "gdansk", "lodz",
}

TECHNOLOGY_WORDS = {
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform",
    "ansible", "jenkins", "gitlab", "github", "python", "java",
    "javascript", "typescript", "node.js", "go", "c#", ".net",
    "linux", "sql", "postgresql", "mysql", "oracle", "grafana",
    "prometheus", "helm", "argocd", "git", "ci/cd", "devops",
    "azure devops", "aws lambda", "cloudformation", "bash",
    "powershell", "kotlin", "ruby", "php", "react", "angular",
    "vue", "spring", "django", "flask", "fastapi", "redis",
    "mongodb", "elasticsearch", "kafka", "rabbitmq", "openstack",
    "cloud", "backend", "frontend", "data", "ai/ml", "security",
    "testing", "fullstack", "mobile", "erp",
}


def detect_nofluffjobs_block(response, page):
    if response is not None and response.status in BLOCK_STATUS_CODES:
        return f"HTTP {response.status}"

    try:
        body_text = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return None

    for pattern in BLOCK_TEXT_PATTERNS:
        if pattern in body_text:
            return f"wykryto tekst blokady: {pattern}"

    return None


def clean_lines(text):
    if not text:
        return []

    lines = []
    for line in text.splitlines():
        line = " ".join(line.split()).strip()
        if line:
            lines.append(line)

    return lines


def is_ui_line(line):
    return line.strip().lower() in UI_TEXTS


def salary_matches(text):
    return bool(
        re.search(
            r"\d[\d\s.,]*\s*(?:[–-]\s*\d[\d\s.,]*)?\s*"
            r"(?:PLN|EUR|USD|GBP|CHF)",
            text or "",
            re.IGNORECASE,
        )
    )


def find_salary(lines):
    patterns = [
        re.compile(
            r"\d[\d\s.,]*\s*[–-]\s*\d[\d\s.,]*\s*"
            r"(?:PLN|EUR|USD|GBP|CHF).*",
            re.IGNORECASE,
        ),
        re.compile(
            r"\d[\d\s.,]*\s*(?:PLN|EUR|USD|GBP|CHF).*",
            re.IGNORECASE,
        ),
    ]

    for pattern in patterns:
        for line in lines:
            if pattern.search(line):
                return line

    for line in lines:
        normalized = line.lower()
        if (
            "check salary" in normalized
            or "sprawdź wynagrodzenie" in normalized
            or "sprawdz wynagrodzenie" in normalized
        ):
            return line

    return None


def is_location_line(line):
    normalized = (line or "").strip().lower()

    if normalized in {"remote", "zdalnie"}:
        return True

    if re.fullmatch(r"(remote|zdalnie)\s*\+\d+", normalized):
        return True

    if normalized in CITY_NAMES:
        return True

    return bool(
        re.fullmatch(
            r"(?:warszawa|kraków|wrocław|poznań|gdańsk|katowice|łódź|"
            r"lublin|białystok|rzeszów|bydgoszcz|szczecin|krakow|"
            r"wroclaw|poznan|gdansk|lodz)(?:\s*\+\d+)?",
            normalized,
        )
    )


def find_location(lines):
    for line in lines:
        value = clean_text(line)
        if value and is_location_line(value):
            return value

    for line in lines:
        normalized = line.lower()
        if (
            ("remote" in normalized or "zdalnie" in normalized)
            and any(city in normalized for city in CITY_NAMES)
        ):
            return line.strip()

    return None


def find_work_mode(lines):
    for line in lines:
        normalized = line.strip().lower()

        if any(
            phrase in normalized
            for phrase in (
                "praca stacjonarna",
                "praca w biurze",
                "on-site",
                "onsite",
                "office work",
            )
        ):
            return "Office"

        if any(
            phrase in normalized
            for phrase in (
                "praca hybrydowa",
                "hybrydowo",
                "hybrid work",
                "hybrid",
            )
        ):
            return "Hybrid"

        if any(
            phrase in normalized
            for phrase in (
                "praca w pełni zdalna",
                "praca zdalna",
                "praca zdalna przez",
                "zdalnie",
                "remote work",
                "remote",
            )
        ):
            return "Remote"

    return None


def find_work_type(lines, title=None):
    """
    Próbuje rozpoznać typ zatrudnienia / wymiar pracy.

    No Fluff Jobs nie pokazuje tego pola identycznie
    dla każdej oferty, dlatego sprawdzamy zarówno
    polskie, jak i angielskie warianty.
    """

    text = " ".join(lines)
    if title:
        text += " " + title

    normalized = text.lower()

    if re.search(
        r"\b(full[- ]?time|pełny etat|pełnym etacie)\b",
        normalized,
    ):
        return "Full-time"

    if re.search(
        r"\b(part[- ]?time|część etatu|część[- ]?etatu)\b",
        normalized,
    ):
        return "Part-time"

    if re.search(
        r"\b(freelance|freelancer)\b",
        normalized,
    ):
        return "Freelance"

    if re.search(
        r"\b(b2b contract|kontrakt b2b)\b",
        normalized,
    ):
        return "B2B"

    return None


def find_experience_level(title, lines):
    text = " ".join(lines)

    explicit_patterns = [
        r"(?:poziom|level|experience level)\s*[:\-]?\s*"
        r"(junior|mid|middle|regular|senior|expert|lead)",
        r"(?:seniority|doświadczenie)\s*[:\-]?\s*"
        r"(junior|mid|middle|regular|senior|expert|lead)",
    ]

    for pattern in explicit_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).lower()
            return {
                "junior": "Junior",
                "mid": "Mid",
                "middle": "Mid",
                "regular": "Regular",
                "senior": "Senior",
                "expert": "Expert",
                "lead": "Lead",
            }[value]

    title_text = (title or "").lower()
    found = []

    if re.search(r"\bjunior\b", title_text):
        found.append("Junior")
    if re.search(r"\bmid\b", title_text):
        found.append("Mid")
    if re.search(r"\bmiddle\b", title_text):
        found.append("Mid")
    if re.search(r"\bregular\b", title_text):
        found.append("Regular")
    if re.search(r"\bsenior\b", title_text):
        found.append("Senior")
    if re.search(r"\bexpert\b", title_text):
        found.append("Expert")
    if re.search(r"\btech lead\b", title_text):
        found.append("Tech Lead")
    elif re.search(r"\blead\b", title_text):
        found.append("Lead")

    return ", ".join(dict.fromkeys(found)) or None


def find_contract_type(lines):
    text = "\n".join(lines).lower()
    found = []

    if re.search(r"\bb2b\b", text):
        found.append("B2B")

    if (
        "uop" in text
        or "uop brutto" in text
        or "umowa o pracę" in text
        or "umowa o prace" in text
    ):
        found.append("Umowa o pracę")

    if "umowa zlecenie" in text:
        found.append("Umowa zlecenie")

    if "umowa o dzieło" in text:
        found.append("Umowa o dzieło")

    if "freelance" in text:
        found.append("Freelance")

    return ", ".join(dict.fromkeys(found)) or None


def normalize_title(title):
    if not title:
        return None

    value = clean_text(title)
    if not value:
        return None

    patterns = [
        r"\s+NOWA$",
        r"\s+NEW$",
        r"\s+Zapisz ofertę$",
        r"\s+Zapisz oferte$",
        r"\s+Save$",
        r"\s+Sprawdź wynagrodzenie$",
        r"\s+Sprawdz wynagrodzenie$",
        r"\s+Check Salary$",
        r"\s+Aplikuj$",
        r"\s+Apply$",
    ]

    changed = True
    while changed:
        changed = False
        for pattern in patterns:
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


def find_title(item):
    for heading in item.get("headings") or []:
        value = normalize_title(heading)
        if value and len(value) <= 250 and not is_ui_line(value):
            return value

    for value in (
        normalize_title(item.get("ariaLabel")),
        normalize_title(item.get("linkTitle")),
    ):
        if value and len(value) <= 250 and not is_ui_line(value):
            return value

    for line in clean_lines(item.get("cardText") or ""):
        value = normalize_title(line)
        if not value or is_ui_line(value):
            continue
        if salary_matches(value) or is_location_line(value):
            continue
        if len(value) <= 250:
            return value

    return None


def find_company(item, title, lines):
    direct_company = clean_text(item.get("company"))
    if direct_company:
        return direct_company

    for line in lines:
        match = re.match(
            r"^(?:o firmie|about the company|about us)\s+(.+)$",
            line,
            re.IGNORECASE,
        )
        if match:
            return clean_text(match.group(1))

    location_index = None
    for index, line in enumerate(lines):
        if is_location_line(line):
            location_index = index

    if location_index is not None:
        for index in range(
            location_index - 1,
            max(-1, location_index - 12),
            -1,
        ):
            candidate = clean_text(lines[index])
            if not candidate:
                continue
            normalized = candidate.lower()
            if is_ui_line(candidate):
                continue
            if salary_matches(candidate):
                continue
            if is_location_line(candidate):
                continue
            if title and normalized == title.lower():
                continue
            if normalized in TECHNOLOGY_WORDS:
                continue
            if len(candidate) > 150:
                continue
            return candidate

    return None


def extract_job_from_raw_item(item, keyword):
    href = (item.get("href") or "").strip()
    if not href:
        return None

    if "/job/" not in href and "/job1/" not in href:
        return None

    # Używamy tej samej stałej, która jest importowana z config.py.
    # Wcześniej była tu literówka NOF_FLUFFJOBS_BASE_URL,
    # przez co każda znaleziona oferta kończyła się NameError.
    url = urljoin(NOFLUFFJOBS_BASE_URL, href)
    source_id = generate_source_id(url)
    lines = clean_lines(item.get("cardText") or "")
    if not lines:
        return None

    title = find_title(item)
    if not title:
        return None

    return {
        "portal": "nofluffjobs",
        "source_id": source_id,
        "title": title,
        "company": find_company(item, title, lines),
        "location": find_location(lines),
        "work_mode": find_work_mode(lines),
        "work_type": find_work_type(lines, title),
        "experience_level": find_experience_level(title, lines),
        "contract_type": find_contract_type(lines),
        "salary": find_salary(lines),
        "url": url,
        "keyword": keyword,
        "published_at": None,
    }


def build_nofluffjobs_url(keyword):
    encoded_keyword = quote(keyword.strip(), safe="")
    return f"{NOFLUFFJOBS_BASE_URL}/pl?criteria={encoded_keyword}"


def scrape_nofluffjobs_page(page, keyword):
    url = build_nofluffjobs_url(keyword)
    print(f"\nNo Fluff Jobs → {keyword}")
    print(f"URL: {url}")

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_timeout(7000)
    except PlaywrightTimeoutError:
        reason = detect_nofluffjobs_block(None, page)
        if reason:
            raise NoFluffJobsBlockedError(reason)
        return [], False

    reason = detect_nofluffjobs_block(response, page)
    if reason:
        raise NoFluffJobsBlockedError(reason)

    print(f"Załadowany URL: {page.url}")

    try:
        page.wait_for_function(
            """
            () => document.querySelectorAll(
                "a[href*='/job']"
            ).length > 0
            """,
            timeout=15000,
        )
    except Exception:
        pass

    raw_items = page.evaluate(
        """
        () => {
            const links = Array.from(
                document.querySelectorAll("a[href*='/job']")
            );

            return links.map(link => {
                const card = link.closest(
                    "article, [data-cy*='job'], [class*='job-card'], [class*='JobCard']"
                ) || link.parentElement;

                const headings = card
                    ? Array.from(card.querySelectorAll("h1,h2,h3,h4"))
                        .map(node => node.innerText?.trim())
                        .filter(Boolean)
                    : [];

                return {
                    href: link.getAttribute("href") || "",
                    ariaLabel: link.getAttribute("aria-label") || "",
                    linkTitle: link.getAttribute("title") || "",
                    company: card?.querySelector(
                        "[data-cy*='company'], [class*='company'], [class*='Company']"
                    )?.innerText?.trim() || "",
                    headings,
                    cardText: card?.innerText || link.innerText || "",
                };
            });
        }
        """
    )

    print(f"Znaleziono elementów z linkiem ofert: {len(raw_items)}")

    jobs = []
    seen = set()

    for item in raw_items:
        try:
            job = extract_job_from_raw_item(item, keyword)
            if not job:
                continue

            if job["source_id"] in seen:
                continue

            seen.add(job["source_id"])
            jobs.append(job)
        except Exception as exc:
            print(f"[WARN] Błąd podczas przetwarzania oferty: {exc}")

    print(f"Unikalnych ofert: {len(jobs)}")
    return jobs, True


def scrape_nofluffjobs_detail(page, job):
    """Pobiera dodatkowe dane z pojedynczej strony oferty."""
    url = job.get("url")
    if not url:
        return job

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_timeout(3000)
    except PlaywrightTimeoutError:
        return job

    reason = detect_nofluffjobs_block(response, page)
    if reason:
        raise NoFluffJobsBlockedError(reason)

    try:
        text = page.locator("body").inner_text(timeout=10000)
        lines = clean_lines(text)

        salary = find_salary(lines)
        if salary:
            job["salary"] = salary

        location = find_location(lines)
        if location:
            job["location"] = location

        work_mode = find_work_mode(lines)
        if work_mode:
            job["work_mode"] = work_mode

        job["contract_type"] = find_contract_type(lines) or job.get(
            "contract_type"
        )
        job["work_type"] = find_work_type(
            lines,
            job.get("title"),
        ) or job.get("work_type")
        job["experience_level"] = find_experience_level(
            job.get("title"),
            lines,
        ) or job.get("experience_level")

        updated = datetime.utcnow().isoformat()
        job["updated_at"] = updated
    except Exception:
        pass

    return job


def save_debug_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
