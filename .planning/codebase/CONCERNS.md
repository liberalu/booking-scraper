# Codebase Concerns

**Analysis Date:** 2026-05-10

## Tech Debt

**Match phase incomplete — fuzzy/manual matching never implemented:**
- Issue: `match_method_enum` in `book_scraper/db/models.py` defines `"isbn"`, `"fuzzy"`, `"manual"` but only ISBN matching is implemented in `book_scraper/services/match.py`. Books without an ISBN (a significant share of the Lithuanian catalogue) are permanently `match_status='unmatched'` and never linked to canonical records.
- Files: `book_scraper/services/match.py`, `book_scraper/db/models.py` (line 81)
- Impact: Cross-shop price comparison, the eventual product comparison page, and the `books` table as the canonical price source all depend on matching coverage. ISBN-only coverage leaves title-only books as orphans indefinitely.
- Fix approach: Implement a fuzzy step using normalised title + author similarity (e.g. `pg_trgm` GIN index) in a new `_step_fuzzy_match` method on `MatchService`, guarded by a configurable similarity threshold per shop.

**`_MAX_YEAR = 2030` hard-coded in pipeline validation:**
- Issue: `book_scraper/pipelines.py` (lines 34–35) rejects any year outside `[1800, 2030]`. The upper bound will silently clear valid years for books published in 2031+.
- Files: `book_scraper/pipelines.py`
- Impact: Silent data loss for valid future-year books once the calendar rolls past 2030.
- Fix approach: Derive `_MAX_YEAR` from `datetime.now().year + 5` at module load time, or raise to a far-future constant and flag outliers instead of nulling.

**`ibiblioteka.toml` `year_to` requires annual manual update:**
- Issue: `config/shops/ibiblioteka.toml` (line 14) has `year_to = 2027 # exclusive — update each calendar year`. If not updated, newly published books from the current year will not be discovered.
- Files: `config/shops/ibiblioteka.toml`
- Impact: Silent coverage gap — new releases from the current year are skipped by the API discovery bands.
- Fix approach: Either auto-derive `year_to` in `book_scraper/spiders/ibiblioteka_api_urls.py` as `current_year + 2`, or add a CI check that fails when `year_to < current_year + 1`.

