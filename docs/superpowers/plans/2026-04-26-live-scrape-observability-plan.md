# Live Scrape Observability — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-04-26-live-scrape-observability-design.md`
**Date:** 2026-04-26

Stages landed in order. Each stage rebuilds, smokes, commits before moving on.

---

## Stage 0 — Verification gates (no code merged)

These checks gate the rest of the work. They write no production code; they answer questions whose answers determine which version of Stage 1 we ship.

### Gate A — Does AUTOTHROTTLE actually drive dispatch under `HttpxMiddleware`?

`HttpxMiddleware.process_request()` returns an `HtmlResponse` directly. Scrapy's `AutoThrottle` reacts to the `response_downloaded` signal, which may or may not fire under that path. If it doesn't, `slots[slot].delay` may stay frozen at `AUTOTHROTTLE_START_DELAY` (in which case the value is fake) — or, worse, drift in a plausible-looking way while being completely ignored by the dispatcher (in which case the value is fake-but-believable).

A simple "does the value drift" probe is too weak; the strengthened probe verifies both drift *and* causality.

**Probe:**

1. Add a temporary DEBUG logger in `HttpxMiddleware.process_request()`. For each request, log:
   - `slot.delay` (the candidate value).
   - `monotonic_now - last_dispatch_monotonic` (actual interval since previous dispatch).
   - `request.url` (so windows can be aligned).
   Hold `last_dispatch_monotonic` in a module-level variable; update it per request.
2. Run `uv run scrapy crawl scan -a shop=vaga -a max_urls=30`.
3. Inspect the log:

**Pass conditions (all required):**
- `slot.delay` takes at least three distinct values across the 30 requests.
- For windows where `slot.delay` is high (top quartile of the run's values), the inter-dispatch interval is also high (loose correlation; eyeball it). What we're ruling out: `slot.delay = 4s` while dispatches happen every 2s — that means AUTOTHROTTLE state is being read by something else but is not gating dispatch through our middleware.
- The base case where `slot.delay` is at `AUTOTHROTTLE_START_DELAY` should also show inter-dispatch ≈ that value.

**Fail conditions (any one):**
- Value never drifts → AUTOTHROTTLE not updating.
- Value drifts but inter-dispatch is constant → value is set but ignored.
- Inter-dispatch is wildly noisier than `slot.delay` (e.g., engine queue dwarfs slot wait) → value isn't a useful proxy even if AUTOTHROTTLE is "alive."

**Branch:**
- **Pass:** Stage 1 captures `slots[slot].delay` into `request_delay_s` with `delay_source = 'autothrottle_slot'`.
- **Fail:** Stage 1 captures `time.monotonic() - request.meta['scheduled_at']` instead with `delay_source = 'httpx_observed'`. Dashboard labels accordingly. The deferred retry feature does *not* become viable — the spec's "Future work" section says retry needs `autothrottle_slot` confidence.
- **Either case:** the column is named `request_delay_s` and `delay_source` carries the provenance.

Remove the temporary log lines before merging Stage 1.

### Gate B — Confirm `scrape_url_items` indexes

```sql
\d scrape_url_items
```

Confirm indexes covering `(run_id, status)` and `(run_id, done_at)`. If missing, add to the Stage 1 migration. The live-view aggregates degrade badly without them.

### Gate C — (was for retry middleware ordering; no longer needed in this spec)

Throttle retry is deferred to a future spec, so the middleware-ordering reconnaissance is not required for the work in this plan. Re-run that check if/when the future retry feature is implemented.

---

## Stage 1 — Telemetry (read-only, no behavior change)

Adds per-URL telemetry, in-process heartbeat, JSONL event log. No retry semantics change. Pure observation.

### Files

**New:**
- `alembic/versions/<id>_add_url_telemetry_columns.py`
  - Add `request_delay_s float NULL`, `delay_source text NULL`, `retry_count int NOT NULL DEFAULT 0`, `response_bytes int NULL` to `scrape_url_items`.
  - Verify / create indexes `(run_id, status)` and `(run_id, done_at)` (skip if Gate B confirmed they exist).
- `book_scraper/extensions/heartbeat.py` — `HeartbeatExtension` class. `from_crawler` connects `spider_closed` and the new custom `run_started` signal. The extension does NOT start ticking on `spider_opened` (run_id isn't set yet). On `run_started(run_id)`: launch an asyncio task ticking every `HEARTBEAT_INTERVAL_S` (default 5). Each tick: `UPDATE scrape_runs SET last_heartbeat = now() WHERE id = :run_id` with `statement_timeout = 2s`; log + swallow on failure. Tick is a no-op if `run_id is None` (defensive belt-and-braces).
- `book_scraper/signals.py` — define a module-level sentinel object `run_started = object()` for the custom Scrapy signal. Emission is in scan.py via `self.crawler.signals.send_catch_log(signal=run_started, sender=self, run_id=self._run_id)`. Receiver signature is `def on_run_started(self, run_id: int, sender=None, **kwargs)` — `sender=self` is passed so receivers that filter on sender (a common Scrapy pattern) work correctly. The extension connects with `crawler.signals.connect(self.on_run_started, signal=run_started)`.
- `book_scraper/logging/events_log.py` — JSONL handler module. Exposes `log_response_event(run_id, url, status, duration_ms, request_delay_s, retry_count, in_flight, bytes)` that appends one line to `logs/scrapy_events.log`.
- `tests/unit/test_heartbeat_extension.py` — fake reactor, fake repo. Cases: (a) `run_started` not yet emitted → no tick, no UPDATE; (b) `run_started(run_id=42)` emitted → tick fires, UPDATE called with id=42; (c) `spider_closed` → loop stops cleanly; (d) DB error in tick → logged + swallowed, next tick still fires.
- `tests/unit/test_events_log.py` — write a few events, parse with `json.loads`, assert fields including `delay_source`.
- `tests/unit/test_batch_ownership.py` — assert that calling `flush_progress()` with a buffer of completed items does NOT modify any `scrape_url_items` row's `status`, `done_at`, `http_status`, `error_reason`, or `response_bytes`. Pins the ownership split.

**Modified:**
- `book_scraper/db/models.py` — add the four columns (`request_delay_s`, `delay_source`, `retry_count`, `response_bytes`) to `ScrapeUrlItem`.
- `book_scraper/db/repo.py`:
  - Extend `mark_scrape_url_item_processing()` to accept `request_delay_s: float | None`.
  - **New:** `mark_scrape_url_item_response(item_id, *, http_status, done_at, response_bytes, error_reason)` — single-row immediate UPDATE. Replaces (for live-view-relevant fields) the per-50-response batched path.
- `book_scraper/middlewares/download_handler.py` (`HttpxMiddleware.process_request`):
  - **If Gate A passed:** read `crawler.engine.downloader.slots[slot_key].delay`; pass to `mark_scrape_url_item_processing()` with `delay_source='autothrottle_slot'`. Wrap the slot lookup in `try/except KeyError`.
  - **If Gate A failed:** read `request.meta['scheduled_at']` (stamped by the spider when the request was yielded), compute `pre_send_wait = time.monotonic() - scheduled_at`, pass with `delay_source='httpx_observed'`. If `scheduled_at` is missing (defensive), fall back to recording the configured slot delay with `delay_source='configured_delay'`.
  - Both `request_delay_s` and `delay_source` are written in the same UPDATE that flips status to `processing`.
- `book_scraper/spiders/scan.py`:
  - In `start()`, immediately after `_run_id` is assigned, emit the `run_started` signal: `self.crawler.signals.send_catch_log(signal=run_started, run_id=self._run_id)`.
  - In `start()`, when invoked in single-URL mode (`-a urls=u1,u2,...`): upsert a `scrape_url_items` row per URL with `status='pending'`, then proceed through the same `processing → done|failed` lifecycle as a queued run. Use the existing `insert_scrape_url_item()` (idempotent on the unique `(run_id, url)` constraint) so re-clicking is safe.
  - When constructing each `scrapy.Request`: stamp `request.meta['scheduled_at'] = time.monotonic()`. Used by `HttpxMiddleware` when Gate A's fallback path is in effect, and harmless otherwise.
  - In `parse_product()` (or wherever responses land): call `mark_scrape_url_item_response(...)` directly with `http_status`, `done_at`, `response_bytes = len(response.body)`, `error_reason`. Do NOT enqueue this update through the 50-response batch at `book_scraper/spiders/scan.py:450-453` — write immediately. Remove the `mark_scrape_url_item_done`/`mark_scrape_url_item_failed` calls from the batch flush (`book_scraper/services/scan.py:126`); ownership of those columns now lives in the immediate path.
  - Keep `flush_progress()` for `scrape_runs` aggregate counters and discovered-URL side effects only.
  - Emit `log_response_event(...)` per response, including `delay_source`.
- `book_scraper/settings.py` — register `HeartbeatExtension` in `EXTENSIONS`. Add `HEARTBEAT_INTERVAL_S = 5`. Add JSONL log handler config.

### Verification (Stage 1)

- `PYTHONPATH=. uv run alembic upgrade head` — succeeds. `psql ... -c "\d scrape_url_items"` shows new columns. Run `alembic downgrade -1 && alembic upgrade head` — clean.
- `docker compose build scraper && docker compose up -d scraper` — container picks up new columns.
- `uv run scrapy crawl scan -a shop=vaga -a max_urls=10` — completes. Inspect:
  - `SELECT request_delay_s, retry_count, response_bytes, done_at, http_status FROM scrape_url_items WHERE run_id = <latest> ORDER BY claimed_at;` — values populated. `done_at` and `http_status` should appear *as the run progresses* (verify mid-run by sampling), not only at the end. This confirms the immediate-write path.
  - `SELECT last_heartbeat FROM scrape_runs ORDER BY id DESC LIMIT 1;` — fresh during the run; advances by ~5s on each sample.
  - `tail -f logs/scrapy_events.log | jq` — one line per response, all fields present.
- **Single-URL parity check.** `uv run scrapy crawl scan -a shop=vaga -a urls=https://www.vaga.lt/<some-product>` then `SELECT id, status, claimed_at, done_at FROM scrape_url_items WHERE run_id = <latest>;` — confirm the row exists and transitions through `pending → processing → done|failed`. Without this, single-URL runs would render empty in the live view.
- `uv run pytest tests/unit/test_heartbeat_extension.py tests/unit/test_events_log.py -v` — pass.
- `uv run pytest tests/integration/test_dashboard_routes.py -v` — passes (no dashboard changes yet, this is a regression check).
- `uv run ruff check book_scraper/ tests/`, `uv run mypy book_scraper/` — clean.

### Commit (Stage 1)

```
feat(scan): per-URL throttle/bytes telemetry + heartbeat extension + JSONL event log
```

---

## Stage 2 — Live dashboard view (read-only, no scraper changes)

Adds the JSON endpoint and wires `HFRunDetail` to poll it.

### Files

**New:**
- `tests/integration/test_run_live_route.py` — assert shape of `/api/runs/{id}/live`, including the empty-run case.

**Modified:**
- `book_scraper/dashboard/queries.py` — add three functions:
  - `get_run_in_flight(session, run_id) -> list[dict]` — the in-flight query.
  - `get_run_rate_window(session, run_id, seconds=60) -> dict[str, int]` — done/failed counts in window.
  - `get_run_recent_failures(session, run_id, limit=10) -> list[dict]`.
- `book_scraper/dashboard/routes/api.py` — add `GET /runs/{run_id}/live` returning:
  ```json
  {
    "run_id": 42,
    "status": "running",
    "health": "healthy" | "stuck" | "dead",
    "last_heartbeat_age_s": 3,
    "in_flight": [{"url": "...", "claimed_age_s": 1.2, "request_delay_s": 2.4, "delay_source": "autothrottle_slot", "retry_count": 0}],
    "rate": {"done_60s": 17, "failed_60s": 0},
    "recent_failures": [{"url": "...", "error_reason": "...", "http_status": 503, "done_age_s": 8}]
  }
  ```
  - Reuse the heartbeat-staleness logic in existing `get_run_health()`. Compute `health` server-side so the React component is dumb.
- `book_scraper/dashboard/static/hifi/hf-runs.jsx` (`HFRunDetail`) — add a second `useEffect` that polls `/api/runs/{id}/live` every 2 seconds while `data.status === 'running'`. Stop polling on unmount and on terminal status. Render new sub-blocks:
  - "Now fetching" panel using `live.in_flight[0]`.
  - Rate readout using `live.rate.done_60s`, derived requests-per-minute = `done_60s`.
  - "Recent failures" list from `live.recent_failures`.
  - Health badge from `live.health`.

### Verification (Stage 2)

- `docker compose build dashboard && docker compose up -d dashboard` — succeeds.
- Visit `http://localhost:8000/app`, navigate to Runs → click an active run.
- Trigger a real scan (`uv run scrapy crawl scan -a shop=vaga -a max_urls=20`):
  - In-flight URL changes ~every 2s in the React view.
  - Rate counter advances.
  - Throttle delay visible.
- `docker kill book_scraper-scraper-1` mid-run. Within 30s the run shows status "dead" / health red.
- Static run (`status='completed'`): live block hidden, no polling (verify in browser dev tools network tab).
- `uv run pytest tests/integration/test_run_live_route.py tests/integration/test_dashboard_routes.py -v` — pass.

### Commit (Stage 2)

```
feat(dashboard): live run telemetry endpoint + HFRunDetail polling
```

---

## Reuse

- `ScanService.flush_progress()` and `mark_scrape_url_item_processing()` (`book_scraper/db/repo.py`) — extend signatures, do not replace.
- `mark_stale_runs()` and `get_run_health()` in `book_scraper/dashboard/queries.py` — reuse for the `health` field; the heartbeat extension just makes them work correctly.
- Existing Scrapy log infrastructure in `book_scraper/settings.py` for adding the JSONL handler.
- `HFRunDetail` in `book_scraper/dashboard/static/hifi/hf-runs.jsx` — extend, do not duplicate. Already wired to `/api/runs/{id}`; just add a second fetch + interval.

## Open Questions / Risks

Most pre-merge unknowns are now resolved by Stage 0 gates. Remaining items:

- **DB statement timeout for heartbeat** — verify SQLAlchemy + asyncpg path supports per-statement timeout; if not, fall back to a connection-level `options='-c statement_timeout=2000'` for the heartbeat session.
- **Immediate-write contention** — switching from one UPDATE per 50 responses to one UPDATE per response is trivial at 1 req/s but worth checking via `pg_stat_statements` once Stage 1 has run a few hours.
- **Stage 0 Gate A outcome** — drives the dashboard label and `delay_source` value. UI labelling is honest in either case; no functional fork.
