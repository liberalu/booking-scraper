# Technology Stack

**Analysis Date:** 2026-05-10

## Languages

**Primary:**
- Python 3.12+ (3.13.12 in active venv) - All backend, spiders, pipelines, dashboard

**Secondary:**
- JSX/React - Dashboard SPA (`book_scraper/dashboard/static/hifi/*.jsx`)
- SQL - Alembic migrations (`alembic/versions/`)
- TOML - Shop configuration (`config/`)
- Bash - Entrypoints and utility scripts (`scripts/`)

## Runtime

**Environment:**
- CPython 3.13.12 (venv managed by uv)
- Asyncio event loop (via Twisted's `AsyncioSelectorReactor`)
- Production runtime: Docker containers

**Package Manager:**
- uv 0.11.3
- Lockfile: `uv.lock` (present, committed)
- Build backend: hatchling

## Frameworks

**Core:**
- Scrapy 2.12+ - Web scraping framework; spiders, middleware, pipelines (`book_scraper/spiders/`, `book_scraper/settings.py`)
- FastAPI 0.115+ - Dashboard HTTP API and SPA serving (`book_scraper/dashboard/`)
- SQLAlchemy 2.0 (asyncio extra) - ORM + query layer (`book_scraper/db/`)
- Pydantic 2.0+ - Config model validation and API request bodies (`book_scraper/config_models.py`)
- Alembic 1.15+ - Database schema migrations (`alembic/`)

**ASGI / Server:**
- uvicorn (standard) 0.34+ - ASGI server for dashboard, started via `scripts/entrypoint-dashboard.sh`

**Testing:**
- pytest 9.0.3+ - Test runner (`tests/`)
- pytest-asyncio 0.25+ - Async test support
- pytest-cov 7.0+ - Coverage reporting

**Build/Dev:**
- ruff 0.11+ - Linting and formatting (line-length 88, target Python 3.12)
- mypy 1.15+ strict mode - Type checking
- pre-commit 4.0+ - Git hooks (ruff check + ruff-format on commit)
- deptry 0.22+ - Unused/missing dependency detection
- pip-audit 2.7+ - Vulnerability scanning

## Key Dependencies

**Critical:**
- `httpx 0.28.1+` - Async HTTP client replacing Scrapy's Twisted downloader (`book_scraper/download_handler.py`). All HTTP requests go through `HttpxMiddleware`. Uses `trust_env=False` to avoid OrbStack proxy issues.
- `scrapy-impersonate 1.6+` - Browser TLS fingerprint impersonation. Registered as Scrapy download handler; enables the `AsyncioSelectorReactor`.
- `asyncpg 0.30+` - PostgreSQL async driver (loaded by SQLAlchemy via `postgresql+asyncpg://` connection string)
- `psycopg2-binary 2.9+` - PostgreSQL sync driver (used by Scrapy pipelines and session factory via `postgresql+psycopg2://`)
- `pydantic 2.0+` - Config model validation at load time; also used in dashboard API request/response shapes

**Infrastructure:**
- `jinja2 3.1+` - HTML templates; used by FastAPI's `Jinja2Templates` for legacy shop/scrape HTML routes
- `markdownify 1.1+` - Converts HTML product descriptions to Markdown in `PostgresPipeline` (`book_scraper/pipelines.py:263`)
- `croniter 6.0+` - Cron expression parsing for scheduled jobs in dashboard queries and API (`book_scraper/dashboard/queries.py`, `book_scraper/dashboard/routes/api.py`)
- `python-multipart 0.0.26+` - Multipart form parsing (FastAPI file/form upload support)
- `docker 7.0+` - Python Docker SDK used by dashboard to exec into the scraper container and trigger crawls (`book_scraper/dashboard/deps.py`)

## Configuration

**Environment:**
- `DATABASE_URL` env var overrides TOML database config (set in `docker-compose.yml`, consumed in `book_scraper/settings.py` and `book_scraper/dashboard/deps.py`)
- `SCRAPY_EVENTS_LOG` env var overrides the JSONL event log path (default: `logs/scrapy_events.log`)

**Runtime config precedence (highest to lowest):**
1. `shop_settings` DB rows - live operator overrides via SQL, no restart required
2. `config/shops/<shop>.toml` `[scraping]` block - per-shop TOML, restart required
3. Scrapy globals in `book_scraper/settings.py` - final fallback

**Config files:**
- `config/default.toml` - Global Scrapy defaults (download_delay, concurrent_requests, DB URL)
- `config/shops/*.toml` - Per-shop config (vaga, pegasas, humanitas, almalittera, ibiblioteka, patogupirkti)
- `alembic.ini` - Alembic migration config
- `scrapy.cfg` - Scrapy project location
- `pyproject.toml` - All Python tooling config (ruff, mypy, pytest, coverage, deptry)
- `.pre-commit-config.yaml` - Pre-commit hooks (ruff check + ruff-format)

**Build:**
- `Dockerfile` - Multi-stage build: `base` → `scraper`, `base` → `dashboard`
- `docker-compose.yml` - All services (postgres, postgres-test, flaresolverr, scraper, dashboard)

## Platform Requirements

**Development:**
- Docker (postgres on 5432, postgres-test on 5433)
- uv for dependency management
- OrbStack or Docker Desktop (note: `trust_env=False` required on httpx clients due to OrbStack IPv6 CIDR in `NO_PROXY`)

**Production:**
- Docker Compose deployment
- PostgreSQL 16 (Docker image `postgres:16`)
- FlareSolverr sidecar (`ghcr.io/flaresolverr/flaresolverr:latest`) — required when humanitas shop is active
- Scraper container runs `cron` (system cron) to schedule crawls; crontab generated from `cron_jobs` DB table at boot
- Dashboard container runs `uvicorn` on port 8000, mounts Docker socket (`/var/run/docker.sock`) to trigger scraper runs via docker exec

---

*Stack analysis: 2026-05-10*
