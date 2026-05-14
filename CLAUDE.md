# CLAUDE.md

## Project Overview

Multi-shop Lithuanian book price scraper built with Scrapy. Stores data in PostgreSQL. Onboarded shops:

- **vaga.lt** — OpenCart, HTML scraping (`sitemap` / `categories` / `full_crawl` strategies).
- **pegasas.lt** — Magento 2 PWA, scoped to the Lithuanian-language subtree (cats 5107/5125/6122). `graphql` strategy returns full metadata; `lupasearch` strategy is a fast supplementary index for daily price/stock rescans + new-arrivals detection (via `is_new`). Scan phase is a no-op (PWA pages have no parseable HTML — all data comes from discover).
- **humanitas.lt** — WordPress + WooCommerce + WPML, ~81k-book catalogue (mostly imported German/English academic + Lithuanian originals). Cloudflare **Managed Challenge** on every URL — bypassed via the **FlareSolverr** sidecar (`book_scraper/flaresolverr_middleware.py`, opted in per-shop via the `[flaresolverr]` block in the TOML). Discovery uses the `categories` strategy paginated at `m575a2product_limit=1000` with `cntnt01page` (the 5000 server cap hangs FS Chromium on the 17 MB response); `parse_product_page` reads the `<div class="book-info">` block and gates non-LT books via `Leidinio kalba`. Cron: Sundays 02:00 discover → 04:00 scan. Coverage on calibration: 99.3% ISBN, 96.1% year, 92.7% format.

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
uv run scrapy crawl scan -a shop=vaga -a max_urls=20               # Cap scan to 20 URLs (dev / smoke)
uv run scrapy crawl discover -a shop=vaga -a strategy=categories -a max_pages=3  # Cap discovery to 3 category pages
uv run scrapy crawl discover -a shop=pegasas -a strategy=graphql   # Pegasas: full LT metadata via Magento GraphQL (rich + slow)
uv run scrapy crawl discover -a shop=pegasas -a strategy=lupasearch  # Pegasas: fast price/stock rescan + is_new detection
uv run scrapy crawl discover -a shop=humanitas -a strategy=categories  # Humanitas: paginated catalogue via FlareSolverr (~10 min)
uv run scrapy crawl scan -a shop=humanitas                         # Humanitas: scan via FlareSolverr (slow — first run multi-day, then self-amortises)
docker compose up -d flaresolverr                                  # FlareSolverr sidecar (required for humanitas)
RUN_FLARESOLVERR_TESTS=1 uv run pytest tests/integration/test_humanitas_flaresolverr.py -v  # End-to-end FS test (opt-in)
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
# Observability (v1.2)
open http://localhost:3000                                           # Grafana — login admin/admin (change on first use)
docker compose up -d loki alloy grafana                             # bring observability stack up after compose changes
docker compose restart grafana                                       # reload Grafana provisioning (data sources, dashboards)
docker compose restart alloy                                         # reload Alloy config (monitoring/alloy/config.alloy)
curl -s 'http://localhost:3100/loki/api/v1/labels' | jq             # list active Loki labels (sanity check)
curl -s 'http://localhost:3100/loki/api/v1/query?query={service="dashboard"}&limit=5' | jq  # last 5 dashboard lines
curl -s 'http://localhost:12345/-/ready'                             # Alloy readiness probe
```

> **OrbStack build gotcha:** OrbStack injects `NO_PROXY` entries containing IPv6 CIDR blocks
> (e.g. `fd07:b51a:cc66:f0::/64`) into container env vars. `httpx.AsyncClient` chokes on
> these during spider init (treats the CIDR as a port). The spider-side fix is
> `trust_env=False` (already applied). For `docker compose build` the proxy vars also break
> `apt-get` inside the build context — use the Make targets which clear the proxy vars:
>
> ```bash
> make compose-build-scraper      # rebuild scraper
> make compose-build-dashboard    # rebuild dashboard
> make compose-build              # rebuild everything
> ```
>
> The Makefile wraps each command with `HTTP_PROXY="" ... docker compose build`. Avoid
> bare `docker compose build`; it silently produces an image with missing apt packages.

## Architecture

- **Framework:** Scrapy with asyncio reactor
- **DB:** PostgreSQL via SQLAlchemy 2.0, migrations via Alembic
- **Dashboard:** FastAPI + Jinja2 + Pico CSS, served via Docker at `http://localhost:8000`
- **Config:** TOML files in `config/` (global defaults + per-shop overrides)
- **Package manager:** uv
- **Deployment:** Everything runs in Docker via `docker-compose.yml`. Rebuild + restart to see changes.