**Sync blocking HTTP call inside Twisted's async reactor (patogupirkti sitemap):**
- Issue: `book_scraper/spiders/patogupirkti/parsers.py` (line 99) calls `urllib.request.urlopen` synchronously inside a parser that is invoked from the Scrapy/Twisted reactor loop. The comment acknowledges this: "~2–3s blocking I/O". This blocks the entire reactor thread for the duration of each child-sitemap fetch.
- Files: `book_scraper/spiders/patogupirkti/parsers.py` (line 96–101)
- Impact: During the 2–3s blocking window the StallDetector timer still advances, the heartbeat cannot tick (it uses `deferToThread` but the reactor's callLater queue is frozen), and no other HTTP responses are dispatched. Low risk currently (single weekly discover run, only 2 child sitemaps), but fragile.
- Fix approach: Move the child-sitemap fetch back into the spider as a Scrapy `Request` chain, returning `total=None` from `parse_sitemap_urls` and adding a new `parse_sitemap_index` callback.

**`os._exit(1)` in production code path (StallDetector):**
- Issue: `book_scraper/extensions.py` (line 379) calls `os._exit(1)` in `_force_exit_after_stall` as a force-exit fallback when the spider pipeline drain takes too long. `os._exit` skips all `atexit` handlers, `finally` blocks, and Python teardown, meaning any in-flight DB writes in the `PostgresPipeline` session are abandoned mid-transaction.
- Files: `book_scraper/extensions.py` (line 379)
- Impact: Potential for partial item writes if `os._exit` fires while a pipeline `session.commit()` is in-flight. The stall scenario requires this to trigger, but it is a real risk on shops with large queues (e.g. humanitas).
- Fix approach: Accept the tradeoff as documented (a live-lock pipeline drain is worse), but add explicit session rollback in `_force_exit_after_stall` before calling `os._exit` to guarantee no half-committed rows.

**`reconcile_runs.py` spawns to `/dev/null` (no log capture):**
- Issue: `book_scraper/scripts/reconcile_runs.py` (line 60) passes `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL` for orphan restarts at boot. `StallDetector._spawn_resume_subprocess` does capture logs via `open_spawn_log`, but the boot reconciler discards stderr/stdout entirely.
- Files: `book_scraper/scripts/reconcile_runs.py` (lines 56–63)
- Impact: Orphan-restart failures at container boot are silent — no log trace if a spawned process immediately crashes.
- Fix approach: Mirror `StallDetector._spawn_resume_subprocess` — use `spawn_logging.open_spawn_log("reconcile-restart", shop)`.

**Hardcoded paths to `/app/.venv/bin/scrapy`:**
- Issue: `book_scraper/extensions.py` (line 308) and `book_scraper/scripts/reconcile_runs.py` (line 49) hardcode `/app/.venv/bin/scrapy`. This path is container-internal; running outside Docker (e.g. local dev) silently fails to spawn subprocesses.
- Files: `book_scraper/extensions.py`, `book_scraper/scripts/reconcile_runs.py`
- Impact: Auto-resume and boot-reconcile subprocess spawns silently fail in any non-Docker environment.
- Fix approach: Derive the scrapy binary path as `sys.executable.replace("python", "scrapy")` or use `shutil.which("scrapy")` as a fallback.

---

## Known Bugs

**Counter drift during single-row restarts:**
- Symptoms: `scrape_runs.urls_processed` can exceed `urls_total` by small amounts (1–10) because the dying spider and the newly spawned spider write to the same `ScrapeRun` row during the ~60s overlap window (the `STALL_FORCE_EXIT_S` timer).
- Files: `book_scraper/db/repo.py` (`update_scrape_run_progress`), `book_scraper/extensions.py` (`_check_stall`, `_force_exit_after_stall`)
- Trigger: Any stall-triggered auto-resume on a shop with a large pending queue (humanitas, patogupirkti).
- Workaround: SQL probe documented in CLAUDE.md:
  ```sql
  SELECT id, urls_processed, urls_total,
         urls_processed - urls_total AS drift
  FROM scrape_runs
  WHERE urls_total IS NOT NULL AND urls_processed > urls_total
  ORDER BY drift DESC LIMIT 10;
  ```
  Drift of 1–10: cosmetic. Drift of 50+: investigate.

**patogupirkti `variant_raw` never populated on product-page parse:**
- Symptoms: `parse_product_page` in `book_scraper/spiders/patogupirkti/parsers.py` (line 510) reads `properties.get("variant_raw")` but this key is only set by `parse_category_page`. Product-page calls start from a fresh `properties = {}`, so the `variant_raw` key is never present; the guard at line 510 is a dead branch.
- Files: `book_scraper/spiders/patogupirkti/parsers.py` (lines 505–513)
- Impact: `properties["variant_raw"]` from the scan phase is always absent — the cross-shop variant string is lost when a product is first discovered via sitemap (not category walk).

---

## Security Considerations

**Dashboard has no authentication:**
- Risk: The FastAPI dashboard (`book_scraper/dashboard/app.py`) exposes all API endpoints including run control (start/stop/pause/continue) and shop settings override with no authentication layer. Anyone with network access to port 8000 can trigger scrape runs, modify DB settings, or read all book data.
- Files: `book_scraper/dashboard/app.py`, `book_scraper/dashboard/routes/api.py`
- Current mitigation: Exposed only on `localhost:8000` via Docker port binding. Network isolation is the only control.
- Recommendations: Add HTTP Basic Auth or a bearer-token middleware for any non-localhost exposure. At minimum add an `ALLOWED_IPS` env-var guard in the middleware.

**`docker.sock` mounted in dashboard container:**
- Risk: `docker-compose.yml` (line 76) mounts `/var/run/docker.sock` in the dashboard container. Any code path that can execute inside the container can control the Docker daemon — full host access.
- Files: `docker-compose.yml`
- Current mitigation: The mount is used by `book_scraper/dashboard/deps.py` (line 29) via `docker.from_env()` for container inspection only.
- Recommendations: Replace Docker SDK usage with a lightweight sidecar that exposes only the needed operation (e.g. container name → log path), or scope to read-only operations by switching to the Docker HTTP API with a restricted socket proxy.

**No input sanitisation on operator-supplied CLI args passed to `subprocess.Popen`:**
- Risk: `StallDetector._spawn_resume_subprocess` and `CronChainTrigger._spawn_chain_subprocess` build `cmd_parts` from values read from the database (`shop`, `strategy`, `args`). Malicious values in these fields could inject arbitrary subprocess arguments.
- Files: `book_scraper/extensions.py` (lines 307–316, 722–728), `book_scraper/scripts/reconcile_runs.py` (line 49)
- Current mitigation: `shlex.quote` is applied when building the log string only, not when constructing `cmd_parts` for `Popen`. The DB is trusted; only an operator with DB write access could exploit this.
- Recommendations: Validate shop names against the known set from `config/shops/*.toml` before spawning.

---

## Performance Bottlenecks

**`MatchService._step3_shop_inferred_synthesis` runs in a Python loop:**
- Problem: `book_scraper/services/match.py` (lines 84–111) runs a SQL query to find candidate ISBNs, then loops over results in Python calling `_synthesise_one` per ISBN — each with multiple round-trips (SELECT Publisher, INSERT Book, INSERT BookIsbn, flush). With a growing cross-shop catalogue this becomes a long-running Python + DB chatty loop.
- Files: `book_scraper/services/match.py`
- Cause: Iterative Python loop over each candidate rather than a batch SQL upsert.
- Improvement path: Rewrite `_step3` as a single SQL `INSERT INTO books ... SELECT ...` with a follow-up `INSERT INTO book_isbns ... SELECT ...`, eliminating the Python loop and reducing N round-trips to 2.

**`_sync_attribute_rows` does a per-shop-book ORM query then iterates:**
- Problem: `book_scraper/db/repo.py` (lines 58–80) loads all `ShopBookAttribute` rows for a shop_book into a Python dict before upserting. Under high-throughput scan phases this creates N+1-style loading.
- Files: `book_scraper/db/repo.py`
- Cause: The `session.query(ShopBookAttribute).filter_by(shop_book_id=...)` inside a per-item pipeline callback.
- Improvement path: Replace with a PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` (already used for other tables in the repo layer).

**Large SQL result sets fetched into Python for dashboard queries:**
- Problem: Several queries in `book_scraper/dashboard/queries.py` (2592 lines) use SQLAlchemy ORM `.all()` on potentially large result sets without streaming. The shop books listing can return tens of thousands of rows.
- Files: `book_scraper/dashboard/queries.py`
- Cause: ORM query patterns that materialise full result sets.
- Improvement path: Apply `.limit()` + cursor pagination on all listing queries; the current per-page cap is set in some but not all callsites.

---

## Fragile Areas

**StallDetector / HeartbeatExtension — all `# pragma: no cover`:**
- Files: `book_scraper/extensions.py` (entire file, lines 1–759)
- Why fragile: The stall detector, heartbeat, and cron chain trigger are marked entirely `# pragma: no cover` because they depend on Twisted's reactor, which is difficult to test in isolation. The existing unit tests in `tests/unit/test_stall_detector.py` (105 lines) and `tests/unit/test_heartbeat_extension.py` (191 lines) use mocks and cover basic paths. However, the interaction between `_check_stall` → `_finalize_run_failed` → `_maybe_auto_resume` → `spider_closed` → `_spawn_resume_subprocess` → `_force_exit_after_stall` is not tested end-to-end with a real DB.
- Safe modification: The `_pending_auto_resume` state machine (lines 260–267, 358–379) is the most fragile path — any change to the handover between `_check_stall` and `spider_closed` risks double-spawn or missed spawn. Always trace both the natural-close and force-exit paths when modifying.
- Test coverage: `test_stall_detector.py` covers `_check_stall` in-flight guard; `_spawn_resume_subprocess`, `_another_run_active`, and `_force_exit_after_stall` have no tests.

**FlaresolverrMiddleware — entirely `# pragma: no cover` with no unit tests:**
- Files: `book_scraper/flaresolverr_middleware.py` (entire file, 388 lines)
- Why fragile: The FlareSolverr session rotation logic (`_ensure_session`, `_create_session_locked`) and the pre-rotation buffer (`_PRE_ROTATION_BUFFER_S = 90.0`) are complex async state machines that are entirely untested. The only test is the opt-in integration test `tests/integration/test_humanitas_flaresolverr.py` which requires a live FlareSolverr sidecar and a live humanitas.lt response.
- Safe modification: The session lock (`self._session_lock`) is shared across all concurrent coroutines; modifying the pre-rotation path without understanding the cold-start vs hard-expiry vs pre-rotation branches can cause session ID races.
- Test coverage: Unit tests should mock the httpx client and test the three session lifecycle paths (cold start, pre-rotation, hard expiry).

**HttpxMiddleware / download handler — all `# pragma: no cover`:**
- Files: `book_scraper/download_handler.py` (entire file, 519 lines)
- Why fragile: The HTTPX client reset logic (`_maybe_reset_client`), the per-host semaphore + dispatch lock, and the `spider_opened` DB settings override chain are untested at the unit level. Integration tests in `tests/integration/test_download_handler.py` cover the `spider_opened` DB path but not the async request dispatch or client rotation.
- Safe modification: The `_retired_clients` drain on `spider_closed` (not explicitly tested) can silently swallow aclose errors.

**`scrape_phase_enum` does not include almalittera/patogupirkti strategies:**
- Files: `book_scraper/db/models.py` (lines 336–347)
- Why fragile: The PostgreSQL `scrape_phase` enum lists `discover_sitemap`, `discover_categories`, `discover_full_crawl`, `discover_graphql`, `discover_lupasearch`, `discover_ibiblioteka_api`, `match`, `scan`. Shops that use `categories` (almalittera, patogupirkti) write `discover_categories` — this works. However, any new strategy that deviates from this naming requires both a migration and an enum update. The enum is `create_type=False` meaning Alembic does not manage its values, so adding a new strategy requires a manual `ALTER TYPE ... ADD VALUE` migration.
- Safe modification: Always add the new value to both the Alembic migration AND the `scrape_phase_enum` declaration in `models.py`.

**`_spa_html()` reads files from disk on every request:**
- Files: `book_scraper/dashboard/app.py` (lines 62–81)
- Why fragile: `_SPA_INDEX_PATH.read_text()` and per-JSX file reads run on every GET to any SPA route. Under concurrent dashboard load or a misconfigured file system this blocks the FastAPI async event loop with synchronous I/O.
- Safe modification: Add an in-memory cache with mtime-based invalidation, or only disable caching in development mode.

**`patogupirkti` and `humanitas` reactor-starving large queue loads:**
- Files: `book_scraper/spiders/scan.py` (the pending-URL cache load), `book_scraper/spiders/discover.py`
- Why fragile: Loading the pending-URL dedup set for patogupirkti (~60k URLs) into a Python dict in the scan spider's `start()` was identified as a reactor-starvation source (patogupirkti runs 363–366, 2026-05-08). Unit test `tests/unit/test_spiders.py` (lines 705–736) documents a 60k-iteration cache benchmark. If queue sizes grow further, this will re-trigger heartbeat_timeout failures.
- Safe modification: Do not increase concurrency or queue depth for patogupirkti without re-benchmarking the cache-load time.

---

## Scaling Limits

**Single-container scraper with subprocess-per-run architecture:**
- Current capacity: One Docker container running sequential scrapy processes per shop. The `start_new_session=True` subprocess model allows multiple shops to run in parallel, but they all share the same TCP stack and PostgreSQL connection pool.
- Limit: Docker Desktop's macOS networking shim (vpnkit) can wedge when many `httpx` connections are forcibly killed via `kill -9` (documented in CLAUDE.md). Past 5–6 simultaneous spider processes the risk of vpnkit deadlock increases.
- Scaling path: Migrate to a proper task queue (Celery or RQ) with one worker process per spider run, or deploy on Linux where vpnkit is not present.

**PostgreSQL connection pool exhaustion under multi-shop parallel runs:**
- Current capacity: Each spider creates its own `session_factory`, and `HeartbeatExtension._write_heartbeat` creates a new session per tick (5s interval). With 6 shops each running a scan + discover simultaneously that is 12+ session factories open concurrently.
- Limit: psycopg2's default pool size + PostgreSQL's `max_connections = 100` (default). No explicit pool size cap is configured in `book_scraper/db/session.py`.
- Scaling path: Add `pool_size` / `max_overflow` to `create_engine` in `book_scraper/db/session.py`, or switch to a connection pooler (PgBouncer).

---

## Dependencies at Risk

**`ghcr.io/flaresolverr/flaresolverr:latest` pinned to `:latest`:**
- Risk: `docker-compose.yml` (line 37) pulls `latest` with no digest pin. A breaking FlareSolverr update (Chromium version bump, API change) will silently break humanitas.lt discovery on the next `docker compose pull`.
- Impact: humanitas.lt discovery and scan both fail until the FlareSolverr issue is diagnosed and a compatible version is pinned.
- Migration plan: Pin to a specific FlareSolverr release tag (e.g. `v3.3.21`) and test upgrades explicitly.

**`scrapy-impersonate` — no version constraint upper bound:**
- Risk: `pyproject.toml` (line 7) specifies `scrapy-impersonate>=1.6` with no upper bound. This package bundles browser fingerprints for TLS impersonation; a major version bump could change the TLS fingerprint profile, causing Cloudflare passive-tier blocks on patogupirkti.lt to start firing.
- Impact: patogupirkti.lt scraping begins returning 403s or challenge pages silently.
- Migration plan: Cap at `scrapy-impersonate>=1.6,<2.0` and test fingerprint changes explicitly before upgrading.

---

## Missing Critical Features

**No price comparison across shops:**
- Problem: The `books` table and `prices` table have the schema for cross-shop price comparison (shop_book.book_id → books, prices.shop_book_id), but there is no API endpoint or UI view that retrieves the same canonical book's price from multiple shops. The match phase creates the linkage, but no consumer of that linkage exists yet.
- Blocks: The core product value proposition (price comparison) is not accessible through the dashboard or any API.

**No automated monitoring / alerting:**
- Problem: There is no alerting on stall-detected runs, heartbeat_timeout failures, or shops with zero coverage. The dashboard reaper marks runs failed and the dashboard shows them, but nothing sends an alert to the operator.
- Blocks: Silent failures (e.g. humanitas FlareSolverr sidecar crash, patogupirkti structure changes) go unnoticed until the operator manually checks the dashboard.

---

## Test Coverage Gaps

**FlareSolverr middleware unit tests:**
- What's not tested: `_ensure_session` pre-rotation path, `_create_session_locked`, `_fetch_via_flaresolverr` response parsing, `_mark_processing` failure modes.
- Files: `book_scraper/flaresolverr_middleware.py`
- Risk: CF session rotation silently breaks on a FlareSolverr API change without any test failure.
- Priority: High — humanitas.lt is the largest catalogue and entirely depends on this path.

**StallDetector auto-resume + subprocess spawn paths:**
- What's not tested: `_spawn_resume_subprocess` (actual Popen call), `_another_run_active` DB check, `_force_exit_after_stall` (os._exit path), `spider_closed` consuming `_pending_auto_resume`.
- Files: `book_scraper/extensions.py`
- Risk: Auto-resume double-spawn or missed spawn after a stall, leading to either doubled concurrency against a shop or a permanently stuck run.
- Priority: High — auto-resume is a critical production feature on all large shops.

**`scripts/` directory — no tests for most scripts:**
- What's not tested: `book_scraper/scripts/html_to_markdown_descriptions.py`, `book_scraper/scripts/fix_author_split.py`, `book_scraper/scripts/backfill_shop_book_types.py`.
- Files: `book_scraper/scripts/`
- Risk: One-off backfill scripts run against production data with no regression safety net. A typo in the WHERE clause could silently corrupt thousands of rows.
- Priority: Medium — scripts are run infrequently, but the data impact is high.

**`match` spider end-to-end integration test:**
- What's not tested: `MatchSpider.start()` end-to-end with a real DB, including the `asyncio.to_thread` dispatch and the `ScrapeRun` row finalisation.
- Files: `book_scraper/spiders/match.py`, `tests/unit/test_match_spider.py`
- Risk: Reactor-blocking regression in `MatchService` would not be caught before deployment.
- Priority: Medium.

**Dashboard routes with operator-triggered side-effects:**
- What's not tested: The start/stop/pause/continue/retry run API endpoints (`POST /api/runs/{id}/stop`, `POST /api/runs/{id}/continue`) in a scenario where the underlying spider subprocess is actually running. `tests/integration/test_dashboard_routes.py` (1549 lines) tests GET routes and some POST endpoints against the DB, but the subprocess-spawning code path in `book_scraper/dashboard/routes/scrape.py` is not exercised.
- Files: `book_scraper/dashboard/routes/scrape.py`
- Risk: A regression in the run-launch subprocess spawn could silently produce a "run started" DB row with no actual spider process.
- Priority: Medium.

---

*Concerns audit: 2026-05-10*
