# Job offers scraper

Automatyczny scraper ofert pracy z polskich portali rekrutacyjnych. Pobiera ogłoszenia z **Just Join IT**, **Pracuj.pl** i **No Fluff Jobs** według zdefiniowanych słów kluczowych i przechowuje je w bazie MySQL. Wyniki są dostępne przez wbudowany panel webowy.

## Funkcje

- Scrapowanie list ofert z trzech portali: Just Join IT, Pracuj.pl, No Fluff Jobs
- Pobieranie szczegółów ofert (opis stanowiska, stack technologiczny, lokalizacja biura, opis firmy)
- Filtrowanie po słowach kluczowych i ignorowanie niepożądanych tytułów
- Automatyczne oznaczanie nieaktywnych ofert (po przekroczeniu progu nieobecności)
- Cooldown dla portali wykrywających automaty (np. No Fluff Jobs)
- Persystentny stan między restartami kontenera (volume Docker)
- Panel webowy PHP do przeglądania zebranych ofert

## Architektura

```
job_offers_scraper/
├── docker-compose.yml       # Orkiestracja usług
├── .env                     # Zmienne środowiskowe (nie commituj!)
├── .env.example             # Szablon zmiennych środowiskowych
│
├── scraper/                 # Serwis scrapera (Python + Playwright)
│   ├── scraper.py           # Główna pętla scrapera
│   ├── justjoin.py          # Scraper Just Join IT
│   ├── pracuj.py            # Scraper Pracuj.pl
│   ├── nofluffjobs.py       # Scraper No Fluff Jobs
│   ├── database.py          # Warstwa dostępu do MySQL
│   ├── filters.py           # Filtrowanie słów kluczowych
│   ├── config.py            # Konfiguracja (interwały, opóźnienia, URL-e)
│   ├── utils.py             # Narzędzia pomocnicze
│   ├── keywords.txt         # Słowa kluczowe do wyszukiwania
│   ├── ignored_keywords.txt # Tytuły do ignorowania
│   └── Dockerfile
│
├── web/                     # Panel webowy (PHP + Apache)
│   ├── index.php            # Interfejs przeglądania ofert
│   ├── style.css
│   └── Dockerfile
│
└── mysql/
    └── init.sql             # Schemat bazy danych (auto-inicjalizacja)
```

## Wymagania

