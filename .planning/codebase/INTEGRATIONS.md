# External Integrations

**Analysis Date:** 2026-05-10

## APIs & External Services

**Book Shop Targets (scraped):**
- **vaga.lt** - Lithuanian book shop (OpenCart). HTML scraping via `sitemap`, `categories`, `full_crawl` strategies.
  - Parsers: `book_scraper/spiders/vaga/parsers.py`
  - Config: `config/shops/vaga.toml`

- **pegasas.lt** - Magento 2 PWA. GraphQL API + LupaSearch third-party index.
  - GraphQL endpoint: `https://www.pegasas.lt/graphql` (GET, query encoded in URL)
  - LupaSearch endpoint: `https://api.lupasearch.com/v1/query/kum08qakjq3j` (POST with JSON body)
  - Auth: None required (public APIs)
  - Parsers: `book_scraper/spiders/pegasas/parsers.py`
  - Config: `config/shops/pegasas.toml`

- **humanitas.lt** - WordPress + WooCommerce. Behind Cloudflare Managed Challenge; all requests routed through FlareSolverr.
  - Discovery via paginated categories URL with CMSMS Products module (`m575a2product_limit=5000`)
  - Auth: None (FlareSolverr handles Cloudflare challenge)
  - Parsers: `book_scraper/spiders/humanitas/parsers.py`
  - Config: `config/shops/humanitas.toml`

- **ibiblioteka.lt** - Lithuanian National Library JSON API (LIBIS).
  - Search endpoint: POST `/detailed-search` (returns paginated bibliographic records)
  - Detail endpoint: GET `/bibliographic-records/public/{id}`
  - Auth: None required
  - Parsers: `book_scraper/spiders/ibiblioteka/parsers.py`
  - Config: `config/shops/ibiblioteka.toml`

- **almalittera.lt** - HTML scraping shop.
  - Parsers: `book_scraper/spiders/almalittera/parsers.py`
  - Config: `config/shops/almalittera.toml`

- **patogupirkti.lt** - HTML scraping shop.
  - Parsers: `book_scraper/spiders/patogupirkti/parsers.py`
  - Config: `config/shops/patogupirkti.toml`

**Third-Party Search Index:**
- **LupaSearch** - Third-party product search index over Magento catalogue.
  - Endpoint: `https://api.lupasearch.com/v1/query/kum08qakjq3j` (pegasas-specific)
  - Protocol: POST with JSON body; filter payload encodes category_ids and sort rules
  - URL helpers: `book_scraper/spiders/lupasearch_urls.py`
  - Auth: None (endpoint is shop-specific but publicly accessible)

**CDN / Fonts:**
- **Google Fonts** - Inter and JetBrains Mono loaded in dashboard HTML
  - CDN: `fonts.googleapis.com`, `fonts.gstatic.com`
  - Referenced in: `book_scraper/dashboard/static/hifi/index.html`

## Data Storage

**Databases:**

- **PostgreSQL 16** (primary)
  - Production connection: `postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper` (Docker service name `postgres`)
  - Local dev connection: `postgresql://postgres:postgres@localhost:5432/book_scraper`
  - Env var override: `DATABASE_URL`
  - Sync client: psycopg2-binary (used by Scrapy pipelines, session factory)
  - Async client: asyncpg (used by SQLAlchemy async sessions)
  - ORM: SQLAlchemy 2.0 with `DeclarativeBase` mapped models (`book_scraper/db/models.py`)
  - Session factory: `book_scraper/db/session.py` (pool_pre_ping=True, pool_recycle=300s, statement_timeout=10s, idle_in_transaction_session_timeout=5min)
  - Migrations: Alembic (`alembic/versions/`)

- **PostgreSQL 16** (test)
  - Test connection: `postgresql://postgres:postgres@localhost:5433/book_scraper_test`
  - Docker Compose profile: `test` (started with `docker compose --profile test up -d postgres-test`)
  - Port: 5433

**Key database tables:**
- `shops` - Registered shops with base URL
- `shop_books` - Product metadata per shop (title, author, ISBN, publisher, year, price, stock)
- `prices` - Append-only price history
- `discovered_urls` - Accumulate-only URL registry per shop
- `scrape_runs` - Per-run phase/status/counters with heartbeat tracking
- `scrape_url_items` - Persistent work queue for scan spider (resumable across crashes)
- `scrape_run_events` - Append-only lifecycle event log per run
- `scrape_failures` - Append-only failure event log
- `validation_issues` - Parser validation issues per run
- `cron_jobs` - Scheduled job definitions (read by `scripts/generate_crontab.py` at boot)
- `shop_settings` - Operator key/value runtime overrides per shop
- `books` - Canonical book records (populated by match phase)
- `book_isbns`, `book_authors`, `publishers`, `series`, `authors` - Canonical bibliographic tables

**File Storage:**
- Local filesystem only
- `logs/scrapy_events.log` - JSONL per-response event log (append-only, logrotate daily, 14-day retention via `docker/logrotate.d/scrapy_events`)
- `scrapy_errors.log` - Scrapy WARNING+ log (root project directory)
- Docker volume `scraper_logs:/var/log` (shared read-only with dashboard for live log display)

