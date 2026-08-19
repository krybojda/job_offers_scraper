import re

from config import (
    KEYWORDS_FILE,
    IGNORED_KEYWORDS_FILE,
)


def load_keywords():
    """
    Wczytuje słowa wyszukiwania.
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
            f"BŁĄD: Nie znaleziono pliku "
            f"{KEYWORDS_FILE}"
        )

        raise


def load_ignored_keywords():
    """
    Wczytuje ignorowane słowa i frazy.

    Brak pliku = brak ignorowanych słów.
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


def is_ignored_job(title, ignored_keywords):
    """
    Sprawdza, czy tytuł zawiera ignorowane
    słowo albo frazę.

    Pojedyncze słowo:
        lead -> "Team Lead"

    Nie pasuje do:
        Leadership

    Fraza:
        team lead -> "DevOps Team Lead"
    """

    if not title or not ignored_keywords:
        return False

    title_lower = title.lower().strip()

    for keyword in ignored_keywords:

        keyword = keyword.strip().lower()

        if not keyword:
            continue

        # Fraza zawierająca spację.
        if " " in keyword:

            if keyword in title_lower:
                return True

            continue

        # Pojedyncze słowo.
        pattern = rf"\b{re.escape(keyword)}\b"

        if re.search(
            pattern,
            title_lower,
        ):
            return True

    return False