- [Docker](https://docs.docker.com/get-docker/) z pluginem Compose

## Szybki start

### 1. Sklonuj repozytorium

```bash
git clone <url-repo>
cd job_offers_scraper
```

### 2. Skonfiguruj zmienne środowiskowe

```bash
cp .env.example .env
```

Uzupełnij plik `.env`:

```env
MYSQL_ROOT_PASSWORD=silne_haslo_root
MYSQL_DATABASE=jobs
MYSQL_USER=jobs_user
MYSQL_PASSWORD=silne_haslo_user
DB_HOST=mysql
DB_PORT=3306
```

### 3. Skonfiguruj słowa kluczowe

Edytuj `scraper/keywords.txt` — jedno słowo lub fraza na linię:

```
devops
cloud engineer
devsecops
```

Opcjonalnie edytuj `scraper/ignored_keywords.txt` — oferty z tymi słowami w tytule zostaną pominięte:

```
senior
lead
manager
```

> Linie zaczynające się od `#` są traktowane jako komentarze.

### 4. Uruchom

```bash
docker compose up -d
```

Panel webowy będzie dostępny pod adresem: **http://localhost:8090**

## Użycie

### Uruchomienie scrapera w trybie ciągłym (cykliczne skanowanie)

Scraper uruchamia się w pętli i automatycznie powtarza skanowanie co `SCRAPE_INTERVAL` sekund (domyślnie co godzinę):

```bash
docker compose up -d scraper
```

> Jeśli baza danych i pozostałe usługi już działają, wystarczy uruchomić sam kontener scrapera. W przeciwnym razie użyj `docker compose up -d` aby uruchomić wszystkie serwisy naraz.

### Uruchomienie jednorazowego przebiegu

```bash
docker compose run --rm scraper python scraper.py --once
```

### Ponowne pobranie brakujących szczegółów

```bash
docker compose run --rm scraper python scraper.py --retry-details
```

### Podgląd logów scrapera

```bash
docker compose logs -f scraper
```

### Dostęp do MySQL przez phpMyAdmin

```bash
docker run -d \
  --name jobs-phpmyadmin \
  --restart unless-stopped \
  --network job_offers_scraper_jobs-network \
  -p 8081:80 \
  -e PMA_HOST=mysql \
  -e PMA_PORT=3306 \
  -e PMA_ARBITRARY=0 \
  phpmyadmin:latest
```

phpMyAdmin będzie dostępny pod: **http://localhost:8081**

### Bezpośredni dostęp do MySQL

```bash
docker compose exec mysql mysql -uroot -p
```

## Konfiguracja zaawansowana

Parametry można nadpisać przez zmienne środowiskowe w `.env` lub `docker-compose.yml`:

| Zmienna | Domyślna | Opis |
|---|---|---|
| `SCRAPE_INTERVAL` | `3600` | Przerwa między pełnymi przebiegami (sekundy) |
| `SCRAPER_MIN_DELAY` | `20` | Minimalne opóźnienie między wyszukiwaniami (s) |
| `SCRAPER_MAX_DELAY` | `40` | Maksymalne opóźnienie między wyszukiwaniami (s) |
| `DETAIL_MIN_DELAY` | `90` | Minimalne opóźnienie między stronami szczegółowymi (s) |
| `DETAIL_MAX_DELAY` | `150` | Maksymalne opóźnienie między stronami szczegółowymi (s) |
| `MAX_DETAILS_PER_RUN` | `100` | Maks. liczba szczegółów pobieranych w jednym przebiegu |
| `NOFLUFFJOBS_BLOCK_COOLDOWN` | `21600` | Czas cooldownu po wykryciu blokady NFJ (s = 6h) |
| `MISSED_THRESHOLD` | `4` | Ile przebiegów bez oferty, żeby oznaczyć ją jako nieaktywną |

### Włączanie/wyłączanie portali

W pliku `scraper/scraper.py` na początku pliku:

```python
RUN_JUSTJOIN = True
RUN_JUSTJOIN_DETAILS = True

RUN_PRACUJ = True
RUN_PRACUJ_DETAILS = True

RUN_NOFLUFFJOBS = True
RUN_NOFLUFFJOBS_DETAILS = True
```

## Schemat bazy danych

Tabela `jobs` (tworzona automatycznie przez `mysql/init.sql`):

| Kolumna | Opis |
|---|---|
| `portal` | Źródło oferty (`justjoin`, `pracuj`, `nofluffjobs`) |
| `source_id` | Unikalny identyfikator oferty na portalu |
| `title` | Tytuł stanowiska |
| `company` | Nazwa firmy |
| `location` | Lokalizacja |
| `work_mode` | Tryb pracy (zdalna, hybrydowa, stacjonarna) |
| `work_type` | Rodzaj pracy (pełny etat itp.) |
| `experience_level` | Poziom doświadczenia |
| `contract_type` | Rodzaj umowy |
| `salary` | Widełki wynagrodzenia |
| `job_description` | Opis stanowiska (szczegóły) |
| `tech_stack` | Stack technologiczny (szczegóły) |
| `url` | Link do oferty |
| `keyword` | Słowo kluczowe, przez które znaleziono ofertę |
| `published_at` | Data publikacji |
| `expires_at` | Data wygaśnięcia |
| `first_seen_at` | Kiedy po raz pierwszy znaleziona |
| `last_seen_at` | Kiedy ostatnio widziana w wynikach |
| `is_active` | Czy oferta jest aktywna |
| `missed_count` | Liczba przebiegów, w których nie pojawiła się na liście |
| `details_complete` | Czy szczegóły zostały pobrane |

## Stack technologiczny

- **Python 3** + [Playwright](https://playwright.dev/python/) — scrapowanie JavaScript-heavy portali
- **BeautifulSoup4** + **lxml** — parsowanie HTML
- **MySQL 8.4** — baza danych
- **PHP 8 + Apache** — panel webowy
- **Docker Compose** — orkiestracja
