# CLAUDE.md

## Project Overview

Multi-shop Lithuanian book price scraper built with Scrapy. Stores data in PostgreSQL. First shop: vaga.lt.

## Key Commands

```bash
uv sync --all-extras                          # Install deps
docker compose up -d postgres postgres-test   # Start DBs
PYTHONPATH=. uv run alembic upgrade head      # Run migrations
uv run scrapy crawl vaga_scan                 # Full product scan
uv run scrapy crawl vaga_prices               # Price-only scan
uv run pytest -v                              # Run tests
uv run ruff check book_scraper/ tests/        # Lint
uv run ruff format book_scraper/ tests/       # Format
uv run mypy book_scraper/                     # Type check
```

## Architecture

- **Framework:** Scrapy with asyncio reactor
- **DB:** PostgreSQL via SQLAlchemy 2.0, migrations via Alembic
- **Config:** TOML files in `config/` (global defaults + per-shop overrides)
- **Package manager:** uv

### Pipeline Phases

1. **Discover** (`vaga_discover`) - find URLs from sitemap
2. **Detect changes** - not yet implemented
3. **Full scan** (`vaga_scan`) - scrape full product pages
4. **Price scan** (`vaga_prices`) - lightweight price re-scrape from category pages
5. **Match** - not yet implemented (link listings to canonical books)

### Key Design Decisions

- Parsers live in `spiders/vaga/parsers.py` separate from spiders so they can be tested without Scrapy
- `listings` table stores full product metadata (title, author, ISBN, publisher, year, pages, etc.)
- `prices` table is append-only (one row per scrape per listing)
- `books` table is for canonical records (shop-independent) — populated by match phase
- Per-shop settings in `config/shops/<shop>.toml`, loaded at spider import time

### Database

- Main DB: `postgresql://postgres:postgres@localhost:5432/book_scraper`
- Test DB: `postgresql://postgres:postgres@localhost:5433/book_scraper_test`
- Both run in Docker via `docker-compose.yml`
- Alembic needs `PYTHONPATH=.` to find models

### Adding a New Shop

1. Create `config/shops/<shop>.toml` with shop settings
2. Create `book_scraper/spiders/<shop>/` directory
3. Add `parsers.py` with parsing functions + test fixtures
4. Add `discover.py`, `scan.py`, `prices.py` spiders
5. Test parsers against saved HTML fixtures

## Code Conventions

- Python 3.12+, strict mypy
- Ruff for linting and formatting (line-length 88)
- Commit directly on main (personal project, no branches)
- Tests use real PostgreSQL (Docker on port 5433), not mocks
- Scrapy items use `scrapy.Field()`, validated in `ValidationPipeline` with Pydantic-style checks

## Specs and Plans

- Design spec: `docs/superpowers/specs/2026-04-05-book-scraper-design.md`
- Implementation plan: `docs/superpowers/plans/2026-04-05-book-scraper-plan.md`
- vaga.lt strategy: Notion page "vaga.lt scraping strategy"
- Architecture: Notion page "Scraping Strategy & Architecture"
