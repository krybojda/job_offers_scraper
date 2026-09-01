import re

from config import (
    KEYWORDS_FILE,
    IGNORED_KEYWORDS_FILE,
)


def load_keywords():
    """
    Wczytuje s?owa wyszukiwania.
    """

    try:

        with open(
            KEYWORDS_FILE,
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
            f"B??D: Nie znaleziono pliku "
            f"{KEYWORDS_FILE}"
        )

        raise


def load_ignored_keywords():
    """
    Wczytuje ignorowane s?owa i frazy.

    Brak pliku = brak ignorowanych s??w.
    """

    try:

        with open(
            IGNORED_KEYWORDS_FILE,
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


def _matches_keyword(text, keyword):
    """
    Sprawdza, czy podany tekst zawiera ignorowane s?owo, fraz? lub jego popularny synonim.
    """
    if not text or not keyword:
        return False

    text_lower = text.lower().strip()
    kw = keyword.lower().strip()

    if not kw or kw.startswith("#"):
        return False

    # Fraza zawieraj?ca spacj? (dopasowanie podci?gu)
    if " " in kw:
        return kw in text_lower

    # Pojedyncze s?owo - dopasowanie z granic? s?owa \b
    pattern = rf"\b{re.escape(kw)}\b"
    if re.search(pattern, text_lower):
        return True

    # Obs?uga polskich odpowiednik?w i skr?t?w dla popularnych poziom?w/stanowisk
    if kw == "senior":
        if re.search(r"\b(sr\.?|starszy|starsza|ekspert)\b", text_lower):
            return True
    elif kw == "lead":
        if re.search(r"\b(leader|lider)\b", text_lower):
            return True
    elif kw == "manager":
        if re.search(r"\b(kierownik|mened?er|menedzer)\b", text_lower):
            return True
    elif kw == "director":
        if re.search(r"\b(dyrektor)\b", text_lower):
            return True

    return False


def is_ignored_job(job_or_title, ignored_keywords, experience_level=None):
    """
    Sprawdza, czy oferta powinna by? zignorowana na podstawie
    tytu?u (title) oraz poziomu do?wiadczenia (experience_level).

    Wiele portali (np. Pracuj.pl, NoFluffJobs, JustJoinIT) umieszcza poziom
    stanowiska (np. "Senior", "Starszy specjalista", "Lead") w osobnym polu
    lub badge'u, a nie w samym tytule oferty.

    Przyjmuje s?ownik oferty dict LUB ci?g znak?w tytu?u.
    """
    if not ignored_keywords:
        return False

    if isinstance(job_or_title, dict):
        title = job_or_title.get("title")
        experience_level = job_or_title.get("experience_level") or experience_level
    else:
        title = job_or_title

    if not title and not experience_level:
        return False

    for keyword in ignored_keywords:
        if _matches_keyword(title, keyword):
            return True
        if _matches_keyword(experience_level, keyword):
            return True

    return False
