# Follow-ups

Tasks deferred during the 2026-05-03 session (pegasas onboarding + run-lifecycle hardening). Also registered as Claude Code Desktop chips. This file is the durable record — pick from here, mark done by deleting the section + committing.

## Recommended order

1. **[#1 Pegasas pivot to LupaSearch + per-SKU enrichment](#1-pegasas-pivot-to-lupasearch--per-sku-enrichment)** — biggest reliability + perf win; makes #4 and #5 less urgent
2. **[#2 Daily LupaSearch cron for pegasas](#2-daily-lupasearch-cron-for-pegasas)** — fold into #1's deployment if doing both
3. **[#3 TOML `[scraping]` vs `shop_settings` reconciliation](#3-toml-scraping-vs-shop_settings-reconciliation)** — small footgun fix
4. **[#4 StallDetector should account for in-flight requests](#4-stalldetector-should-account-for-in-flight-requests)** — proper fix for stall behaviour; safety net for any future shop with similar slow-backend issues
5. **[#5 Investigate why RetryMiddleware skips 5xx](#5-investigate-why-retrymiddleware-skips-5xx)** — re-evaluate after #4
6. **[#6 Cap reconcile_runs concurrent restarts](#6-cap-reconcile_runs-concurrent-restarts)** — defensive, low probability event
7. **[#7 Fix NameError `or_` in dashboard queries](#7-fix-nameerror-or_-in-dashboard-queries)** — pre-existing one-line import fix
8. **[#8 Clean up 32 non-LT pegasas stragglers](#8-clean-up-32-non-lt-pegasas-stragglers)** — pure SQL, lowest priority

---

## #1: Pegasas pivot to LupaSearch + per-SKU enrichment

In `/Users/evaldas/Projects/book-scraper`, replace pegasas's deep-paginated `discover_graphql` strategy as the primary discovery mechanism with a two-phase approach: LupaSearch for URL + basic metadata, per-SKU GraphQL for full enrichment in the scan phase.

**Why:** Pegasas's Magento full-page cache wasn't designed for catalog-wide harvest. Deep pagination (page 200+ at pageSize=50) causes silent request hangs that StallDetector kills, requiring N auto-resume cycles to finish a full crawl. Single-SKU queries are indexed and fast (~200-500ms each), even cold-cache. ~14k LT products × 400ms / concurrency=4 ≈ 25 min total, no stalls.

**Concrete changes:**

1. **`book_scraper/spiders/pegasas/parsers.py`:**
   - Refactor so `_graphql_item_to_product` is reusable for both category-page items and single-SKU responses (same Magento shape — items[] is just length 1 in the SKU case).
   - Replace the React-shell stub in `parse_product_page(text)` with real JSON parsing: `data.products.items[0]` → product dict via the shared helper.
   - New `rewrite_scan_url(url) -> str` hook: extract trailing SKU from the URL slug (`...e-knyga-11004377` → `000000000011004377`, padded to 18 chars per Magento format) and return the GraphQL URL with a single-SKU filter. Use the same field set as the existing `_PRODUCT_FIELDS` from `book_scraper/spiders/graphql_urls.py`.

2. **`book_scraper/spiders/scan.py`:**
   - Before yielding a `scrapy.Request`, check if the shop's parser module exposes `rewrite_scan_url(url)`. If yes, swap to the returned URL and add `Accept: application/json` header (same pattern as the discover-graphql strategy uses).
   - Default behavior unchanged for vaga (parser doesn't export the hook).

3. **Tests:**
   - Capture a per-SKU GraphQL response as a fixture (e.g. SKU `000000000002188371` from the existing category fixture).
   - Unit-test `parse_product_page` against the new fixture.
   - Unit-test `rewrite_scan_url` extracts SKUs correctly across URL shapes.
   - Verify existing scan-spider tests still pass (vaga's flow must be untouched).

4. **`config/shops/pegasas.toml`:**
   - Add a comment noting that LupaSearch is now the recommended primary discovery; the GraphQL strategy stays for ad-hoc / debug use.

5. **Smoke test after shipping:**
   - Mark all pegasas runs `resumable_after_failure=FALSE` to clear the chain.
   - `docker exec book-scraper-scraper-1 uv run scrapy crawl discover -a shop=pegasas -a strategy=lupasearch` → expect ~3 min, ~1.5k LT products with basic metadata.
   - `docker exec book-scraper-scraper-1 uv run scrapy crawl scan -a shop=pegasas` → expect ~15-30 min, all products enriched with ISBN/year/pages/dimensions, **zero stall_timeouts**, single-spider invariant intact (verify via `/proc` and `scrape_run_events` chain length 0).
   - Sample-check shop_book/26841: should be `type=ebook` AND have ISBN/year/pages populated.

6. **Drop `discover_graphql` from the dashboard's default strategy presentation** for pegasas (it stays in the strategy picker as an option but isn't the default).

**Schedule integration (after the dashboard cron follow-up ships):**
- Daily: `discover_lupasearch` (3 min) — keeps prices/stock fresh, surfaces new SKUs.
- Weekly: `scan` (~25 min) — re-enriches new SKUs and any whose price/stock changed since the last LupaSearch run.

**What stays the same:** ON CONFLICT race fix in `upsert_discovered_url`, the parser contract `{products, total}`, auto-resume + force-exit + single-spider invariant (now a safety net rather than primary recovery), adaptive subdivision (still active for ad-hoc graphql runs), subdivided Timeline events, EAN/ISBN distinction, e-book detection via cat 6122, all attribute capture (dimensions, original_title, color, translator). All today's commits earn their keep — they just stop being load-bearing.

---

## #2: Daily LupaSearch cron for pegasas

In `/Users/evaldas/Projects/book-scraper`, the pegasas.lt shop now has a `lupasearch` discover strategy that takes ~3 minutes for a full LT-language pass (vs ~30 minutes for the GraphQL strategy with full metadata). It's the right tool for daily price + stock rescans and new-arrivals detection (via `is_new=1`).

**Add a cron job entry** that runs `discover_lupasearch` for pegasas daily — pick a sensible time (e.g. 03:00 UTC). Use the existing cron infrastructure: `book_scraper/db/repo.py` has `mark_cron_job_ran_if_matches`, `cron_jobs` table is the source of truth, and `book_scraper/scripts/generate_crontab.py` (or similar) renders it into actual crontab entries inside the scraper container.

The dashboard's "New schedule" dialog (`HFNewScheduleDialog` in `book_scraper/dashboard/static/hifi/hf-overlays.jsx`) should let you create the entry through the UI now that pegasas appears in the shop dropdown. Either click through the dashboard or `INSERT` directly into `cron_jobs` — whichever is faster and survives container restarts (the on-disk crontab regenerates from the DB on boot).

**Verify after creation:**
1. `docker exec book-scraper-scraper-1 crontab -l` shows the new entry.
2. The next scheduled run actually fires and finishes cleanly.

---

## #3: TOML `[scraping]` vs `shop_settings` reconciliation

In `/Users/evaldas/Projects/book-scraper`, the per-shop `[scraping]` section in `config/shops/<shop>.toml` (`download_delay`, `concurrent_requests_per_domain`, etc.) is **documented-only** — the live values used at runtime come from the `shop_settings` DB table, read in `book_scraper/download_handler.py::HttpxMiddleware.spider_opened`. If no DB row exists, the middleware falls back to the global Scrapy settings (e.g. `CONCURRENT_REQUESTS_PER_DOMAIN=1` from `book_scraper/settings.py`), NOT to the TOML's `[scraping]` block. This bit me when I bumped `concurrent_requests_per_domain = 2` in `config/shops/pegasas.toml` and the spider still ran at concurrency=1 until I manually inserted `INSERT INTO shop_settings ...`.

**Pick a coherent story and ship it. Either:**

**Option A (lean toward this):** make the TOML `[scraping]` values an actual fallback. In `HttpxMiddleware.from_crawler` or `spider_opened`, after reading the DB, fall through to `shop_config.scraping.<key>` if the DB has no row for that key, before falling through to Scrapy's default.

**Option B:** rewrite the TOML `[scraping]` docstring + comments to make it crystal-clear it's documentation/defaults that nothing reads at runtime, and that operators must use `shop_settings` (or the dashboard's rate-settings UI if/when it exists) to actually tune behaviour. Same applies to anything that references it.

Option A is more intuitive ("config files configure things"). Option B is honest about the current implementation.

Either way: add a clear test that shows the precedence chain (TOML → shop_settings → Scrapy default) so the next person onboarding a shop doesn't run into this. Verify with `uv run pytest tests/integration/`.

---

## #4: StallDetector should account for in-flight requests

In `/Users/evaldas/Projects/book-scraper`, `book_scraper/extensions.py::StallDetector` resets its `_last_activity` timer only on `response_received` and `item_scraped` signals. With pegasas.lt's Magento backend serving cold-cache misses in 60-150s and `concurrent_requests_per_domain=2`, two slow requests can be in flight simultaneously for >STALL_TIMEOUT seconds, no response lands, and the detector kills a run that's still actively doing work.

This was observed in pegasas runs 273 and 274 (both failed at ~50–60% done with `stuck_in_processing` failures). Bumping `STALL_TIMEOUT` from 60s to 180s pushed the failure further out but didn't eliminate it; the underlying detector logic is what needs fixing.

**Fix.** Make `_check_stall` consider whether there are in-flight requests before declaring a stall. The simplest signal: read `crawler.engine.downloader.active` (or equivalent — check Scrapy's API) — if non-empty, the engine isn't actually stalled, just waiting on slow responses. Reset the timer. Only fire the kill when both:
- `_last_activity` is older than the timeout, **AND**
- the downloader has no in-flight requests

Optionally also expose the in-flight count in the heartbeat / dashboard so operators can see "running but slow" vs "actually stalled."

After the fix, re-run pegasas full crawl with concurrency=2 (currently downgraded to 1 in `shop_settings` as a workaround) and confirm it completes without stall_timeout. Update `book_scraper/settings.py` STALL_TIMEOUT comment to reflect the new semantics.

---

## #5: Investigate why RetryMiddleware skips 5xx

In the book-scraper project (`/Users/evaldas/Projects/book-scraper`), Scrapy's `RetryMiddleware` is in the active downloader chain (visible in spider startup logs: `'scrapy.downloadermiddlewares.retry.RetryMiddleware'`), and Scrapy's default `RETRY_HTTP_CODES` includes 503 with `RETRY_TIMES=2`. But on observed pegasas.lt 503 responses during run 266, the failed `scrape_url_items.retry_count` stayed at 0 and the dispatch finished in ~5s — not the ~30+s you'd see with two retries and exponential backoff.

We worked around this by adding parser-level adaptive subdivision in `book_scraper/spiders/discover.py::_subdivide_failed_graphql_page`, but the underlying RetryMiddleware integration hole affects vaga and any future shop that also encounters transient 5xxs.

**Investigate and fix.** Likely culprits:
1. The custom `HttpxMiddleware` in `book_scraper/download_handler.py` short-circuits `process_request` by returning a synthesized `HtmlResponse` directly — the request never goes through Scrapy's downloader. RetryMiddleware's `process_response` *should* still see it on the way back, but maybe `dont_retry` is set on the request somewhere, or the response object is missing fields RetryMiddleware checks for.
2. The `meta` dict our spider builds in `_build_request_for_url_item` doesn't propagate `retry_times` or other retry hooks.

**What to deliver:** root-cause writeup + a fix that makes 5xx responses retry up to `RETRY_TIMES`. Add a unit test that simulates a 503 and asserts the request is reissued. After the fix, the parser-level subdivision still adds value (lighter requests on backend pressure), but should no longer be the only retry path.

---

## #6: Cap reconcile_runs concurrent restarts

In `/Users/evaldas/Projects/book-scraper/book_scraper/scripts/reconcile_runs.py`, the boot-time orphan-recovery script flips every still-`running` `scrape_run` to failed and **immediately spawns a fresh `scrapy crawl` subprocess for each one** — no cap, no spacing, no per-shop dedup. It runs from the scraper container's entrypoint.

This is the same swarm shape that wedged Docker Desktop's daemon during this session's auto-resume bug (multiple concurrent scrapy processes hammering pegasas at concurrency=2 each, accumulated httpx sockets, vpnkit stalled for ~10 minutes). The auto-resume path was hardened in commits `65caeb6` (single-spider via spider_closed) and `094d4e0` (force-exit at 60s); reconcile_runs is the remaining vector that could re-trigger the same kind of wedge if enough orphans accumulate (e.g. a long incident, a CI restart loop, or several container restarts in quick succession).

**Fix.** Three layers, smallest first:

1. **Per-(shop, phase) dedup.** If two orphans are e.g. `discover_graphql` for `pegasas`, restart only one — the dashboard's pre-flight check (`_preflight_checks` in `book_scraper/dashboard/routes/api.py`) refuses concurrent runs for the same shop+phase anyway, so spawning two would just race and one would no-op.
2. **Stagger spawns.** Insert a 5-second sleep between Popen calls so the first spider's prepare_discover runs before the next one tries.
3. **Cap total concurrent spawns** at e.g. 3. If 10 orphans found, restart 3 and leave 7 for the next reconcile cycle (or surface them via a validation issue so the operator notices).

Verify by manually creating 5 orphan rows (UPDATE scrape_runs SET status='running' for 5 different runs across different shops + same shop), then running `python -m book_scraper.scripts.reconcile_runs` and confirming the spawn pattern matches the cap + stagger.

---

## #7: Fix NameError `or_` in dashboard queries

In `/Users/evaldas/Projects/book-scraper/book_scraper/dashboard/queries.py` line 1448, there's a `NameError: name 'or_' is not defined` causing `tests/integration/test_validation_queries.py::test_get_issues_page_search_matches_title_or_url` to fail. The function uses `or_(ValidationIssue.url.ilike(pattern), ShopBook.title.ilike(pattern))` but `or_` is not imported.

Fix: add `or_` to the existing `from sqlalchemy import ...` statement at the top of `book_scraper/dashboard/queries.py`.

Verify by running: `uv run pytest tests/integration/test_validation_queries.py::test_get_issues_page_search_matches_title_or_url -v` from `/Users/evaldas/Projects/book-scraper`. After the fix passes, run the full integration suite to confirm no regressions: `uv run pytest tests/integration/ -q`.

After verification: rebuild and restart the dashboard container per CLAUDE.md post-task checklist (`docker compose build dashboard && docker compose up -d dashboard`), then `uv run pytest tests/integration/test_dashboard_routes.py -v` to smoke-test routes.

---

## #8: Clean up 32 non-LT pegasas stragglers

In `/Users/evaldas/Projects/book-scraper`, the pegasas.lt shop ingested some non-Lithuanian books before the language filter was added. After deleting all `Anglų` (English) books, 32 stragglers in other languages remain:

- 30 Prancūzų (French)
- 1 Lenkų (Polish)
- 1 Lietuvių ir anglų k. (bilingual LT/EN)

Plus 95 books with no language attribute set ("(unknown)") — those are likely real LT books that just lack the Magento attribute, so leave them alone. Only delete the 32 with explicitly non-LT, non-bilingual language tags (or include the bilingual one — operator's call).

**Run the cleanup** following the same pattern used for the English deletion in the recent feat(pegasas) commit (look at git log for `delete_en.sql` references). Deletion order:

1. `prices` where `shop_book_id IN (...)`
2. `shop_book_changes` where `shop_book_id IN (...)`
3. `UPDATE validation_issues SET shop_book_id=NULL` for those ids
4. `discovered_urls` where shop_book_id matches
5. `shop_books` (cascades to attributes/authors/field_updates)

Wrap the whole thing in a single transaction and commit. After cleanup, verify the language breakdown:

```sql
SELECT COALESCE(sba.value,'(unknown)') AS language, COUNT(DISTINCT sb.id) AS books
FROM shop_books sb
LEFT JOIN shop_book_attributes sba ON sba.shop_book_id=sb.id AND sba.key='language'
WHERE sb.shop_id=(SELECT id FROM shops WHERE name='pegasas')
GROUP BY sba.value ORDER BY books DESC;
```

Should show only `Lietuvių` + `(unknown)`.

No code change needed — purely a data cleanup.
