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

    # Fallback na podstawie rozpoznanej lokalizacji
    for line in lines:
        value = clean_text(line)
        if value and is_location_line(value):
            norm = value.lower().strip()
            if "remote" in norm or "zdalnie" in norm:
                return "Remote"
            elif "+" in norm or "locations" in norm:
                return "Hybrid"
            else:
                return "Office"

    return None


def find_work_type(lines, title=None):
    """
    Próbuje rozpoznać typ zatrudnienia / wymiar pracy.
    """
    text = " ".join(lines)
    if title:
        text += " " + title

    normalized = text.lower()

    if re.search(
        r"\b(full[- ]?time|pełny etat|pelny etat|pełnym etacie|pelnym etacie|cały etat|caly etat)\b",
        normalized,
    ):
        return "Pełny etat"

    if re.search(
        r"\b(part[- ]?time|część etatu|czesc etatu|część[- ]?etatu|pół etatu|pol etatu)\b",
        normalized,
    ):
        return "Część etatu"

    if re.search(
        r"\b(staż|staz|praktyka|praktyki|internship|intern)\b",
        normalized,
    ):
        return "Staż / Praktyka"

    if re.search(
        r"\b(freelance|freelancer)\b",
        normalized,
    ):
        return "Freelance"

    return "Pełny etat"


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
        or "umowę o pracę" in text
        or "umowa o prace" in text
        or "employment contract" in text
        or "permanent" in text
    ):
        found.append("Umowa o pracę")

    if (
        "uz" in text
        or "umowa zlecenie" in text
        or "umowę zlecenie" in text
        or "mandate contract" in text
    ):
        found.append("Umowa zlecenie")

    if "uod" in text or "umowa o dzieło" in text or "umowę o dzieło" in text:
        found.append("Umowa o dzieło")

    if "freelance" in text:
        found.append("Freelance")

    # Fallback stawek godzinowych i dziennych na B2B
    if not found:
        if re.search(r"/\s*(?:godz|h|dzień|dzien|day)\b", text, re.IGNORECASE):
            found.append("B2B")

    if not found:
        return None

    return ", ".join(dict.fromkeys(found))


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
                "a[href*='/job/'], a[href*='/job1/']"
            ).length > 0
            """,
            timeout=30000,
        )
    except PlaywrightTimeoutError:
        reason = detect_nofluffjobs_block(response, page)
        if reason:
            raise NoFluffJobsBlockedError(reason)
        print("Nie znaleziono linków do ofert.")
        return [], False

    raw_jobs = page.evaluate(
        """
        () => {
            const links = Array.from(
                document.querySelectorAll(
                    "a[href*='/job/'], a[href*='/job1/']"
                )
            );

            return links.map((link) => {
                const href = link.getAttribute("href");
                if (!href) return null;

                const headings = Array.from(
                    link.querySelectorAll(
                        "h1, h2, h3, h4, [role='heading']"
                    )
                )
                .map((element) => (
                    element.innerText || ""
                ).trim())
                .filter(Boolean);

                return {
                    href,
                    linkText: (link.innerText || "").trim(),
                    ariaLabel: link.getAttribute("aria-label") || "",
                    linkTitle: link.getAttribute("title") || "",
                    headings,
                    cardText: (link.innerText || "").trim(),
                };
            }).filter(Boolean);
        }
        """
    )

    print(
        "Znaleziono elementów z linkiem ofert: "
        f"{len(raw_jobs)}"
    )

    if not raw_jobs:
        print("Brak ofert na stronie.")
        return [], False

    jobs = []
    seen = set()

    for item in raw_jobs:
        try:
            job = extract_job_from_raw_item(item, keyword)
        except Exception as error:
            print(
                "[WARN] Błąd podczas przetwarzania oferty: "
                f"{error}"
            )
            continue

        if not job:
            continue

        if job["source_id"] in seen:
            continue

        seen.add(job["source_id"])
        jobs.append(job)

    print(f"Unikalnych ofert: {len(jobs)}")

    if jobs:
        first = jobs[0]
        print("\n--- PODGLĄD NO FLUFF JOBS ---")
        print(f"Tytuł: {first.get('title')}")
        print(f"Firma: {first.get('company')}")
        print(f"Lokalizacja: {first.get('location')}")
        print(f"Tryb: {first.get('work_mode')}")
        print(f"Typ: {first.get('work_type')}")
        print(f"Poziom: {first.get('experience_level')}")
        print(f"Umowa: {first.get('contract_type')}")
        print(f"Wynagrodzenie: {first.get('salary')}")
        print(f"URL: {first.get('url')}")
        print("--- KONIEC PODGLĄDU ---")

    return jobs, True


def scrape_nofluffjobs(page, keyword, min_delay=None, max_delay=None):
    try:
        jobs, page_ok = scrape_nofluffjobs_page(page, keyword)
    except NoFluffJobsBlockedError:
        raise
    except Exception as error:
        print(f"[ERROR] No Fluff Jobs dla '{keyword}': {error}")
        return [], set(), False

    if not page_ok:
        return [], set(), False

    seen_source_ids = {job["source_id"] for job in jobs}
    print(
        f"\nNo Fluff Jobs → {keyword}: "
        f"łącznie {len(jobs)} unikalnych ofert"
    )

    return jobs, seen_source_ids, True


def extract_nofluff_section(lines, start_patterns, end_patterns):
    start_index = None

    for index, line in enumerate(lines):
        normalized = line.lower().strip()
        if any(pattern in normalized for pattern in start_patterns):
            start_index = index + 1
            break

    if start_index is None:
        return None

    end_index = len(lines)
    for index in range(start_index, len(lines)):
        normalized = lines[index].lower().strip()
        if any(pattern in normalized for pattern in end_patterns):
            end_index = index
            break

    section = lines[start_index:end_index]
    return "\n".join(section).strip() if section else None


def extract_nofluff_technologies(lines):
    display_names = {
        "aws": "AWS", "azure": "Azure", "gcp": "GCP",
        "docker": "Docker", "kubernetes": "Kubernetes", "terraform": "Terraform",
        "ansible": "Ansible", "jenkins": "Jenkins", "gitlab": "GitLab", "github": "GitHub",
        "python": "Python", "java": "Java", "javascript": "JavaScript", "typescript": "TypeScript",
        "node.js": "Node.js", "go": "Go", "c#": "C#", ".net": ".NET", "linux": "Linux",
        "sql": "SQL", "postgresql": "PostgreSQL", "mysql": "MySQL", "oracle": "Oracle",
        "grafana": "Grafana", "prometheus": "Prometheus", "helm": "Helm", "argocd": "ArgoCD",
        "git": "Git", "ci/cd": "CI/CD", "devops": "DevOps", "azure devops": "Azure DevOps",
        "aws lambda": "AWS Lambda", "cloudformation": "CloudFormation", "bash": "Bash",
        "powershell": "PowerShell", "kotlin": "Kotlin", "ruby": "Ruby", "php": "PHP",
        "react": "React", "angular": "Angular", "vue": "Vue", "spring": "Spring",
        "django": "Django", "flask": "Flask", "fastapi": "FastAPI", "redis": "Redis",
        "mongodb": "MongoDB", "elasticsearch": "Elasticsearch", "kafka": "Kafka",
        "rabbitmq": "RabbitMQ", "openstack": "OpenStack", "cloud": "Cloud", "backend": "Backend",
        "frontend": "Frontend", "data": "Data", "ai/ml": "AI/ML", "security": "Security",
        "testing": "Testing", "fullstack": "Fullstack", "mobile": "Mobile", "erp": "ERP",
    }

    result = []
    for line in lines:
        normalized = line.lower()
        for key in sorted(TECHNOLOGY_WORDS, key=len, reverse=True):
            if key in normalized:
                value = display_names.get(key, key)
                if value not in result:
                    result.append(value)

    return ", ".join(result) if result else None


def _parse_datetime_value(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    if text.isdigit() and len(text) in {10, 13}:
        try:
            timestamp = int(text)
            if len(text) == 13:
                timestamp //= 1000
            return datetime.fromtimestamp(timestamp)
        except (ValueError, OSError, OverflowError):
            pass

    text = text.replace("Z", "+00:00")

    try:
        value = datetime.fromisoformat(text)
        return value.replace(tzinfo=None)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y",
        "%d.%m.%Y %H:%M:%S",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def _collect_published_date(page, body_text):
    """
    Szuka daty publikacji w kilku źródłach HTML.
    Nie wykorzystuje first_seen_at jako daty publikacji.
    """

    # -----------------------------------------------------
    # 1. JSON-LD
    # -----------------------------------------------------

    try:
        scripts = page.locator(
            "script[type='application/ld+json']"
        ).all_inner_texts()

        stack = []

        for script_text in scripts:
            try:
                data = json.loads(script_text)
            except Exception:
                continue

            if isinstance(data, list):
                stack.extend(data)
            else:
                stack.append(data)

        while stack:
            item = stack.pop()
            if not isinstance(item, dict):
                continue

            for key in (
                "datePosted",
                "datePublished",
                "publishedAt",
                "published_at",
                "publicationDate",
                "publication_date",
            ):
                parsed = _parse_datetime_value(item.get(key))
                if parsed:
                    return parsed

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

            for key in (
                "item",
                "mainEntity",
                "mainEntityOfPage",
                "job",
                "offer",
            ):
                nested = item.get(key)
                if isinstance(nested, dict):
                    stack.append(nested)
                elif isinstance(nested, list):
                    stack.extend(nested)

    except Exception:
        pass

    # -----------------------------------------------------
    # 2. Meta tags / time
    # -----------------------------------------------------

    try:
        values = page.evaluate(
            """
            () => {
                const result = [];

                for (const meta of document.querySelectorAll(
                    "meta[property], meta[name]"
                )) {
                    const key = (
                        meta.getAttribute("property") ||
                        meta.getAttribute("name") ||
                        ""
                    ).toLowerCase();

                    if (
                        key.includes("published") ||
                        key.includes("publication") ||
                        key === "date" ||
                        key === "dateposted"
                    ) {
                        const value = meta.getAttribute("content");
                        if (value) result.push(value);
                    }
                }

                for (const element of document.querySelectorAll(
                    "time[datetime], [data-published-at], [data-published], " +
                    "[data-date-posted], [data-publication-date]"
                )) {
                    const value =
                        element.getAttribute("datetime") ||
                        element.getAttribute("data-published-at") ||
                        element.getAttribute("data-published") ||
                        element.getAttribute("data-date-posted") ||
                        element.getAttribute("data-publication-date");

                    if (value) result.push(value);
                }

                return result;
            }
            """
        )

        for value in values:
            parsed = _parse_datetime_value(value)
            if parsed:
                return parsed

    except Exception:
        pass

    # -----------------------------------------------------
    # 3. Tekst strony / dane osadzone w skrypcie
    # -----------------------------------------------------

    text_patterns = [
        r"(?:datePosted|datePublished|publishedAt|published_at|publicationDate|publication_date)"
        r"\s*[\"']?\s*[:=]\s*[\"']([^\"']+)",
        r"(?:opublikowano|opublikowana|opublikowany|published)"
        r"\s*[:\-]\s*(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    ]

    for pattern in text_patterns:
        match = re.search(
            pattern,
            body_text,
            re.IGNORECASE,
        )
        if match:
            parsed = _parse_datetime_value(match.group(1))
            if parsed:
                return parsed

    return None


def _fallback_job_description(lines):
    """
    Fallback dla ofert, w których nie występuje
    jednoznaczny nagłówek sekcji opisu.
    """

    start_markers = {
        "oryginalny tekst.",
        "oryginalny tekst",
        "original text",
    }

    end_markers = {
        "pokaż tłumaczenie",
        "pokaz tlumaczenie",
        "pokaż wszystko",
        "pokaz wszystko",
        "szczegóły oferty",
        "szczegoly oferty",
        "aplikuj",
        "zapisz ofertę",
        "zapisz oferte",
    }

    start_index = None

    for index, line in enumerate(lines):
        if line.lower().strip() in start_markers:
            start_index = index + 1
            break

    if start_index is None:
        return None

    end_index = len(lines)

    for index in range(start_index, len(lines)):
        if lines[index].lower().strip() in end_markers:
            end_index = index
            break

    description_lines = [
        line
        for line in lines[start_index:end_index]
        if line.strip()
    ]

    if not description_lines:
        return None

    return "\n".join(description_lines).strip()


def scrape_nofluffjobs_details(page, job):
    url = job["url"]

    print(
        f"[SZCZEGÓŁY NO FLUFF JOBS] {job['title']}"
    )

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_timeout(5000)
    except PlaywrightTimeoutError:
        reason = detect_nofluffjobs_block(None, page)
        if reason:
            raise NoFluffJobsBlockedError(reason)
        return None

    reason = detect_nofluffjobs_block(response, page)
    if reason:
        raise NoFluffJobsBlockedError(reason)

    try:
        body_text = page.locator("body").inner_text(timeout=10000)
    except Exception as error:
        print(
            "[WARN] Nie udało się odczytać strony szczegółowej: "
            f"{error}"
        )
        return None

    lines = clean_lines(body_text)
    if not lines:
        return None

    title = job.get("title")
    company = job.get("company")

    try:
        h1 = page.locator("h1").first
        if h1.count() > 0:
            value = normalize_title(h1.inner_text(timeout=5000))
            if value:
                title = value
    except Exception:
        pass

    try:
        selectors = [
            "a[href*='/company/']",
            "[class*='company-name']",
            "[class*='companyName']",
        ]

        for selector in selectors:
            locator = page.locator(selector)
            count = locator.count()
            if count == 0:
                continue

            for index in range(min(count, 5)):
                try:
                    value = clean_text(
                        locator.nth(index).inner_text(timeout=2000)
                    )
                except Exception:
                    continue

                if value and not (
                    title and value.lower() == title.lower()
                ):
                    company = value
                    break

            if company:
                break
    except Exception:
        pass

    for line in lines:
        match = re.match(
            r"^(?:o firmie|about the company|about us)\s+(.+)$",
            line,
            re.IGNORECASE,
        )
        if match:
            company = clean_text(match.group(1))
            break

    # -----------------------------------------------------
    # POBIERZ DANE ZE STRUKTURY JSON-LD
    # -----------------------------------------------------
    ld_job_posting = None
    try:
        scripts = page.locator("script[type='application/ld+json']").all_inner_texts()
        for script_text in scripts:
            try:
                data = json.loads(script_text)
                if isinstance(data, dict):
                    if "@graph" in data:
                        for g in data["@graph"]:
                            if isinstance(g, dict) and g.get("@type") == "JobPosting":
                                ld_job_posting = g
                                break
                    elif data.get("@type") == "JobPosting":
                        ld_job_posting = data
                        break
                elif isinstance(data, list):
                    for g in data:
                        if isinstance(g, dict) and g.get("@type") == "JobPosting":
                            ld_job_posting = g
                            break
                if ld_job_posting:
                    break
            except Exception:
                continue
    except Exception:
        pass

    if ld_job_posting:
        if not company:
            hiring_org = ld_job_posting.get("hiringOrganization")
            if isinstance(hiring_org, dict) and hiring_org.get("name"):
                company = clean_text(hiring_org["name"])

    location = find_location(lines) or job.get("location")
    work_mode = find_work_mode(lines) or job.get("work_mode")
    work_type = find_work_type(lines, title) or job.get("work_type")

    experience_level = None
    if ld_job_posting:
        exp_req = ld_job_posting.get("experienceRequirements")
        if isinstance(exp_req, dict) and exp_req.get("description"):
            experience_level = clean_text(exp_req["description"])
    if not experience_level:
        experience_level = find_experience_level(title, lines) or job.get("experience_level")

    contract_type = None
    if ld_job_posting:
        emp_type = ld_job_posting.get("employmentType")
        if emp_type:
            emp_str = str(emp_type).upper()
            if "CONTRACTOR" in emp_str or "CONTRACT" in emp_str:
                contract_type = "B2B"
            elif any(k in emp_str for k in ("FULL_TIME", "EMPLOYEE", "PERMANENT")):
                contract_type = "Umowa o pracę"
    if not contract_type:
        contract_type = find_contract_type(lines) or job.get("contract_type")

    salary = find_salary(lines) or job.get("salary")

    # published_at pochodzi ze Schema.org JobPosting lub źródeł strony
    published_at = None
    if ld_job_posting and ld_job_posting.get("datePosted"):
        published_at = _parse_datetime_value(ld_job_posting["datePosted"])
    if not published_at:
        published_at = _collect_published_date(page, body_text)

    job_description = extract_nofluff_section(
        lines,
        [
            "opis stanowiska", "job description", "description",
            "zakres obowiązków", "responsibilities",
        ],
        [
            "obowiązkowe", "must have", "wymagania", "requirements",
            "mile widziane", "nice to have", "benefity", "benefits",
            "o firmie", "about the company", "szczegóły oferty",
            "szczegoly oferty",
        ],
    )

    if not job_description:
        job_description = _fallback_job_description(lines)

    requirements = extract_nofluff_section(
        lines,
        [
            "obowiązkowe", "must have", "wymagania", "requirements",
        ],
        [
            "mile widziane", "nice to have", "benefity", "benefits",
            "o firmie", "about the company", "szczegóły oferty",
            "szczegoly oferty",
        ],
    )

    about_company = extract_nofluff_section(
        lines,
        [
            "o firmie", "about the company", "about us",
        ],
        [
            "benefity", "benefits", "aplikuj", "apply",
            "podobne oferty", "similar jobs",
        ],
    )

    tech_stack = extract_nofluff_technologies(lines)
    if not tech_stack:
        tech_stack = requirements

    expires_text = None
    expires_at = None

    for pattern in (
        r"oferta\s+ważna\s+do:\s*(\d{1,2}[.]\d{1,2}[.]\d{4})",
        r"oferta\s+wazna\s+do:\s*(\d{1,2}[.]\d{1,2}[.]\d{4})",
        r"valid\s+until:\s*(\d{1,2}[.]\d{1,2}[.]\d{4})",
    ):
        match = re.search(pattern, body_text, re.IGNORECASE)
        if not match:
            continue

        parsed = _parse_datetime_value(match.group(1))
        if parsed:
            expires_at = parsed
            expires_text = match.group(0)
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
        "tech_stack": tech_stack,
        "office_location": location,
        "about_company": about_company,
        "expires_text": expires_text,
        "expires_at": expires_at,
    }
