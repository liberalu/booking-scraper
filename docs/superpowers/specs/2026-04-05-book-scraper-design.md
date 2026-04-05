# Book Price Scraper — Design Spec

**Date:** 2026-04-05
**Goal:** Build a multi-shop book price comparison system for Lithuanian e-shops. Track book prices over time, compare across shops, detect discounts.

---

## Project Setup

This is a **new project**. The existing prototype scripts are moved to `_prototypes/` to keep the root clean. They serve as reference during development.

```
_prototypes/              # existing files moved here
    scrape_book.py
    scrape_book_curl.py
    scrape_book_fast.py
    scrape_prices.py
    scrape_sitemap.py
    scrape_autocomplete.py
    scrape_autocomplete_fast.py
    dump_html.py
    dump_html2.py
    test_cookie_reuse.py
    test_curl_cffi.py
    test_curl_cffi2.py
    test_parallel_playwright.py
    deploy.sh
    Dockerfile
    book_urls.txt
    page_dump.html
    page_dump2.html
    page_screenshot.png
    prices.csv
    prices_auto.csv
```

### Framework: Scrapy

The project uses **Scrapy** as its core scraping framework. Scrapy provides built-in concurrency, rate limiting, retry with backoff, request deduplication, and item pipelines for storage.

**Core dependencies:**
- **Scrapy** — framework (spiders, pipelines, middleware, scheduling)
- **scrapy-impersonate** — curl_cffi integration for TLS fingerprinting (per spider, as needed)
- **scrapy-playwright** — Playwright integration for JS-rendered pages (per spider, as needed)
- **Pydantic** — data validation in item pipelines

**Database layer:**
- **SQLAlchemy 2.0** — ORM with asyncpg driver
- **Alembic** — schema migrations
- **PostgreSQL** — single database for all data

**Project tooling:**
- **Python 3.12+**
- **uv** — package manager

All spiders use the asyncio reactor (`twisted.internet.asyncioreactor.AsyncioSelectorReactor`) as required by both scrapy-impersonate and scrapy-playwright.

---

## Pipeline Phases

The system operates in 4 phases. Each phase maps to one or more Scrapy spiders per shop.

| Phase | What it does | Frequency |
|-------|-------------|-----------|
| 1. Discover | Find all product URLs from a shop (sitemap, crawl, API — pluggable per shop) | Once initially, then periodically |
| 2. Detect changes | Compare discovered URLs against known listings — flag new and removed | After each discovery run |
| 3. Full scan | Scrape full product data (title, author, ISBN, price, metadata) for new/unscanned listings | On new listings or initial bulk import |
| 4. Price scan | Lightweight re-scrape: price + stock status only for known listings | Weekly/daily |

Additional operations:
- `match` — run book matching on unmatched listings
- `status` — show stats (listings count, matched/unmatched, prices collected)

Phases 1-3 are heavy and run infrequently. Phase 4 is the steady-state loop.

### First shop: vaga.lt

**vaga.lt** is the first target — a Lithuanian bookstore/publisher with no bot protection (plain Apache/OpenCart). ~20K URLs, JSON-LD structured data, category pages with pagination. Full pipeline is built and validated against this shop first, then extended to harder targets (knygos.lt, etc.).

Key vaga.lt characteristics:
- **No Cloudflare** — plain HTTP requests work, default Scrapy handler is sufficient
- **Sitemap:** `vaga.lt/sitemap.xml` (~20K URLs, single file, no newlines — needs XML parser)
- **Category pages:** `vaga.lt/knygos?limit=100&page={N}` — bulk prices (~5 min for all)
- **Product pages:** JSON-LD with `@type: Book` + HTML property spans (ISBN, publisher, year, pages)
- **Note:** JSON-LD contains control characters — must clean before `json.loads()`
- **Note:** HTML class has typo: `propery-title` (not `property-title`)

### How phases map to Scrapy

- **Phases 1, 3, 4** → Scrapy spiders (one or more per shop per phase)
- **Phase 2** → Python script/command that queries the DB (no scraping needed)
- **Match** → Python script/command that queries the DB (no scraping needed)

