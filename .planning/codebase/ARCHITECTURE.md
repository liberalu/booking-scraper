<!-- refreshed: 2026-05-10 -->
# Architecture

**Analysis Date:** 2026-05-10

## System Overview

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         CLI / cron trigger                           │
│              scrapy crawl discover -a shop=X -a strategy=Y           │
│              scrapy crawl scan      -a shop=X                        │
└───────────────────────────┬──────────────────────────────────────────┘
                            │
         ┌──────────────────┴──────────────────┐
         ▼                                     ▼
┌─────────────────────┐             ┌──────────────────────┐
│   DiscoverSpider    │             │     ScanSpider        │
│  `spiders/discover.py`│           │  `spiders/scan.py`    │
│  strategies:        │             │  - loads queue from   │
│  sitemap/categories │             │    scrape_url_items   │
│  graphql/lupasearch │             │  - parses product     │
│  full_crawl/ibiblio │             │    pages              │
└────────┬────────────┘             └────────┬─────────────┘
         │  load_parsers(shop)               │  load_parsers(shop)
         ▼                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Shop-Specific Parsers (dynamic)                    │
│  `spiders/{shop}/parsers.py` — loaded via `spiders/registry.py`     │
│  parse_sitemap_urls() / parse_category_page() / parse_product_page()│
│  parse_lupasearch_response() / rewrite_scan_url()                   │
└─────────────────────────────────────────────────────────────────────┘
         │  yields items
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Item Pipelines                               │
│  ValidationPipeline (100) → `pipelines.py`                          │
│  PostgresPipeline   (200) → `pipelines.py`                          │
└─────────────────────────────────────────────────────────────────────┘
         │  upserts / inserts
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        PostgreSQL Database                           │
│  shops → shop_books → prices (append-only)                          │
│  discovered_urls → scrape_url_items → scrape_runs                   │
│  books (canonical layer, populated by match phase)                   │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI Dashboard                               │
│  `dashboard/app.py` — routes via `dashboard/routes/api.py`          │
│  served at http://localhost:8000 in Docker                           │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| DiscoverSpider | Find product URLs; enqueue in scrape_url_items | `book_scraper/spiders/discover.py` |
| ScanSpider | Fetch product pages; emit ShopBookItem/BookItem | `book_scraper/spiders/scan.py` |
| registry.load_parsers | Dynamically import `spiders/{shop}/parsers.py` | `book_scraper/spiders/registry.py` |
| Shop parsers | Parse HTML/JSON into typed dicts (per-shop) | `book_scraper/spiders/{shop}/parsers.py` |
| ValidationPipeline | Validate + clean items; accumulate issues | `book_scraper/pipelines.py` |
| PostgresPipeline | Upsert shop_books, insert prices, link URLs | `book_scraper/pipelines.py` |
| DiscoverService | Prepare/finish discover runs; resume logic | `book_scraper/services/discover.py` |
| ScanService | Prepare/finish scan runs; populate queue | `book_scraper/services/scan.py` |
| DB repo | All SQL: upserts, queue management, events | `book_scraper/db/repo.py` |
| DB models | SQLAlchemy ORM mapped classes | `book_scraper/db/models.py` |
| HttpxMiddleware | All HTTP via httpx (replaces Twisted client) | `book_scraper/download_handler.py` |
| FlaresolverrMiddleware | Route CF-protected shops through FS sidecar | `book_scraper/flaresolverr_middleware.py` |
| StallDetector | Auto-close + auto-resume stalled spiders | `book_scraper/extensions.py` |
| HeartbeatExtension | Tick last_heartbeat every 5s via worker thread | `book_scraper/extensions.py` |
| CronChainTrigger | Spawn next chained cron job on successful close | `book_scraper/extensions.py` |
| Dashboard app | FastAPI + Jinja2 operator UI | `book_scraper/dashboard/app.py` |
| Dashboard reaper | Background async loop: fail zombie runs | `book_scraper/dashboard/reaper.py` |

## Pattern Overview

**Overall:** Pipeline-driven multi-phase web scraper with DB-backed persistent queues.

**Key Characteristics:**
- Two generic Scrapy spiders (`discover`, `scan`) — shop logic lives entirely in parser modules, loaded dynamically by name.
- DB-backed work queue (`scrape_url_items`) enables crash resume: processing rows are reset to pending on restart.
- Httpx replaces Twisted's HTTP client throughout; middleware implements its own per-host throttle (Scrapy's slot machinery is bypassed when `process_request` returns a Response directly).
- Three Scrapy extensions (StallDetector, HeartbeatExtension, CronChainTrigger) wire into Scrapy signals for run lifecycle management.