**Caching:**
- None (no Redis, Memcached, or other caching layer)

## Authentication & Identity

**Auth Provider:**
- None. No user authentication or sessions. The dashboard is unauthenticated — access controlled by network only (runs in Docker on localhost:8000).

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Rollbar, etc.)

**Structured Logging:**
- JSONL event log: `book_scraper/event_log.py`
  - One line per HTTP response; tail-able and jq-greppable
  - Fields: `ts`, `run_id`, `url`, `status`, `duration_ms`, `request_delay_s`, `delay_source`, `retry_count`, `in_flight`, `bytes`, optional `error_reason`
  - Path: `logs/scrapy_events.log` (or `SCRAPY_EVENTS_LOG` env var)

- Scrapy warnings/errors: `scrapy_errors.log` (WARNING+ level, configured in `book_scraper/settings.py`)

**Heartbeat / Crash Detection:**
- `HeartbeatExtension` in `book_scraper/extensions.py` — ticks every `HEARTBEAT_INTERVAL_S` (5s) and writes `last_heartbeat` timestamp to `scrape_runs`. Dashboard reaper kills runs that go stale.
- `StallDetector` in `book_scraper/extensions.py` — monitors response/item signals; closes spider after `STALL_TIMEOUT` (180s) with no activity while downloader is idle.
- Dashboard reaper: `book_scraper/dashboard/reaper.py` — background asyncio task watching for stale heartbeats.

## CI/CD & Deployment

**Hosting:**
- Local Docker Compose (`docker-compose.yml`)
- No cloud provider or Kubernetes configuration detected

**CI Pipeline:**
- None detected (no `.github/`, `.gitlab-ci.yml`, etc.)
- `make ci` combines `lint + test + deps` for local CI simulation

**Container build:**
- Multi-stage `Dockerfile` with `base`, `scraper`, and `dashboard` targets
- Base image: `python:3.12-slim`
- uv injected via `COPY --from=ghcr.io/astral-sh/uv:latest`
- Scraper stage adds system `cron` + `logrotate`
- Build note: OrbStack proxy env vars must be cleared before `docker compose build` (see CLAUDE.md)

**Scheduler (cron):**
- System `cron` daemon inside scraper container
- Crontab generated from `cron_jobs` DB table at container boot via `scripts/generate_crontab.py`
- `CronChainTrigger` Scrapy extension: after a cron-scheduled run finishes, spawns the chained job (linked via `cron_jobs.chain_to_job_id`)

**Process management:**
- `scripts/reconcile_runs.py` runs at scraper boot to fail orphaned `running` rows and auto-restart them
- `subprocess.Popen(start_new_session=True)` used for detached process spawning in `book_scraper/scripts/reconcile_runs.py` and `book_scraper/extensions.py`
- Auto-resume chain depth capped at `STALL_AUTO_RESUME_MAX` (3)

## Webhooks & Callbacks

**Incoming:**
- None (no inbound webhooks)

**Outgoing:**
- None (no outbound webhooks)

## FlareSolverr Sidecar

**Service:** `ghcr.io/flaresolverr/flaresolverr:latest`
- Docker Compose service name: `flaresolverr`
- Port: `8191`
- Protocol: JSON RPC via HTTP POST to `/v1`
- Purpose: Solve Cloudflare Managed Challenge for humanitas.lt (Chromium-based)
- Opt-in: per-shop via `[flaresolverr]` block in TOML (`config/shops/humanitas.toml`)
- Middleware: `book_scraper/flaresolverr_middleware.py` (priority 0, before HttpxMiddleware at priority 1)
- Session management: sessions created/destroyed per spider run; TTL 25 min (below CF's ~30 min clearance expiry); pre-rotation 90s before expiry
- Commands used: `sessions.create`, `sessions.destroy`, `request.get`, `request.post`

## Docker SDK Integration

**docker-py SDK** (`docker 7.0+`)
- Used by dashboard to trigger scrape runs without a separate API
- `docker.from_env()` connects via mounted Docker socket (`/var/run/docker.sock`)
- Dashboard executes `docker exec <scraper-container> scrapy crawl ...` to start spiders
- Container identified by compose labels: `com.docker.compose.service=scraper`, `com.docker.compose.project=<project>`
- Implementation: `book_scraper/dashboard/deps.py`, `book_scraper/dashboard/routes/api.py`

## Frontend (Dashboard SPA)

**CDN-loaded libraries (no build step):**
- React 18.3.1 — `https://unpkg.com/react@18.3.1/umd/react.development.js`
- ReactDOM 18.3.1 — `https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js`
- Babel Standalone 7.29.0 — `https://unpkg.com/@babel/standalone@7.29.0/babel.min.js` (transpiles JSX in-browser at runtime)
- Google Fonts — Inter + JetBrains Mono

All SPA source files: `book_scraper/dashboard/static/hifi/*.jsx` (16 JSX modules inlined at request time by `book_scraper/dashboard/app.py:_spa_html()` to defeat browser caching)

---

*Integration audit: 2026-05-10*
