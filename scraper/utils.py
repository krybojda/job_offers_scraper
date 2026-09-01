import hashlib
import re


def clean_text(value):
    """
    Normalizuje bia?e znaki.
    """

    if not value:
        return None

    value = " ".join(
        value.split()
    )

    return (
        value
        if value
        else None
    )


def normalize_url(url):
    """
    Normalizuje URL oferty, usuwaj?c parametry ?ledz?ce, kotwice
    oraz warianty j?zykowe/lokalizacyjne, aby ta sama oferta
    mia?a zawsze identyczny identyfikator ?r?d?owy (source_id).
    """
    if not url:
        return ""

    url_clean = url.strip().split("?")[0].split("#")[0].rstrip("/")

    # 1. Pracuj.pl: oferta zawiera unikalny identyfikator numeryczny ,oferta,1234567
    # Multi-lokalizacyjne oferty maj? r??ne nazwy miast w ?cie?ce, ale ten sam ID oferty.
    if "pracuj.pl" in url_clean.lower():
        match = re.search(r",oferta,(\d+)", url_clean, re.IGNORECASE)
        if match:
            return f"https://www.pracuj.pl/praca/,oferta,{match.group(1)}"

    # 2. NoFluffJobs: usu? prefiksy j?zykowe (/pl/, /en/) i ujednolic /job1/ do /job/
    if "nofluffjobs.com" in url_clean.lower():
        url_clean = re.sub(
            r"https?://(?:www\.)?nofluffjobs\.com/(?:pl|en|cz|hu|ua)/",
            "https://nofluffjobs.com/",
            url_clean,
            flags=re.IGNORECASE,
        )
        url_clean = re.sub(
            r"https?://(?:www\.)?nofluffjobs\.com/",
            "https://nofluffjobs.com/",
            url_clean,
            flags=re.IGNORECASE,
        )
        url_clean = re.sub(r"/job1/", "/job/", url_clean, flags=re.IGNORECASE)
        return url_clean.lower()

    # 3. JustJoin.it: ujednolic subdomen?, prefiksy j?zykowe oraz warianty ?cie?ek
    if (
        "justjoin.it" in url_clean.lower()
        or "/job-offer/" in url_clean.lower()
        or "/offers/" in url_clean.lower()
        or "/job-offers/" in url_clean.lower()
    ):
        url_clean = re.sub(
            r"https?://(?:www\.)?justjoin\.it/(?:pl|en)/",
            "https://justjoin.it/",
            url_clean,
            flags=re.IGNORECASE,
        )
        url_clean = re.sub(
            r"https?://(?:www\.)?justjoin\.it/",
            "https://justjoin.it/",
            url_clean,
            flags=re.IGNORECASE,
        )
        if not url_clean.startswith("http"):
            url_clean = "https://justjoin.it/" + url_clean.lstrip("/")
        url_clean = re.sub(r"/(?:pl|en)/", "/", url_clean, flags=re.IGNORECASE)
        url_clean = re.sub(r"/(?:job-offers|offers)/", "/job-offer/", url_clean, flags=re.IGNORECASE)
        return url_clean.lower()

    return url_clean.lower()


def generate_source_id(url):
    """
    Tworzy stabilny identyfikator oferty na podstawie znormalizowanego URL.
    """
    normalized_url = normalize_url(url)
    return hashlib.sha256(
        normalized_url.encode("utf-8")
    ).hexdigest()
