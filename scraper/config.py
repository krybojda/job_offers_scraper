import os


# =========================================================
# OGÓLNA KONFIGURACJA
# =========================================================

SCRAPE_INTERVAL = int(
    os.getenv("SCRAPE_INTERVAL", "3600")
)

# Przerwa między kolejnymi wyszukiwaniami.
MIN_DELAY = int(
    os.getenv("SCRAPER_MIN_DELAY", "20")
)

MAX_DELAY = int(
    os.getenv("SCRAPER_MAX_DELAY", "40")
)

# Przerwa między stronami szczegółowymi.
DETAIL_MIN_DELAY = int(
    os.getenv("DETAIL_MIN_DELAY", "30")
)

DETAIL_MAX_DELAY = int(
    os.getenv("DETAIL_MAX_DELAY", "60")
)

# Maksymalna liczba szczegółów pobieranych
# w jednym przebiegu.
MAX_DETAILS_PER_RUN = int(
    os.getenv("MAX_DETAILS_PER_RUN", "20")
)

# Po ilu pełnych poprawnych przebiegach
# oferta staje się nieaktywna.
MISSED_THRESHOLD = int(
    os.getenv("MISSED_THRESHOLD", "3")
)


# =========================================================
# JUST JOIN IT
# =========================================================

JUSTJOIN_BASE_URL = (
    "https://justjoin.it"
)


# =========================================================
# PRACUJ.PL
# =========================================================

PRACUJ_BASE_URL = (
    "https://www.pracuj.pl"
)

# Na tym etapie CELOWO tylko jedna strona.
#
# Pracuj obecnie zwraca 403 przy próbie przejścia
# do kolejnej strony z naszego automatycznego klienta.
#
# Gdy dopracujemy bezpieczną paginację, zmienimy na >1.
PRACUJ_MAX_PAGES = 1


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

KEYWORDS_FILE = (
    "keywords.txt"
)

IGNORED_KEYWORDS_FILE = (
    "ignored_keywords.txt"
)