## Layers

**Configuration Layer:**
- Purpose: Supply per-shop settings from TOML; expose via typed Pydantic models.
- Location: `config/shops/{shop}.toml`, `config/default.toml`
- Contains: Scraping pacing, discovery strategy URLs, flaresolverr blocks.
- Depends on: `book_scraper/config_models.py` (Pydantic), `book_scraper/config.py` (loader).
- Precedence (highest wins): `shop_settings` DB row → `config/shops/{shop}.toml [scraping]` → `book_scraper/settings.py` globals.

**Spider Layer:**
- Purpose: Orchestrate HTTP requests, call parsers, yield items, track run state.
- Location: `book_scraper/spiders/discover.py`, `book_scraper/spiders/scan.py`
- Contains: Request scheduling, pagination, subdivision, idle-sweep, pause/stop polling.
- Depends on: parser modules (via registry), service layer, DB repo.
- Used by: Scrapy engine.

**Parser Layer (shop-specific):**
- Purpose: Parse raw HTML/JSON responses into typed Python dicts.
- Location: `book_scraper/spiders/{shop}/parsers.py` for each shop.
- Contains: BeautifulSoup / json-based parsing, book classification scoring, type inference.
- Depends on: `book_scraper/book_types.py`, `book_scraper/isbn.py`, `book_scraper/spiders/cover_type.py`.
- Used by: DiscoverSpider, ScanSpider (loaded via registry).
- Contract: `parse_category_page() → CategoryPageResult`, `parse_product_page() → ProductPageResult`, `parse_sitemap_urls() → list[str]`.

**Service Layer:**
- Purpose: Orchestrate DB operations for run lifecycle (prepare, populate, finish, resume).
- Location: `book_scraper/services/discover.py`, `book_scraper/services/scan.py`, `book_scraper/services/match.py`
- Contains: ScanPlan / DiscoverPlan dataclasses, run-lock acquisition, freshness warnings, queue population.
- Depends on: DB repo, DB models.
- Used by: DiscoverSpider, ScanSpider.

**Pipeline Layer:**
- Purpose: Validate items, then persist them to PostgreSQL.
- Location: `book_scraper/pipelines.py`
- Contains: ValidationPipeline (field checks, attribute schema, year/pages swap detection), PostgresPipeline (upsert shop_books, insert prices, upsert discovered_urls).
- Depends on: DB repo, DB models.
- Used by: Scrapy engine (registered at priorities 100, 200).

**DB Layer:**
- Purpose: All database interactions; no business logic.
- Location: `book_scraper/db/repo.py` (queries), `book_scraper/db/models.py` (ORM), `book_scraper/db/session.py` (factory).
- Contains: upsert_shop_book, insert_price, upsert_discovered_url, scrape_url_items queue management, scrape_run lifecycle functions.
- Depends on: SQLAlchemy 2.0, PostgreSQL.
- Used by: Pipelines, services, spiders (direct calls for per-response updates), dashboard.

**Dashboard Layer:**
- Purpose: Operator UI for monitoring and controlling scrape runs.
- Location: `book_scraper/dashboard/`
- Contains: FastAPI app (`app.py`), REST API routes (`routes/api.py`), dashboard queries (`queries.py`), background reaper (`reaper.py`).
- Depends on: DB layer (read-heavy), shared DB session factory.
- Used by: operators, cron health checks.

**Middleware Layer:**
- Purpose: HTTP transport (httpx-based) and CF bypass (FlareSolverr).
- Location: `book_scraper/download_handler.py`, `book_scraper/flaresolverr_middleware.py`
- Contains: Per-host pacing (asyncio locks + adaptive delay), session rotation, hard timeouts, FlareSolverr JSON RPC.
- Registered at priorities: FlaresolverrMiddleware=0 (first), HttpxMiddleware=1.

## Data Flow

### Discover Phase

1. CLI invokes `scrapy crawl discover -a shop=X -a strategy=Y` — DiscoverSpider `__init__` loads `config/shops/X.toml` and `spiders/X/parsers.py` (`discover.py:57-146`).
2. `start()` calls `DiscoverService.prepare_discover()` which upserts the shop, resumes or creates a `scrape_runs` row, seeds `scrape_url_items` with strategy starting URLs (`services/discover.py:50-90`).
3. Spider yields Scrapy Requests from the queue. Each response goes to `dispatch()` which routes by `url_type` to `parse_sitemap`, `parse_categories`, `parse_lupasearch_page`, etc. (`discover.py:345-396`).
4. Each parser calls `parsers.parse_category_page(response.text)` → returns `CategoryPageResult {products, total}`.
5. Spider yields `DiscoveredUrlItem` (for each product URL) and `ShopBookItem` (when rich data is available inline, e.g., GraphQL/LupaSearch).
6. Pipeline: `ValidationPipeline.process_item` validates, then `PostgresPipeline.process_item` calls `upsert_discovered_url` + optionally `upsert_shop_book` + `insert_price`.
7. On close: `DiscoverService.finish_discover` marks the run completed/failed, stamps `last_run_at` on the cron job.

