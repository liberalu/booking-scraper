# CLAUDE.md

## Project Overview

Multi-shop Lithuanian book price scraper built with Scrapy. Stores data in PostgreSQL. First shop: vaga.lt.

## Key Commands

```bash
uv sync --all-extras                          # Install deps
docker compose up -d postgres postgres-test   # Start DBs
PYTHONPATH=. uv run alembic upgrade head      # Run migrations
uv run scrapy crawl discover -a shop=vaga -a strategy=sitemap      # Discover URLs from sitemap
uv run scrapy crawl discover -a shop=vaga -a strategy=categories   # Discover URLs + extract prices
uv run scrapy crawl discover -a shop=vaga -a strategy=full_crawl   # Discover all internal links
uv run scrapy crawl scan -a shop=vaga                              # Full product scan (resumable)
uv run scrapy crawl scan -a shop=vaga -a rescrape=true             # Re-scrape all known product URLs
uv run pytest -v                              # Run tests
uv run pytest tests/unit/ -v                  # Unit tests only (no DB)
uv run pytest tests/integration/ -v           # Integration tests only
make coverage                                 # Tests with coverage report
uv run ruff check book_scraper/ tests/        # Lint
uv run ruff format book_scraper/ tests/       # Format
uv run mypy book_scraper/                     # Type check
make audit                                    # Check for vulnerable dependencies
make deps                                     # Check for unused/missing dependencies
uv run pre-commit run --all-files             # Run pre-commit hooks
docker compose build dashboard                # Rebuild dashboard image
docker compose up -d dashboard                # Restart dashboard container
uv run pytest tests/integration/test_dashboard_routes.py -v  # Smoke test after deploy
```

## Architecture

- **Framework:** Scrapy with asyncio reactor
- **DB:** PostgreSQL via SQLAlchemy 2.0, migrations via Alembic
- **Dashboard:** FastAPI + Jinja2 + Pico CSS, served via Docker at `http://localhost:8000`
- **Config:** TOML files in `config/` (global defaults + per-shop overrides)
- **Package manager:** uv
- **Deployment:** Everything runs in Docker via `docker-compose.yml`. Rebuild + restart to see changes.

### Pipeline Phases

1. **Discover** (`discover` spider) — find URLs via sitemap, categories, or full crawl. Category discovery also extracts prices.
2. **Scan** (`scan` spider) — scrape full product pages for discovered URLs. Resumable after crashes.
3. **Match** — not yet implemented (link listings to canonical books)

Spiders are generic — shop is passed as argument: `scrapy crawl discover -a shop=vaga -a strategy=sitemap`

### Key Design Decisions

- Generic spiders (`discover`, `scan`) — shop-specific logic lives in `spiders/<shop>/parsers.py`, loaded dynamically via `spiders/registry.py`
- `discovered_urls` table tracks all found URLs per shop (accumulate-only, never deleted)
- `scrape_runs` table logs each run's phase/status for crash detection and resume
- `listings` table stores full product metadata (title, author, ISBN, publisher, year, pages, etc.)
- `prices` table is append-only (one row per scrape per listing)
- `books` table is for canonical records (shop-independent) — populated by match phase
- Per-shop settings in `config/shops/<shop>.toml`, loaded at spider init time

### Database

- Main DB: `postgresql://postgres:postgres@localhost:5432/book_scraper`
- Test DB: `postgresql://postgres:postgres@localhost:5433/book_scraper_test`
- Both run in Docker via `docker-compose.yml`
- Alembic needs `PYTHONPATH=.` to find models

### Adding a New Shop

1. Create `config/shops/<shop>.toml` with discovery strategies and scraping settings
2. Create `book_scraper/spiders/<shop>/` directory
3. Add `parsers.py` exporting `parse_sitemap_urls()`, `parse_category_page()`, `parse_product_page()`
4. Add test fixtures and parser tests
5. No new spider classes needed — generic spiders load parsers dynamically

## Testing

Tests are split into `tests/unit/` (fast, no DB) and `tests/integration/` (real PostgreSQL on port 5433).

- Unit tests cover parsers, config, items, session, registry, and spiders (using fake Scrapy responses)
- Integration tests cover DB repo layer and PostgresPipeline end-to-end
- Scrapy boilerplate (`settings.py`, `middlewares.py`, lifecycle methods) marked `# pragma: no cover`
- HTML fixtures in `tests/fixtures/` shared by parser and spider tests

## Post-Task Checklist

After completing any task that changes code, suggest to the user:

1. **Rebuild + restart containers**:
   - Dashboard-only changes (routes, templates, queries): `docker compose build dashboard && docker compose up -d dashboard`
   - **Schema changes (Alembic migration that drops/renames a column or type), model changes, repo/pipeline/spider changes**: rebuild *both* — `docker compose build dashboard scraper && docker compose up -d dashboard scraper`. Skipping the scraper rebuild leaves it running old code that queries dropped columns and every crawl crashes on startup (see commit f740448).
2. `uv run pytest tests/integration/test_dashboard_routes.py -v` — smoke test all routes.
3. After schema migrations, trigger a short scan (`scrapy crawl scan -a shop=vaga -a urls=<one-url>`) to confirm the scraper container picked up the new models.

## Code Conventions

- Python 3.12+, strict mypy
- Ruff for linting and formatting (line-length 88)
- Commit directly on main (personal project, no branches)
- Tests use real PostgreSQL (Docker on port 5433), not mocks
- Scrapy items use `scrapy.Field()`, validated in `ValidationPipeline` with Pydantic-style checks

## Specs and Plans

- Design spec: `docs/superpowers/specs/2026-04-05-book-scraper-design.md`
- Implementation plan: `docs/superpowers/plans/2026-04-05-book-scraper-plan.md`
- Fault tolerance spec: `docs/superpowers/specs/2026-04-06-fault-tolerance-design.md`
- Fault tolerance plan: `docs/superpowers/plans/2026-04-06-fault-tolerance-plan.md`
- Dashboard redesign spec: `docs/superpowers/specs/2026-04-14-dashboard-redesign-design.md`
- Dashboard redesign plan: `docs/superpowers/plans/2026-04-14-dashboard-redesign-plan.md`
- vaga.lt strategy: Notion page "vaga.lt scraping strategy"
- Architecture: Notion page "Scraping Strategy & Architecture"