Spiders are run via `scrapy crawl <spider_name>`. Non-scraping commands use a simple CLI (argparse or Scrapy's custom commands).

---

## Module Structure

Follows standard Scrapy project conventions. Spiders are grouped by shop in subdirectories under `spiders/`. Shared logic lives at the project root level.

```
scrapy.cfg                          # Scrapy deploy config
book_scraper/
    __init__.py
    settings.py                     # Scrapy settings: reactor, pipelines, middleware
    items.py                        # Scrapy items: ListingItem, PriceItem
    middlewares.py                  # Custom spider/downloader middlewares
    pipelines.py                    # Shared pipelines: validation, PostgreSQL storage

    spiders/
        __init__.py
        knygos/
            __init__.py
            discover.py             # Phase 1: sitemap spider (Playwright)
            scan.py                 # Phase 3: full product spider (autocomplete API / curl_cffi)
            prices.py               # Phase 4: price-only spider (autocomplete API)
        pegasas/
            __init__.py
            discover.py             # Phase 1
            scan.py                 # Phase 3
            prices.py               # Phase 4

    db/
        __init__.py
        models.py                   # SQLAlchemy ORM: Book, Shop, Listing, Price, Category
        repo.py                     # CRUD operations
        session.py                  # Engine + session factory

    matching/
        __init__.py
        matcher.py                  # Orchestrates the matching chain
        isbn.py                     # ISBN exact match
        fuzzy.py                    # Title + author similarity scoring

    commands/
        __init__.py
        changes.py                  # Phase 2: diff discovered vs known URLs
        match.py                    # Run book matching
        status.py                   # Show stats

tests/
    fixtures/                       # Saved HTML/JSON for parser tests
    test_parsers.py
```

### Spider naming convention

Spiders live in `spiders/<shop>/` directories. Spider names use `<shop>_<phase>` — e.g. `knygos_discover`, `pegasas_prices`. Run with `scrapy crawl knygos_discover`.

### Per-spider HTTP strategy

Each spider sets its own HTTP backend via `custom_settings`:

- **Easy shops:** default Scrapy HTTP handler
- **TLS fingerprinting:** scrapy-impersonate (curl_cffi) via `DOWNLOAD_HANDLERS`
- **JS-rendered pages:** scrapy-playwright via `DOWNLOAD_HANDLERS`
- **JSON APIs:** default HTTP handler with `response.json()`

### Shared pipelines

All spiders share the same item pipelines defined in `pipelines.py`:

1. **ValidationPipeline** — validate items with Pydantic models
2. **PostgresPipeline** — upsert listings, insert prices into PostgreSQL

---

## Data Model

PostgreSQL-only. ClickHouse can be added later when the prices table grows past ~100M rows.

### books

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| isbn | text, nullable | unique when present |
| title | text | |
| slug | text, unique | URL-friendly identifier |
| author | text, nullable | |
| publisher | text, nullable | |
| year | int, nullable | publication year |
| pages | int, nullable | page count |
| language | text | default 'lt' |
| format | text, nullable | hardcover, paperback, ebook, audiobook |
| description | text, nullable | blurb/summary |
| labels | text[] | flat tags, PostgreSQL array |
| created_at | timestamptz | |
| updated_at | timestamptz | |

### categories

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| name | text | display name, e.g. "Grožinė literatūra" |
| slug | text, unique | e.g. "grozine-literatura" |
| parent_id | FK → categories, nullable | tree structure |

### book_categories

| Column | Type | Notes |
|--------|------|-------|
| book_id | FK → books | |
| category_id | FK → categories | |
| | composite PK | (book_id, category_id) |

### shops

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| name | text, unique | e.g. "knygos", "pegasas" |
| base_url | text | |

### listings

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| book_id | FK → books, nullable | null = not yet matched |
| shop_id | FK → shops | |
| url | text | unique per shop |
| shop_title | text | raw title from shop |
| shop_author | text, nullable | raw author from shop |
| isbn_from_shop | text, nullable | |
| image_url | text, nullable | |
| match_status | enum | unmatched, matched, uncertain |
| match_method | enum, nullable | isbn, fuzzy, manual |
| is_active | bool | false = removed from shop |
| first_seen_at | timestamptz | |
| last_seen_at | timestamptz | |

### prices

| Column | Type | Notes |
|--------|------|-------|
| id | bigserial PK | |
| listing_id | FK → listings | |
| price | decimal | |
| price_original | decimal, nullable | before discount |
| in_stock | bool | |
| scraped_at | timestamptz | |
| discount_pct | generated | computed from price/price_original |

Append-only table. Partitionable by month when needed.

---

## Book Matching

Matching links a shop `Listing` to a canonical `Book`. Runs as a separate command (`match`).

Priority chain — first match wins:

1. **ISBN exact match** — listing has ISBN → find book with same ISBN. ~100% reliable.
2. **Fuzzy title + author** — scoring formula: `title_similarity × 0.6 + author_similarity × 0.3 + (publisher+year) × 0.1`
   - Score > 0.9 → auto-match (`match_status = matched`)
   - Score 0.7–0.9 → `match_status = uncertain` (review later)
   - Score < 0.7 → no match
3. **No match** → create new `Book` from listing data.

Matching is idempotent — re-running skips already-matched listings.

---

## Tooling & Infrastructure

### Code quality
- **Ruff** — linter + formatter
- **mypy** — strict type checking
- **pytest** — tests

### Testing strategy
- **Parsers:** tested against saved HTML/JSON fixtures (no network calls)
- **DB repo:** tested against real PostgreSQL (local or test container)
- **Spiders:** integration tested manually, not unit tested

### CLI
- Scrapy spiders: `scrapy crawl <spider_name>`
- Non-scraping commands: Scrapy custom commands or argparse

### Deployment (future)
- Docker + Hetzner VPS (reuse existing deploy.sh pattern)
- For PoC: run from laptop