### Scan Phase

1. CLI invokes `scrapy crawl scan -a shop=X` — ScanSpider `__init__` loads config and parsers (`scan.py:61-119`).
2. `start()` calls `ScanService.prepare_scan_create_run()` which acquires a per-shop scan lock and creates a run row, then `populate_scan_queue()` loads discovered product URLs into `scrape_url_items` (`services/scan.py:74-`).
3. Spider iterates queue items, polling TTL-cached `scrape_runs.status` for pause/stop before each dispatch (`scan.py:340-360`).
4. `parse_product` calls `parsers.parse_product_page(response.text)` → returns `ProductPageResult`. For shops with `rewrite_scan_url` (pegasas), the URL is swapped to a GraphQL endpoint before fetching.
5. Anti-bot detection (`ANTI_BOT_MARKERS`) fires before content parsing; 200 OK challenge pages are treated as failures (`scan.py:30-58`).
6. Spider yields `ShopBookItem` (or `BookItem` for ibiblioteka); pipeline upserts + records price.
7. `spider_idle` hook: end-of-run retry sweep — failed items with `attempts < RETRY_CAP` are reset to pending and re-dispatched once per process.

### Stall Detection + Auto-Resume

1. `StallDetector._check_stall` fires every 10s via `reactor.callLater`.
2. Stall condition: elapsed > `STALL_TIMEOUT` (180s) AND no in-flight requests.
3. On stall: `_finalize_run_failed` marks run `failed` with `resumable_after_failure=True`, then `_maybe_auto_resume` checks chain depth and zero-progress circuit-breaker.
4. Params stashed in `_pending_auto_resume`; actual `subprocess.Popen` fires in `spider_closed` so the dying spider has drained first.
5. `STALL_FORCE_EXIT_S` (60s) fallback: if `spider_closed` hasn't fired, spawn + `os._exit(1)`.
6. New process inherits queue via `find_resumable_run` → `restart_run_in_place`; retryable failures reset to pending.
7. Chain capped at `STALL_AUTO_RESUME_MAX=3` (default). Zero-progress circuit-break at 2 consecutive zero-yield runs.

### Heartbeat

1. `HeartbeatExtension._tick` fires every `HEARTBEAT_INTERVAL_S=5s` via `reactor.callLater`.
2. Write is `deferToThread` (worker pool) so reactor thread is never blocked on DB I/O.
3. Updates `scrape_runs.last_heartbeat` only for rows with `status IN ('running', 'paused')`.
4. Returns current status; if `'stopping'`, signals `engine.close_spider`.
5. Dashboard reaper (`dashboard/reaper.py`) runs every 30s; any run with `last_heartbeat > 60s` ago (or `pid` dead) is transitioned to `failed`.

## Key Abstractions

**ShopBookItem:**
- Purpose: Carries full scraped product data between spider and pipeline.
- Examples: yielded by `discover.py:590-629`, `scan.py:590-611`
- Pattern: `scrapy.Item` subclass with typed fields; `properties` JSONB for shop-specific extras.

**CategoryPageResult / ProductPageResult:**
- Purpose: Typed contracts between generic spiders and shop parsers.
- Examples: `book_scraper/spiders/parser_types.py`
- Pattern: `TypedDict`; parsers must return this exact shape; spiders access by key.

**ScrapeUrlItem (queue row):**
- Purpose: Persistent work queue item enabling crash resume.
- Examples: `book_scraper/db/models.py:545-599`
- Pattern: Each URL has `status` (pending/processing/done/failed) + `attempts` counter. Processing rows reset to pending on restart. Unique on `(run_id, url)`.

**ScanPlan / DiscoverPlan:**
- Purpose: Decouple run-row creation from queue population so HeartbeatExtension starts before the slow INSERT batch.
- Examples: `book_scraper/services/scan.py:28-45`, `book_scraper/services/discover.py:38-44`
- Pattern: Dataclass returned by `prepare_*_create_run`, consumed by `populate_*_queue`.

## Entry Points

