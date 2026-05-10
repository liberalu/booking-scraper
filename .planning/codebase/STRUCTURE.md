# Codebase Structure

**Analysis Date:** 2026-05-10

## Directory Layout

```
book-scraper/
├── book_scraper/          # Main Python package
│   ├── spiders/           # Scrapy spider + per-shop parser modules
│   │   ├── discover.py    # Generic discover spider
│   │   ├── scan.py        # Generic scan spider
│   │   ├── match.py       # Match spider (stub)
│   │   ├── registry.py    # Dynamic parser loader
│   │   ├── parser_types.py# TypedDicts for parser contracts
│   │   ├── cover_type.py  # Cover type normalisation utility
│   │   ├── graphql_urls.py# Magento GraphQL URL builder/parser
│   │   ├── lupasearch_urls.py # LupaSearch POST URL helpers
│   │   ├── ibiblioteka_api_urls.py # ibiblioteka.lt API URL helpers
│   │   ├── prices.py      # Price parsing utilities
│   │   ├── vaga/          # vaga.lt shop (OpenCart HTML)
│   │   │   └── parsers.py
│   │   ├── pegasas/       # pegasas.lt shop (Magento 2 PWA / GraphQL)
│   │   │   └── parsers.py
│   │   ├── humanitas/     # humanitas.lt shop (WooCommerce + FlareSolverr)
│   │   │   └── parsers.py
│   │   ├── ibiblioteka/   # ibiblioteka.lt (national library API)
│   │   │   └── parsers.py
│   │   ├── patogupirkti/  # patogupirkti.lt shop
│   │   │   └── parsers.py
│   │   └── almalittera/   # almalittera.lt shop
│   │       └── parsers.py
│   ├── db/                # Database layer
│   │   ├── models.py      # SQLAlchemy ORM models
│   │   ├── repo.py        # All DB queries (2255 lines)
│   │   ├── session.py     # SQLAlchemy session factory (cached)
│   │   └── scrape_run_events.py  # Event type constants
│   ├── services/          # Run lifecycle orchestration
│   │   ├── discover.py    # DiscoverService + DiscoverPlan
│   │   ├── scan.py        # ScanService + ScanPlan
│   │   └── match.py       # MatchService (stub)
│   ├── dashboard/         # FastAPI operator UI
│   │   ├── app.py         # FastAPI app factory + lifespan
│   │   ├── deps.py        # FastAPI dependency injection (DB session)
│   │   ├── queries.py     # Dashboard-specific DB queries
│   │   ├── reaper.py      # Background zombie-run reaper loop
│   │   ├── shop_book_filters.py  # Filter helpers for shop-books API
│   │   └── routes/
│   │       ├── api.py     # All REST API endpoints (2497 lines)
│   │       ├── scrape.py  # HTML scrape-trigger routes
│   │       └── shops.py   # HTML shop detail routes
│   ├── pipelines.py       # ValidationPipeline + PostgresPipeline
│   ├── extensions.py      # StallDetector, HeartbeatExtension, CronChainTrigger
│   ├── settings.py        # Scrapy global settings
│   ├── middlewares.py     # (placeholder — actual middleware in download_handler.py)
│   ├── download_handler.py # HttpxMiddleware (all HTTP requests)
│   ├── flaresolverr_middleware.py # FlareSolverr bypass middleware
│   ├── config.py          # TOML config loader
│   ├── config_models.py   # Pydantic config model definitions
│   ├── items.py           # Scrapy Item definitions
│   ├── book_types.py      # BookType enum
│   ├── isbn.py            # ISBN validation utilities
│   ├── url_utils.py       # URL normalisation
│   ├── event_log.py       # Per-response JSONL event writer
│   └── spawn_logging.py   # Log file helper for subprocess spawning
├── config/                # Per-shop TOML configuration
│   ├── default.toml       # Global defaults
│   └── shops/
│       ├── vaga.toml
│       ├── pegasas.toml
│       ├── humanitas.toml
│       ├── ibiblioteka.toml
│       ├── patogupirkti.toml
│       └── almalittera.toml
├── tests/
│   ├── unit/              # Fast tests, no DB (36 files)
│   └── integration/       # Tests requiring PostgreSQL on port 5433 (42 files)
├── tests/fixtures/        # HTML fixture files for parser tests
│   ├── vaga/
│   ├── pegasas/
│   ├── humanitas/
│   ├── knygos/
│   └── almalittera/
├── alembic/               # DB migrations
│   └── versions/          # Migration scripts
├── scripts/               # Utility scripts + entrypoints
│   ├── entrypoint-scraper.sh
│   ├── entrypoint-dashboard.sh
│   ├── generate_crontab.py
│   ├── migrations/        # Data-migration scripts
│   └── backfill_*.py      # One-off backfill scripts
├── logs/                  # Runtime log output (gitignored)
├── docker-compose.yml     # All services: postgres, postgres-test, scraper, dashboard, flaresolverr
├── Dockerfile             # Single image for both scraper + dashboard
├── pyproject.toml         # Dependencies (uv-managed)
├── scrapy.cfg             # Scrapy settings pointer
├── alembic.ini            # Alembic config
└── Makefile               # Convenience targets: coverage, audit, deps
```