### Pipeline Phases

1. **Discover** (`discover` spider) — find URLs. Strategies: `sitemap`, `categories`, `full_crawl`, `graphql` (Magento), `lupasearch` (third-party search index, POST endpoint). GraphQL + LupaSearch can also yield full `ShopBookItem` data inline, so for Magento PWA shops the scan phase becomes a no-op.
2. **Scan** (`scan` spider) — scrape full product pages for discovered URLs. Resumable after crashes.
3. **Match** — not yet implemented (link shop_books to canonical books)

Spiders are generic — shop is passed as argument: `scrapy crawl discover -a shop=vaga -a strategy=sitemap`

### Run lifecycle & stall recovery

`StallDetector` (`book_scraper/extensions.py`) closes the spider if no `response_received` or `item_scraped` signal lands for `STALL_TIMEOUT` seconds (default 180s). On stall:

1. Run flipped to `failed` with `resumable_after_failure=True` + `close_reason=stall_timeout`.
2. Auto-resume queued — fires on `spider_closed` signal, or via a force-exit timer at `STALL_FORCE_EXIT_S` (default 60s) if the natural close drains too slowly. Force-exit calls `os._exit` after spawning the new subprocess.
3. New scrapy process inherits the queue via `inherit_pending_items`, which also resets retryable failures (`run_aborted` / `stuck_in_processing` / `subdivision_5xx`) to pending.
4. Chain depth is tracked via `resumed_after_failure` events in `scrape_run_events`. Capped at `STALL_AUTO_RESUME_MAX` (default 10). When the cap hits, the run stays `failed` and waits for an operator click on Continue.

Adaptive subdivision: when a `discover_graphql` page returns 5xx, the spider reschedules the failed range as N smaller pageSize requests (`subdivide_factor` in the shop config, default 5). The depth=1 sub-page carries `_sub=1` in its URL so it can't recurse. Each subdivision is logged as a `subdivided` row on `scrape_run_events` (renders as ⊟ in the dashboard's Timeline card).

### Per-shop runtime settings

Precedence chain at runtime, highest to lowest:

1. **`shop_settings` DB row** — operator override applied without a redeploy.
2. **`config/shops/<shop>.toml` `[scraping]` block** — per-shop config; restart required.
3. **Scrapy globals from `book_scraper/settings.py`** — final fallback.

`HttpxMiddleware.spider_opened` walks the chain key-by-key: a DB row for `download_delay` wins for that key, but `concurrent_requests_per_domain` still falls through to TOML when no DB row exists.

Keys consumed: `concurrent_requests_per_domain` (int), `download_delay` (float).

```sql
-- Live override during an incident (no restart needed):
INSERT INTO shop_settings (shop_id, key, value, type)
VALUES ((SELECT id FROM shops WHERE name='pegasas'),
        'concurrent_requests_per_domain', '2', 'int')
ON CONFLICT (shop_id, key) DO UPDATE SET value=EXCLUDED.value, type=EXCLUDED.type;
```

### Key Design Decisions

- Generic spiders (`discover`, `scan`) — shop-specific logic lives in `spiders/<shop>/parsers.py`, loaded dynamically via `spiders/registry.py`
- `discovered_urls` table tracks all found URLs per shop (accumulate-only, never deleted)
- `scrape_runs` table logs each run's phase/status for crash detection and resume
- `shop_books` table stores full product metadata (title, author, ISBN, publisher, year, pages, etc.) — one row per book-as-it-appears-in-a-shop
- `prices` table is append-only (one row per scrape per shop_book)
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
3. Add `parsers.py` exporting `parse_sitemap_urls()`, `parse_category_page()`, `parse_product_page()`. The `parse_category_page` contract returns `{"products": [...], "total": int | None}` — `total` enables upfront pagination on the first page (the spider enqueues all remaining pages from `total`, so `concurrent_requests_per_domain` actually engages instead of chaining one page at a time). Return `total=None` for HTML-scrape shops where the count isn't reliably surfaced; the spider falls back to per-page chained pagination.
4. Add test fixtures and parser tests
5. No new spider classes needed — generic spiders load parsers dynamically