**Discover (CLI):**
- Location: `book_scraper/spiders/discover.py:57` (`DiscoverSpider`)
- Triggers: `scrapy crawl discover -a shop=X -a strategy=Y`
- Responsibilities: URL discovery, queue seeding, `DiscoveredUrlItem` + inline `ShopBookItem` emission.

**Scan (CLI):**
- Location: `book_scraper/spiders/scan.py:61` (`ScanSpider`)
- Triggers: `scrapy crawl scan -a shop=X`
- Responsibilities: Product page scraping, `ShopBookItem` / `BookItem` emission, pause/stop polling.

**Dashboard (HTTP):**
- Location: `book_scraper/dashboard/app.py:36` (`app = FastAPI(...)`)
- Triggers: Docker container start; listens on port 8000.
- Responsibilities: Operator UI — run control (start/stop/pause/resume/continue), shop-book browsing, validation issues, price history.

**Docker entrypoints:**
- Scraper: `scripts/entrypoint-scraper.sh` (runs `generate_crontab.py` then cron daemon)
- Dashboard: `scripts/entrypoint-dashboard.sh` (uvicorn on port 8000)

## Architectural Constraints

- **Threading:** Scrapy asyncio reactor (`AsyncioSelectorReactor`). All DB writes from spiders are synchronous in the reactor thread except `HeartbeatExtension._write_heartbeat` which is offloaded via `deferToThread`.
- **Global state:** `get_session_factory(url)` returns a cached `sessionmaker` keyed by URL (`db/session.py`). Shop cache in `PostgresPipeline` is per-pipeline-instance (per-run). `_config = load_default_config()` at module import in `settings.py`.
- **Circular imports:** `db/repo.py` imports from `spiders/vaga/parsers.py` (for `infer_shop_book_type`) — a seam between repo and spider layers.
- **Session isolation:** Each per-response DB write in the scan spider creates and closes a fresh session. The long-lived progress session is separate and only used for batch flushes.
- **httpx replaces Twisted:** `HttpxMiddleware.process_request` returns a Scrapy `HtmlResponse` directly, bypassing Scrapy's downloader slots. Pacing (per-host lock + adaptive delay) is re-implemented in the middleware.
- **OS process spawning:** Auto-resume and cron-chain use `subprocess.Popen(start_new_session=True)` with `start_new_session=True` so the child outlives the parent. Never use `kill -9` on these processes (see CLAUDE.md).

## Anti-Patterns

### Querying inside the reactor event loop synchronously

**What happens:** Spider callbacks do synchronous SQLAlchemy queries (e.g., `mark_scrape_url_item_response` called directly in `parse_product`).
**Why it's wrong:** Blocking the reactor thread stalls all other pending I/O callbacks; on large queues (patogupirkti 60k URLs) this caused heartbeat starvation and runs being killed by the dashboard reaper.
**Do this instead:** Batch writes via `_url_status_updates` + `_flush_progress` (every 10 responses). For true heartbeat correctness use `deferToThread` as `HeartbeatExtension` does (`extensions.py:566`).

### Reading full shop config in every DB write helper

**What happens:** `HttpxMiddleware.spider_opened` reads the precedence chain at startup rather than on every request.
**Why it's correct:** Settings are immutable within a run; reading them once at `spider_opened` is intentional.

## Error Handling

**Strategy:** Multiple independent failsafe paths ensure `scrape_runs` is never left zombie.

**Patterns:**
- Primary: `spider.closed(reason)` calls `ScanService.finish_scan` / `DiscoverService.finish_discover`.
- Failsafe: if that throws, `finalize_run_failsafe(database_url, run_id, ...)` opens a fresh session with `statement_timeout=5s` and marks the row done.
- Belt-and-suspenders: `StallDetector._finalize_run_failed` writes directly before calling `engine.close_spider`.
- Dashboard reaper: marks any run with stale heartbeat or dead PID as `failed` every 30s.
- Pipeline item errors: `PostgresPipeline.process_item` catches `SQLAlchemyError`, rolls back, clears shop cache, records a `scrape_failures` row, and continues — single bad item never poisons the run.

## Cross-Cutting Concerns

**Logging:** Standard Python `logging`; WARNING+ written to `scrapy_errors.log` via a `FileHandler` added at `settings.py` import. Per-response events written to `logs/scrapy_events.log` via `book_scraper/event_log.py`.
**Validation:** `ValidationPipeline` accumulates issues in-memory; flushed to `validation_issues` table at `close_spider`. Issues are surfaced in the dashboard's Issues card.
**Authentication:** No user auth on dashboard. Cloudflare bypass via FlareSolverr sidecar (opt-in per-shop via `[flaresolverr]` TOML block).

---

*Architecture analysis: 2026-05-10*