## Directory Purposes

**`book_scraper/spiders/`:**
- Purpose: Generic spiders + all per-shop parse logic.
- Contains: `discover.py` and `scan.py` (the only two active spider classes), plus one subdirectory per onboarded shop.
- Key files: `registry.py` (3-line dynamic importer), `parser_types.py` (TypedDict contracts).

**`book_scraper/spiders/{shop}/`:**
- Purpose: Shop-specific HTML/JSON parsing, completely isolated per shop.
- Contains: `parsers.py` only. No spider classes.
- Key files: `vaga/parsers.py`, `pegasas/parsers.py`, `humanitas/parsers.py`.

**`book_scraper/db/`:**
- Purpose: All database interaction.
- Contains: ORM models, repo functions (raw SQLAlchemy), session factory.
- Key files: `models.py` (906 lines), `repo.py` (2255 lines).

**`book_scraper/services/`:**
- Purpose: Run lifecycle orchestration — business logic above raw DB calls.
- Contains: `ScanService`, `DiscoverService`, `MatchService`.
- Key files: `scan.py`, `discover.py`.

**`book_scraper/dashboard/`:**
- Purpose: FastAPI web app served as Docker container.
- Contains: App factory, REST routes, background reaper, query helpers.
- Key files: `app.py`, `routes/api.py` (2497 lines).

**`config/shops/`:**
- Purpose: Per-shop runtime configuration (discovery URLs, pacing, FlareSolverr toggle).
- Contains: One `.toml` per shop.
- Key files: `vaga.toml`, `pegasas.toml`, `humanitas.toml`.

**`tests/unit/`:**
- Purpose: Fast parser/config/item tests with no DB dependency.
- Contains: Parser tests, config tests, spider unit tests using fake Scrapy responses.
- Key files: `test_vaga_parsers.py`, `test_pegasas_parsers.py`, `test_spiders.py`.

**`tests/integration/`:**
- Purpose: Tests that require the test PostgreSQL instance (port 5433).
- Contains: Repo-layer tests, pipeline end-to-end tests, service tests, dashboard route tests.
- Key files: `test_postgres_pipeline.py`, `test_scan_service.py`, `test_dashboard_routes.py`.

**`tests/fixtures/`:**
- Purpose: Saved HTML pages for parser unit tests. Committed to repo.
- Contains: Subdirectory per shop. Used by `open(fixture_path).read()` in tests.

**`alembic/versions/`:**
- Purpose: DB migration scripts, applied with `alembic upgrade head`.
- Contains: Chronological migration files.

**`scripts/`:**
- Purpose: Container entrypoints and one-off data scripts.
- Key files: `entrypoint-scraper.sh`, `entrypoint-dashboard.sh`, `generate_crontab.py`.

## Key File Locations

**Entry Points:**
- `book_scraper/spiders/discover.py:57`: DiscoverSpider class
- `book_scraper/spiders/scan.py:61`: ScanSpider class
- `book_scraper/dashboard/app.py:36`: FastAPI app instance
- `scripts/entrypoint-scraper.sh`: Docker scraper container start
- `scripts/entrypoint-dashboard.sh`: Docker dashboard container start

**Configuration:**
- `book_scraper/settings.py`: Scrapy global settings (loaded first)
- `config/default.toml`: Global defaults (robotstxt, DB URL)
- `config/shops/{shop}.toml`: Per-shop settings (one per onboarded shop)
- `book_scraper/config_models.py`: Pydantic models for TOML config
- `book_scraper/config.py`: `load_shop_config(shop_name)` and `load_default_config()`

**Core Logic:**
- `book_scraper/pipelines.py`: `ValidationPipeline` + `PostgresPipeline`
- `book_scraper/extensions.py`: `StallDetector`, `HeartbeatExtension`, `CronChainTrigger`
- `book_scraper/download_handler.py`: `HttpxMiddleware` (all HTTP)
- `book_scraper/db/repo.py`: All SQL queries
- `book_scraper/db/models.py`: All ORM models
- `book_scraper/services/scan.py`: `ScanService` (prepare/populate/finish scan runs)
- `book_scraper/services/discover.py`: `DiscoverService` (prepare/finish discover runs)

