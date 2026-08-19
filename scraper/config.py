import os


# =========================================================
# OGÓLNA KONFIGURACJA
# =========================================================

SCRAPE_INTERVAL = int(
    os.getenv("SCRAPE_INTERVAL", "3600")
)

MIN_DELAY = int(
    os.getenv("SCRAPER_MIN_DELAY", "20")
)

MAX_DELAY = int(
    os.getenv("SCRAPER_MAX_DELAY", "40")
)


# =========================================================
# JUST JOIN IT
# =========================================================

JUSTJOIN_BASE_URL = "https://justjoin.it"


# =========================================================
# PRZEGLĄDARKA
# =========================================================

HEADLESS = True

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


# =========================================================
# PLIKI
# =========================================================

KEYWORDS_FILE = "keywords.txt"

IGNORED_KEYWORDS_FILE = "ignored_keywords.txt"