See the `📖 New Bookstore Onboarding Guide` Notion page for a full checklist + the pitfalls section captured during the pegasas onboarding (Magento `category_id` filter is membership-based and leaks across language siblings; EAN ≠ ISBN; e-book detection via category id since Magento has no `is_ebook`; etc.).

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
   - **BuildKit cache gotcha**: on macOS Docker Desktop, the `COPY book_scraper/` layer occasionally hits a stale-cache path even though source files changed — the new image is "Built" but inside the container `/app/book_scraper/...` still has the previous code. If you're verifying a fix and the running container disagrees with your edits, rebuild with `--no-cache`: `docker compose build --no-cache dashboard scraper && docker compose up -d dashboard scraper`. Quick way to confirm: `docker exec book-scraper-<svc>-1 grep <new-symbol> /app/book_scraper/<changed-file>` — if your new symbol isn't there, the cache lied.
2. `uv run pytest tests/integration/test_dashboard_routes.py -v` — smoke test all routes.
3. After schema migrations, trigger a short scan (`scrapy crawl scan -a shop=vaga -a urls=<one-url>`) to confirm the scraper container picked up the new models.
4. After deploying single-row restarts (2026-05-09): on shops with large
   stale-failed backlogs (humanitas, patogupirkti), the first scan may
   trigger an end-of-run retry sweep over hundreds–thousands of URLs.
   Watch heartbeat during the first run; if the sweep extends past
   STALL_TIMEOUT, the run will restart cleanly (single-row, capped at
   STALL_AUTO_RESUME_MAX restarts). To grandfather stale failures as
   exhausted before the first run, run:
   `UPDATE scrape_url_items SET attempts=3 WHERE status='failed';`
5. **Observability stack changes** (`monitoring/`, Grafana provisioning, Alloy config, Loki config): no rebuild — just `docker compose up -d loki alloy grafana` (or `docker compose restart grafana` for provisioning-only edits, `docker compose restart alloy` for Alloy config changes). Upstream images are pulled, not built.

### Observability label cardinality (Loki)

The Loki index can only afford low-cardinality labels. The four allowed labels are:
- `service` — bounded set (dashboard, scraper, postgres, flaresolverr, loki, promtail, grafana)
- `level` — INFO / WARNING / ERROR / DEBUG / CRITICAL
- `role` — operator / stall-resume / cron-chain / reconcile-restart / cron
- `shop` — vaga / pegasas / humanitas / future shops

**Never promote `run_id` to a label.** It's unbounded and would explode the index. Filter via LogQL `|= "run_id=N"` instead. Phase 4 (CODEOBS-02) emits `key=value` log lines so `| logfmt` works.

### Counter drift probe (single-row restart era)

With single-row restarts, old + new processes can briefly write to the same
`scrape_runs` row during handover (~60s window). Aggregate counters can
drift by tens of items. To check whether drift has crossed cosmetic levels:

```sql
SELECT id, urls_processed, urls_total,
       urls_processed - urls_total AS drift
FROM scrape_runs
WHERE urls_total IS NOT NULL AND urls_processed > urls_total
ORDER BY drift DESC LIMIT 10;
```

Drift of 1–10 across the fleet: cosmetic, ignore.
Drift of 50+ on a single run: investigate (process fencing may be needed —
see spec's Architectural alternatives section).

### Don't `kill -9` scrapy processes inside the container

If a runaway loop spawned multiple spiders, **don't** mass-`kill -9` them from inside the scraper container. The detached processes (started via `subprocess.Popen(start_new_session=True)` in `reconcile_runs.py` and `extensions.py`) leave open httpx + TCP sockets when SIGKILL'd, and Docker Desktop's macOS networking shim (vpnkit) can wedge — the daemon stops responding for 5–10 minutes. Escalation order instead:

1. `docker compose stop scraper` (SIGTERM, graceful close).
2. If that hangs, `docker kill scraper` (the daemon handles socket teardown cleanly when killing the container itself).
3. If `docker` itself hangs, restart Docker Desktop from the macOS menu bar.

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
- pegasas.lt strategy: Notion page "pegasas.lt scraping strategy"
- Architecture: Notion page "Scraping Strategy & Architecture"
- Onboarding checklist + pitfalls: Notion page "📖 New Bookstore Onboarding Guide"
