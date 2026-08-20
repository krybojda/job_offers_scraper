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
    range_pattern = re.compile(
        r"\d[\d\s.,]*\s*[–-]\s*\d[\d\s.,]*\s*"
        r"(?:PLN|EUR|USD|GBP|CHF).*",
        re.IGNORECASE,
    )
    single_pattern = re.compile(
        r"\d[\d\s.,]*\s*(?:PLN|EUR|USD|GBP|CHF).*",
        re.IGNORECASE,
    )

    for line in lines:
        if range_pattern.search(line):
            return line

    for line in lines:
        if single_pattern.search(line):
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
                "bez pracy zdalnej",
                "praca w biurze",
                "praca stacjonarna",
                "on-site",
                "onsite",
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
    text = " ".join(lines)
    if title:
        text += " " + title

    normalized = text.lower()

    if (
        "pełny etat" in normalized
        or "full-time" in normalized
        or "full time" in normalized
    ):
        return "Full-time"

    if (
        "część etatu" in normalized
        or "part-time" in normalized
        or "part time" in normalized
    ):
        return "Part-time"

    if "freelance" in normalized:
        return "Freelance"

    return None


def find_experience_level(title, lines):
    text = " ".join(lines)

    explicit = re.search(
        r"(?:poziom|level|experience level)\s*:?\s*"
        r"(junior|mid|middle|regular|senior|expert|lead)",
        text,
        re.IGNORECASE,
    )
    if explicit:
        value = explicit.group(1).lower()
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

    url = urljoin(NOF_FLUFF_BASE_URL, href)
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
    return f"{NO_FLUFF_BASE_URL}/pl?criteria={encoded_keyword}"


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
        "docker": "Docker", "kubernetes": "Kubernetes",
        "terraform": "Terraform", "ansible": "Ansible",
        "jenkins": "Jenkins", "gitlab": "GitLab", "github": "GitHub",
        "python": "Python", "java": "Java", "javascript": "JavaScript",
        "typescript": "TypeScript", "node.js": "Node.js", "go": "Go",
        "c#": "C#", ".net": ".NET", "linux": "Linux", "sql": "SQL",
        "postgresql": "PostgreSQL", "mysql": "MySQL", "oracle": "Oracle",
        "grafana": "Grafana", "prometheus": "Prometheus", "helm": "Helm",
        "argocd": "ArgoCD", "git": "Git", "ci/cd": "CI/CD",
        "devops": "DevOps", "bash": "Bash", "powershell": "PowerShell",
        "kotlin": "Kotlin", "ruby": "Ruby", "php": "PHP", "react": "React",
        "angular": "Angular", "vue": "Vue", "spring": "Spring",
        "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
        "redis": "Redis", "mongodb": "MongoDB", "elasticsearch": "Elasticsearch",
        "kafka": "Kafka", "rabbitmq": "RabbitMQ", "openstack": "OpenStack",
        "cloud": "Cloud", "backend": "Backend", "frontend": "Frontend",
        "data": "Data", "ai/ml": "AI/ML", "security": "Security",
        "testing": "Testing", "fullstack": "Fullstack", "mobile": "Mobile",
        "erp": "ERP",
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


def _parse_json_date(value):
    if not value:
        return None

    text = str(value).strip()

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def _collect_json_ld_dates(page):
    date_posted = None
    valid_through = None

    try:
        scripts = page.locator(
            "script[type='application/ld+json']"
        ).all_inner_texts()

        for script_text in scripts:
            try:
                data = json.loads(script_text)
            except Exception:
                continue

            stack = data if isinstance(data, list) else [data]

            while stack:
                item = stack.pop()
                if not isinstance(item, dict):
                    continue

                if item.get("datePosted") and not date_posted:
                    date_posted = _parse_json_date(item["datePosted"])

                if item.get("validThrough") and not valid_through:
                    valid_through = _parse_json_date(item["validThrough"])

                graph = item.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)

                for key in ("item", "mainEntity", "mainEntityOfPage"):
                    nested = item.get(key)
                    if isinstance(nested, dict):
                        stack.append(nested)

    except Exception:
        pass

    return date_posted, valid_through


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

    location = find_location(lines) or job.get("location")
    work_mode = find_work_mode(lines) or job.get("work_mode")
    work_type = find_work_type(lines, title) or job.get("work_type")
    experience_level = (
        find_experience_level(title, lines)
        or job.get("experience_level")
    )
    contract_type = (
        find_contract_type(lines)
        or job.get("contract_type")
    )
    salary = find_salary(lines) or job.get("salary")

    published_at, expires_at = _collect_json_ld_dates(page)

    job_description = extract_nofluff_section(
        lines,
        [
            "opis stanowiska", "job description", "description",
            "zakres obowiązków", "responsibilities",
        ],
        [
            "obowiązkowe", "must have", "wymagania", "requirements",
            "mile widziane", "nice to have", "benefity", "benefits",
            "o firmie", "about the company",
        ],
    )

    requirements = extract_nofluff_section(
        lines,
        [
            "obowiązkowe", "must have", "wymagania", "requirements",
        ],
        [
            "mile widziane", "nice to have", "benefity", "benefits",
            "o firmie", "about the company",
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
    if expires_at:
        expires_text = expires_at.strftime("%Y-%m-%d %H:%M:%S")

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


NO_FLUFF_BASE_URL = NOFLUFFJOBS_BASE_URL