**Testing:**
- `tests/conftest.py`: Shared fixtures (DB session, factories)
- `tests/unit/`: Parser + unit tests (no DB)
- `tests/integration/`: DB-backed integration tests
- `tests/fixtures/{shop}/`: HTML fixture files

## Naming Conventions

**Files:**
- Snake_case modules: `download_handler.py`, `flaresolverr_middleware.py`, `scrape_run_events.py`
- Test files: `test_{module_or_subject}.py`
- Config files: `{shop}.toml`
- Migration files: `{hash}_{description}.py` (Alembic standard)

**Directories:**
- Shop spider directories: lowercase shop name matching the `shop` CLI argument: `vaga/`, `pegasas/`, `humanitas/`
- All lowercase with underscores.

**Classes:**
- Services: `{Phase}Service` — `ScanService`, `DiscoverService`
- Plan dataclasses: `{Phase}Plan` — `ScanPlan`, `DiscoverPlan`
- Pipelines: `{Name}Pipeline` — `ValidationPipeline`, `PostgresPipeline`
- Extensions: `{Name}Extension` or `{Name}Detector` — `HeartbeatExtension`, `StallDetector`
- Middlewares: `{Name}Middleware` — `HttpxMiddleware`, `FlaresolverrMiddleware`
- ORM models: PascalCase matching table names: `ShopBook`, `DiscoveredUrl`, `ScrapeRun`

**Functions:**
- Repo functions: `verb_noun` snake_case: `upsert_shop_book`, `insert_price`, `find_resumable_run`
- Parser functions: `parse_{target}`: `parse_category_page`, `parse_product_page`, `parse_sitemap_urls`
- Private helpers: leading underscore: `_split_author_string`, `_finalize_run_failed`

## Where to Add New Code

**New Shop:**
1. Config: `config/shops/{shop}.toml` — define `[shop]`, `[discover.*]`, `[scraping]` sections.
2. Parsers: `book_scraper/spiders/{shop}/parsers.py` — export `parse_sitemap_urls`, `parse_category_page`, `parse_product_page`.
3. `book_scraper/spiders/{shop}/__init__.py` — empty file.
4. Fixtures: `tests/fixtures/{shop}/` — saved HTML for parser tests.
5. Tests: `tests/unit/test_{shop}_parsers.py`.
6. No new spider class needed — `discover` and `scan` are generic.

**New Discovery Strategy:**
1. Add strategy-specific URL builder to `book_scraper/spiders/{strategy}_urls.py`.
2. Add parser method to shop's `parsers.py`.
3. Add `parse_{strategy}_page` handler in `book_scraper/spiders/discover.py`.
4. Add strategy name to `_valid_strategies` set in `discover.py:99`.
5. Add `{strategy}: {url_type}` mapping in `services/discover.py:28-35`.

**New API endpoint:**
- Location: `book_scraper/dashboard/routes/api.py`
- Pattern: `@router.get("/endpoint")` or `@router.post(...)` with FastAPI dependency injection (`db: Session = Depends(get_db)`).

**New DB query:**
- Location: `book_scraper/db/repo.py`
- Pattern: `def verb_noun(session: Session, ...) -> ReturnType:` using SQLAlchemy 2.0 `select()` / `update()` / `pg_insert().on_conflict_do_update(...)`.

**New ORM model:**
- Location: `book_scraper/db/models.py`
- Pattern: `class Name(Base):` with `Mapped[type]` column annotations.
- Follow with an Alembic migration: `alembic revision --autogenerate -m "description"`.

**New Scrapy extension:**
- Location: `book_scraper/extensions.py`
- Register in `book_scraper/settings.py` under `EXTENSIONS`.

**Utilities (shared):**
- ISBN logic: `book_scraper/isbn.py`
- URL normalisation: `book_scraper/url_utils.py`
- Cover/format parsing: `book_scraper/spiders/cover_type.py`
- Book type enum: `book_scraper/book_types.py`

## Special Directories

**`logs/`:**
- Purpose: Runtime log output (`scrapy_errors.log`, `scrapy_events.log`, spawn logs).
- Generated: Yes (at runtime)
- Committed: No (gitignored)

**`alembic/versions/`:**
- Purpose: Schema migration history.
- Generated: Partially (via `alembic revision --autogenerate`), then edited.
- Committed: Yes.

**`tests/fixtures/`:**
- Purpose: Saved HTTP response bodies for deterministic parser tests.
- Generated: No (manually saved during onboarding).
- Committed: Yes.

**`book_scraper/dashboard/static/`:**
- Purpose: Static assets for the dashboard UI.
- Contains: CSS, JS, `hifi/` SPA assets.
- Committed: Yes.

---

*Structure analysis: 2026-05-10*
