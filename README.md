# Book Price Scraper

Multi-shop book price comparison system for Lithuanian e-shops. Scrapes book data and prices, stores in PostgreSQL, tracks price changes over time.

## Architecture

Scrapy-based project with per-shop spider directories, shared item pipelines for PostgreSQL storage, and TOML config files for per-shop settings.

### Pipeline Phases

| Phase | Spider | What it does |
|-------|--------|-------------|
| 1. Discover | `vaga_discover` | Find all product URLs from sitemap |
| 2. Detect changes | (not yet implemented) | Compare discovered URLs vs known listings |
| 3. Full scan | `vaga_scan` | Scrape full product data (title, author, ISBN, price, metadata) |
| 4. Price scan | `vaga_prices` | Lightweight price-only re-scrape via category pages |
| Match | (not yet implemented) | Link listings to canonical books |

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
# Discover all URLs from sitemap
uv run scrapy crawl vaga_discover

# Full product scan (~3 hours for all 20K pages)
uv run scrapy crawl vaga_scan

# Price-only scan (~3 minutes for all prices)
uv run scrapy crawl vaga_prices

# Limit items for testing
uv run scrapy crawl vaga_scan -s CLOSESPIDER_ITEMCOUNT=10
```

### Run Tests

```bash
# Start test database
docker compose up -d postgres-test

# Run all tests
uv run pytest -v
```

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
        models.py               # SQLAlchemy ORM: Book, Shop, Listing, Price, Category
        repo.py                 # CRUD operations
        session.py              # DB engine + session factory
    spiders/
        vaga/
            discover.py         # Phase 1: sitemap spider
            scan.py             # Phase 3: full product data
            prices.py           # Phase 4: price-only re-scrape
            parsers.py          # HTML/JSON parsing (testable without Scrapy)

tests/
    fixtures/                   # Saved HTML/XML for parser tests
    test_vaga_parsers.py        # Parser tests
    test_db_repo.py             # DB repository tests
    test_items.py               # Item validation tests

_prototypes/                    # Old prototype scripts (reference only)
```

## Database

PostgreSQL with 6 tables:

- **books** - Canonical book records (shop-independent)
- **shops** - Registered shops (vaga, knygos, etc.)
- **listings** - Book x shop link with full metadata
- **prices** - Append-only price history
- **categories** - Hierarchical category tree
- **book_categories** - Many-to-many book-category link

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
