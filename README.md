# Book Price Scraper

Multi-shop book price comparison system for Lithuanian e-shops. Scrapes book data and prices, stores in PostgreSQL, tracks price changes over time.

## Architecture

Scrapy-based project with per-shop spider directories, shared item pipelines for PostgreSQL storage, and TOML config files for per-shop settings.

### Pipeline Phases

| Phase | Command | What it does |
|-------|---------|-------------|
| Discover (sitemap) | `discover -a shop=vaga -a strategy=sitemap` | Find product URLs from sitemap |
| Discover (categories) | `discover -a shop=vaga -a strategy=categories` | Find URLs + extract current prices |
| Discover (full crawl) | `discover -a shop=vaga -a strategy=full_crawl` | Crawl all internal links (manual) |
| Prices | `prices -a shop=vaga` | Quick price scan from category pages (alias for discover categories) |
| Scan | `scan -a shop=vaga` | Scrape full product data (resumable after crashes) |
| Match | (not yet implemented) | Link listings to canonical books |

Spiders are generic — shop and strategy passed as arguments. No per-shop spider classes needed.

### Supported Shops

| Shop | Status | Protection | Scale |
|------|--------|-----------|-------|
| [vaga.lt](https://vaga.lt) | Active | None | ~20K products |
| [knygos.lt](https://knygos.lt) | Planned | Cloudflare | ~3M products |

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for PostgreSQL)

### Setup

```bash
# Install dependencies
uv sync --all-extras

# Start PostgreSQL
docker compose up -d postgres

# Run migrations
PYTHONPATH=. uv run alembic upgrade head
```

### Run Spiders

```bash
# Discover URLs from sitemap (weekly)
uv run scrapy crawl discover -a shop=vaga -a strategy=sitemap

# Discover URLs + extract prices from category pages (monthly)
uv run scrapy crawl discover -a shop=vaga -a strategy=categories

# Quick price scan from category pages
uv run scrapy crawl prices -a shop=vaga

# Full product scan (resumable — just re-run after crash)
uv run scrapy crawl scan -a shop=vaga

# Quick price scan via category pages
make prices

# Limit items for testing
uv run scrapy crawl scan -a shop=vaga -s CLOSESPIDER_ITEMCOUNT=10
```

### Run Tests

```bash
# Start test database
docker compose up -d postgres-test

# Run all tests
uv run pytest -v

# Unit tests only (no DB required)
uv run pytest tests/unit/ -v

# Integration tests only (requires postgres-test)
uv run pytest tests/integration/ -v

# With coverage report
make coverage

# HTML coverage report (opens in browser)
make coverage-html
```

## Testing Strategy

Tests are split into two directories by what they need to run:

```
tests/
    unit/           # Fast, no external dependencies
    integration/    # Requires PostgreSQL (Docker on port 5433)
    fixtures/       # Saved HTML/XML pages for parser + spider tests
```

**Unit tests** cover pure logic — parsers, config loading, item validation, session factory, spider registry, and spiders. Spider tests use fake Scrapy responses built from the same HTML fixtures, so they verify the full spider→parser→item chain without network or DB.

**Integration tests** hit a real PostgreSQL instance (not mocks). They cover the DB repository layer (listings, prices, discovered URLs, scrape runs) and the `PostgresPipeline` end-to-end.

Scrapy boilerplate (`settings.py`, `middlewares.py`) and framework lifecycle methods (`from_crawler`, `open_spider`, `close_spider`) are marked `# pragma: no cover` — they have no branching logic and are exercised by real spider runs rather than unit tests.

## Project Structure

```
config/
    default.toml                # Global settings (delays, DB URL)
    shops/
        vaga.toml               # Per-shop settings (URLs, concurrency)

book_scraper/
    settings.py                 # Scrapy settings (loads from config/)
    items.py                    # Scrapy items: ListingItem, PriceItem, DiscoveredUrlItem
    pipelines.py                # ValidationPipeline, PostgresPipeline
    config.py                   # TOML config loader
    db/
        models.py               # SQLAlchemy ORM models + enums
        repo.py                 # CRUD operations (listings, prices, discovered URLs, scrape runs)
        session.py              # DB engine + session factory
    spiders/
        discover.py             # Generic discover spider (sitemap/categories/full_crawl)
        scan.py                 # Generic scan spider (resumable)
        registry.py             # Dynamic parser loader
        vaga/
            parsers.py          # vaga.lt HTML/JSON parsing (testable without Scrapy)

tests/
    unit/                       # Pure logic tests (no DB)
    integration/                # Tests that hit PostgreSQL
    fixtures/                   # Saved HTML/XML for parser + spider tests

_prototypes/                    # Old prototype scripts (reference only)
```

## Database

PostgreSQL with 8 tables:

- **books** - Canonical book records (shop-independent)
- **shops** - Registered shops (vaga, knygos, etc.)
- **listings** - Book x shop link with full metadata
- **prices** - Append-only price history
- **categories** - Hierarchical category tree
- **book_categories** - Many-to-many book-category link
- **discovered_urls** - Accumulate-only URL inventory per shop (tracks url_type, fail_count, source)
- **scrape_runs** - Phase/status log for crash detection and resume

### Listings Fields

Each listing stores: title, author, SKU, ISBN, publisher, year, pages, cover type, description, categories, image URL, price, original price, stock status.

## Configuration

Settings are in TOML files under `config/`:

```toml
# config/shops/vaga.toml
[shop]
name = "vaga"
base_url = "https://vaga.lt"

[scraping]
download_delay = 0.5
concurrent_requests_per_domain = 3

[discover.sitemap]
url = "https://vaga.lt/sitemap.xml"
max_age_hours = 168

[discover.categories]
url = "https://vaga.lt/knygos?limit=100&page={page}"
max_age_hours = 672
```

Override at runtime with Scrapy CLI:
```bash
uv run scrapy crawl vaga_scan -s DOWNLOAD_DELAY=0.3
```

## Code Quality

```bash
uv run ruff check book_scraper/ tests/    # Lint
uv run ruff format book_scraper/ tests/   # Format
uv run mypy book_scraper/                 # Type check
```
