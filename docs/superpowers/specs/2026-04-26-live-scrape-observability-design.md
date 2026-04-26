# Live Scrape Observability — Design

**Date:** 2026-04-26
**Status:** Ready for implementation

## Problem

The scan pipeline runs as one Scrapy process per shop, throttled to 1 request/sec by design (vaga.lt silently blocks bursts). The execution model is fine for the workload, but the user has no way to see what is happening during a run:

- AUTOTHROTTLE's adaptive delay is invisible. We cannot tell whether requests are going out at the 2-second baseline or the 30-second ceiling.
- Number of requests in flight is not surfaced live. Heartbeat-style progress is only flushed after every 50 responses, so a run that has been silently stuck for 5 minutes still looks "fresh."
- A request that has been hanging for >15 seconds on AUTOTHROTTLE backoff is indistinguishable on the dashboard from a healthy slow page.
- `scrape_runs.last_heartbeat` is *checked* by the dashboard's stale-run reaper but nothing reliably writes it. Crash detection lags by 20 minutes.
- Silent block pages (200 OK, tiny body) and full product pages look identical at the run-summary level.
- Recent failures, request rate, and error rate require manual SQL.

The user explored alternatives — splitting into per-page subprocesses, introducing Kafka — but those address throughput problems they do not have. The actual problem is **observability**, not execution semantics. Once observability exists, deeper architectural changes can be evaluated against real numbers.

## Goals

1. See the page currently being fetched, with how long it has been in flight and the dispatch delay applied (with provenance — see Risks).
2. See request rate, error rate, and the last N failures, refreshed every ~2 seconds on the run detail page.
3. Distinguish a stuck spider (alive but hung on a request) from a crashed spider (process gone).
4. **Capture the data needed to decide whether throttle-aware retry is safe.** Implement retry only as a follow-up, after live telemetry from real runs has proven a reliable adaptive signal *and* established what symptoms (beyond delay alone) should trigger it.
5. Keep a structured per-request log file (`scrapy_events.log`, JSONL) for postmortem and SSH tailing.

## Non-Goals

- Replacing Scrapy with per-page job processes.
- Introducing Kafka, Redis, or any new queue infrastructure.
- TCP connection refresh logic (revisit only if telemetry shows stale-connection failures).
- Prometheus / Grafana export.
- Per-shop configurable delay (already supported via `DOWNLOAD_DELAY` in shop config).
- **Throttle-aware automatic retry.** Deferred to a follow-up spec. See "Future work" section. The data captured here makes that future work possible without committing to the retry semantics now.

## Design

### Data model — extend `scrape_url_items`

Add four columns to the existing queue table. No new tables. All live stats are *derived* via aggregate queries on `scrape_url_items` + `scrape_runs`.

| Column | Type | Set by |
|---|---|---|
| `request_delay_s` | float, nullable | `HttpxMiddleware`, on dispatch. Holds AUTOTHROTTLE per-slot delay if Gate A passes; otherwise holds `time.monotonic() - request.meta['scheduled_at']` with `delay_source='httpx_observed'`. |
| `delay_source` | text, nullable | `HttpxMiddleware`, on dispatch. Values: `autothrottle_slot`, `httpx_observed`, `configured_delay`. Persisted (not log-only) so postmortems from DB/API can interpret `request_delay_s` correctly. |
| `retry_count` | int, default 0 | Added now for future retry analysis/compatibility; remains 0 in this spec because automatic retry is not implemented. Adding the column now avoids a second migration later. |
| `response_bytes` | int, nullable | Spider response handler, on done |

### Per-response immediate writes (no batching for live-view columns)

The existing scan pipeline buffers per-URL response bookkeeping until `_urls_responded % _flush_every == 0`, currently every 50 responses (`book_scraper/spiders/scan.py:450-453`). At 1 req/s, that batch represents up to ~50–100 seconds of write lag — which would make every live-view "done in last 60s" / "currently fetching" derivation wrong, and the dashboard would feel stale-by-design.

**Resolution:** writes for live-view-critical columns happen *immediately* per response, not via the batch. A new repo helper `mark_scrape_url_item_response(item_id, *, http_status, done_at, response_bytes, error_reason)` performs the single-row UPDATE on response.

**Explicit ownership split — must not be ambiguous.** With both an immediate path and a batched path co-existing, the same column written by both is a race. Ownership is partitioned:

| Column / responsibility | Owned by | Notes |
|---|---|---|
| `scrape_url_items.status` (terminal: `done`/`failed`) | Immediate (`mark_scrape_url_item_response`) | Batch must NOT write terminal status |
| `scrape_url_items.done_at` | Immediate | |
| `scrape_url_items.http_status` | Immediate | |
| `scrape_url_items.error_reason` | Immediate | |
| `scrape_url_items.response_bytes` | Immediate | |
| `scrape_url_items.request_delay_s` | `HttpxMiddleware` on dispatch (already part of the `processing` UPDATE) | One-shot; not touched again |
| `scrape_url_items.retry_count` | (no writer in this spec) | Column added now for forward compatibility; remains 0. Future retry feature would write it. |
| `scrape_runs.urls_processed`, `errors_4xx`, `errors_5xx`, `error_count` | Batch path (`flush_progress`) | Aggregate counters; safe to lag |
| Discovered-URL side effects (new URLs found in product pages) | Batch path | Already there; orthogonal to live view |

The existing `mark_scrape_url_item_done()` and `mark_scrape_url_item_failed()` helpers (`book_scraper/services/scan.py:126`) called from the batch are removed from the batch loop in Stage 1. They may stay defined in repo for backward compatibility but are no longer invoked from `flush_progress`. The spider's response handler calls `mark_scrape_url_item_response` directly and *does not* enqueue terminal-state work into the batch buffer.

This partition is enforced by code: the batch path's flush logic operates only on `scrape_runs` aggregates and discovery side-effects; it has no access to the per-URL terminal columns. A unit test asserts that calling the batched flush does not modify `scrape_url_items.status` / `done_at` / etc.

`status='processing'` is also written immediately on dispatch (already true today via `HttpxMiddleware.process_request`); this design preserves that.

### Liveness — heartbeat extension

A new Scrapy extension (`book_scraper/extensions/heartbeat.py`) starts a 5-second timer **after the spider's `_run_id` is known** and stops it on `spider_closed`. Each tick: `UPDATE scrape_runs SET last_heartbeat = now() WHERE id = :run_id` with a 2-second statement timeout (so a hung DB doesn't pile up ticks).

**Lifecycle detail:** `ScanSpider._run_id` is initialised to `None` (`book_scraper/spiders/scan.py:46`) and assigned inside `start()`, which runs *after* `spider_opened` fires. Hooking the extension to `spider_opened` directly would tick before a run row exists, foreign-key-failing the UPDATE. The spider therefore emits a custom Scrapy signal `run_started` once `_run_id` is set; the extension connects to that signal to launch its loop.

**Signal mechanics (concrete shape):**

```python
# book_scraper/signals.py — module-level sentinel object
run_started = object()
```

Spider side, immediately after assigning `self._run_id`:
```python
from book_scraper.signals import run_started
self.crawler.signals.send_catch_log(
    signal=run_started,
    sender=self,
    run_id=self._run_id,
)
```

Extension side, in `from_crawler`:
```python
from book_scraper.signals import run_started
crawler.signals.connect(self.on_run_started, signal=run_started)
# ...
def on_run_started(self, run_id: int, sender=None, **kwargs) -> None:
    self._run_id = run_id
    self._start_loop()
```

Using a sentinel object (not a string) matches Scrapy's own convention (`signals.spider_opened` etc.) and avoids accidental name clashes. Pass `sender=self` so receivers that filter on sender (a common Scrapy pattern) work correctly. `**kwargs` in the receiver absorbs any additional framework-injected keys.

The extension also tolerates `run_id is None` defensively (skip tick + log warning) as belt-and-braces against signal-ordering bugs.

The heartbeat is independent of request flow, so a request hung in AUTOTHROTTLE doesn't make the process look dead.

Combined with `claimed_at` age on the in-flight row, the dashboard distinguishes:

| Heartbeat fresh? | `now() - claimed_at` | Render as |
|---|---|---|
| Yes (< 30s) | small | Healthy — fetching |
| Yes | > `DOWNLOAD_TIMEOUT × 2` (30s) | Stuck on one request — alive but hung |
| No (> 30s) | any | Process dead |

### Throttle-aware retry — deferred

Originally planned for this spec. **Deferred** because it is mechanically broken in this architecture and would amplify the load patterns it is supposed to defend against. See "Future work" below for the framing of what a defensible version would look like. None of that is in scope here.

The data this spec collects (`request_delay_s`, `delay_source`, `retry_count`, `response_bytes`, plus the per-response JSONL log) is the input a future retry feature would need. We capture the data; we don't act on it yet.

### Structured event log

A JSONL log handler writes to `logs/scrapy_events.log`. One line per response:

```json
{"ts": "2026-04-26T12:00:01.234Z", "run_id": 42, "url": "...",
 "status": 200, "duration_ms": 312,
 "request_delay_s": 2.4, "delay_source": "autothrottle_slot",
 "retry_count": 0, "in_flight": 1, "bytes": 18432}
```

`delay_source` is one of `"autothrottle_slot"` (Gate A passed) or `"httpx_observed"` (Gate A failed; see Risks). Recorded explicitly so a postmortem reader can interpret the number correctly without grepping settings.

`in_flight` is read from the Scrapy slot in-process, no DB round-trip. Useful for `tail -f`, `jq`-greppable postmortems, and grep-based debugging when the dashboard isn't accessible.

### Dashboard live view

The React SPA migration (per `2026-04-25-hifi-react-dashboard.md`) is already in flight. Live observability plugs into that, not into the legacy Jinja templates.

- New endpoint `GET /api/runs/{run_id}/live` returns the aggregate JSON below.
- `HFRunDetail` (in `book_scraper/dashboard/static/hifi/hf-runs.jsx`) polls it on a 2-second `setInterval`, gated behind `data.status === 'running'` so finished runs don't poll.
- Health badge derives from the heartbeat × `claimed_at` table above.

**UI labelling — honest about provenance.** The delay value is *not* labelled "AutoThrottle delay." It is labelled "Dispatch delay" (or "Observed wait" — pick one and stay consistent), with a small confidence indicator derived from `delay_source`:

| `delay_source` | UI label suffix | Tooltip |
|---|---|---|
| `autothrottle_slot` | (verified) | "Adaptive throttle delay from AUTOTHROTTLE; verified by Gate A." |
| `httpx_observed` | (observed) | "Wall-clock wait between request scheduling and dispatch. Includes engine queue time, not purely AUTOTHROTTLE." |
| `configured_delay` | (static) | "Configured `DOWNLOAD_DELAY`; not adaptive." |

The dashboard never lies about the source. A reader who sees "(observed)" knows the number conflates queue time with throttle.

Aggregate queries (one round trip, all on existing/added indexes):

```sql
-- in flight
SELECT url, claimed_at, request_delay_s, delay_source, retry_count
FROM scrape_url_items
WHERE run_id = :run_id AND status = 'processing'
ORDER BY claimed_at DESC;

-- rate / errors over last 60s
SELECT
  COUNT(*) FILTER (WHERE done_at > now() - interval '60 seconds') AS done_60s,
  COUNT(*) FILTER (WHERE done_at > now() - interval '60 seconds' AND status = 'failed') AS failed_60s
FROM scrape_url_items
WHERE run_id = :run_id;

-- recent failures
SELECT url, error_reason, http_status, done_at
FROM scrape_url_items
WHERE run_id = :run_id AND status = 'failed'
ORDER BY done_at DESC NULLS LAST
LIMIT 10;
```

### Component boundaries

| Unit | Purpose | Inputs | Outputs |
|---|---|---|---|
| `HeartbeatExtension` | Prove process is alive | `run_id`, DB session | `scrape_runs.last_heartbeat` ticks every 5s |
| `HttpxMiddleware` (modified) | Record per-request delay (source per Gate A) | request, slot delay or `scheduled_at`-derived wait | `scrape_url_items.request_delay_s`, `scrape_url_items.delay_source` |
| Spider response handler (modified) | Record response size and terminal state | response | `scrape_url_items.response_bytes`, `done_at`, `http_status`, `error_reason` |
| `events_log_handler` | JSONL postmortem feed | per-response signal | `logs/scrapy_events.log` |
| `GET /api/runs/{id}/live` | Live JSON for the React UI | `run_id` | aggregate stats JSON |
| `HFRunDetail` (modified) | Render live view | API response | DOM updates every 2s |

Each unit has a single purpose, communicates through narrow interfaces (DB columns, Scrapy signals, JSON), and can be tested in isolation.

## Risks

- **AUTOTHROTTLE may not update under our custom downloader (Stage 0 verification gate).** `HttpxMiddleware.process_request()` (`book_scraper/download_handler.py:91-121`) explicitly bypasses Scrapy's normal downloader handoff and notes that `request_reached_downloader` does not fire. AUTOTHROTTLE's slot-delay updates depend on signals fired from that path. If they don't fire, `slots[slot].delay` is frozen at `AUTOTHROTTLE_START_DELAY` and `request_delay_s` is meaningless — the dashboard would show a convincing but fake number.

  **Gate A — strengthened.** A simple "does the value drift" probe is too weak; a value can drift while being completely ignored by the dispatcher. The probe must verify both that the value drifts *and* that it correlates with the actual dispatch cadence:

  1. Run ~30 URLs with a debug logger printing, per request: `slots[slot].delay` at dispatch time, and the wall-clock interval since the previous dispatch (`monotonic_now - last_dispatch_monotonic`).
  2. Pass conditions:
     - `slot.delay` takes at least three distinct values across the run (proves it drifts).
     - For windows where `slot.delay` is high, the inter-dispatch interval is also roughly high (proves the value actually controls dispatch — i.e., AUTOTHROTTLE is reading and applying it). Loose correlation is fine; what we're ruling out is "delay = 4s but dispatches every 2s," which means the value is set but ignored.
  3. Fail conditions: any of the above not met — including the case where the value drifts beautifully but dispatch cadence is constant (AUTOTHROTTLE state is being updated by *something* but isn't gating dispatch through our middleware).

  **Fallback semantics if Gate A fails — concrete measurement point.** `HttpxMiddleware.process_request()` only runs once Scrapy is ready to dispatch, so it cannot itself measure how long Scrapy delayed the request. A two-timestamp scheme:

  1. When the spider yields the request, stamp `request.meta['scheduled_at'] = time.monotonic()`.
  2. In `HttpxMiddleware.process_request()` at dispatch, compute `pre_send_wait = time.monotonic() - request.meta['scheduled_at']` and write it to `request_delay_s` with `delay_source = 'httpx_observed'`.

  This measures total Scrapy queue + slot wait — coarser than AUTOTHROTTLE's adaptive delay but honest about what it represents. The dashboard labels it "Dispatch delay (observed)" so readers don't mistake it for adaptive throttling state.

  **Telemetry, not authority.** Whatever the source, `request_delay_s` is observational data — useful for the live UI and for future analysis — not an authoritative trigger for any decision. The retry feature that would have read this value is deferred (see "Future work") precisely because the value's confidence depends on Gate A's outcome and because high delay does not, on its own, mean "should retry."
- **Heartbeat extension start-time.** `_run_id` is assigned inside `start()` after `spider_opened` fires. Connecting to `spider_opened` directly would tick before a run exists. The spider emits a custom `run_started` signal after `_run_id` is set; the extension connects to that.
- **Event-loop saturation.** A heavy synchronous parse can delay the heartbeat tick. The 30-second "dead" threshold (6× the 5-second tick) absorbs reasonable bursts. If parse spikes >30s become real, that is itself a bug to surface, not a heartbeat failure.
- **Heartbeat write contention.** Negligible at one run at a time. Re-evaluate if multi-shop concurrent runs become real.
- **Index coverage on `scrape_url_items`.** Confirm `(run_id, status)` and `(run_id, done_at)` indexes exist. If not, add them in the same migration. The aggregate queries collapse without these.
- **Per-response immediate writes vs existing batched flush.** Switching `done_at` / `http_status` / `response_bytes` to immediate writes increases UPDATE volume from one per 50 responses to one per response. At 1 req/s (~ 3.6k/hour at peak) this is trivial, but verify Postgres write contention with `pg_stat_statements` once Stage 1 is live.
- **Single-URL mode (`-a urls=...`) currently bypasses the queue.** The dashboard's "rescrape this URL" buttons and any direct CLI invocation with `-a urls=...` create a `scrape_run` row but do *not* insert `scrape_url_items` rows. The live view derives everything from `scrape_url_items`, so without a fix it would render an empty in-flight panel for those runs — even though the dashboard is the most likely place a user clicks into them. **Fix in Stage 1:** the spider's `start()` upserts a `scrape_url_items` row for each URL passed via `-a urls=...` (status `pending`), which then flows through the same `processing → done|failed` lifecycle as a queued run. Treats every run uniformly; no special-casing in the dashboard.

## Verification

End-to-end checks (full detail in the implementation plan):

1. Migration up/down clean, new columns visible.
2. Healthy run: live view shows in-flight URL, dispatch delay (with provenance label), advancing rate counter.
3. Crash detection: `docker kill` mid-run; dashboard marks run "dead" within 30 seconds.
4. Stuck-request detection: hung URL fixture; dashboard shows "hung" while heartbeat remains fresh, then marks `failed`/dead according to existing timeout/close behavior (`DOWNLOAD_TIMEOUT`, `STALL_TIMEOUT`, the run's natural close path). No new automatic remediation in this spec.
5. JSONL log: one well-formed line per response, `jq` parses cleanly, `delay_source` field present and consistent with what the dashboard shows.
6. Smoke + unit + integration tests pass; ruff and mypy clean.

## Out of this spec

- Migration of the legacy Jinja run detail page (will be removed once React SPA is the default).
- Cross-run trend dashboards (per-day throttle distribution, error-rate heatmap) — possible follow-up once the per-run telemetry exists.

## Future work — throttle-aware retry (deferred)

A retry feature might be useful later, but the version originally drafted here was unsafe for two reasons (one mechanical, one architectural):

1. **Mechanical.** AUTOTHROTTLE's per-slot delay applies to the *next* dispatch, not the current one. By the time the middleware sees a high delay and decides to abort, the request is already on the way out. Re-queuing it doesn't help — when it's picked up again, the slot delay is still high (or higher, because the requeue burst added pressure). The retry would loop until `THROTTLE_RETRY_MAX` and then mark scrapeable URLs failed.
2. **Architectural.** Even if the mechanics were fixed, "high delay → retry" is the wrong heuristic. AUTOTHROTTLE backing off is usually AUTOTHROTTLE doing its job: slowing us down because the site is pushing back. Retrying amplifies the load pattern AUTOTHROTTLE was protecting against.

A defensible future retry feature would:

- Trigger on **multi-signal evidence of bad scrape state**, not on delay alone. Candidate symptoms (none authoritative individually):
  - Recent 200 responses with bodies far smaller than typical product pages (silent block).
  - Repeated redirects to homepage / category page (soft block).
  - Spike in timeout / connection-error rate within the last N requests.
  - High `failed_60s` rate on the same shop's most-recent runs.
- Treat retry as "**defer this URL and try again later**," not "retry immediately." Probably re-enqueue with an explicit cooldown rather than letting Scrapy pick it up on the next slot.
- Be confidence-gated: only fire when `delay_source = 'autothrottle_slot'` (verified by Gate A) — never on `httpx_observed` or `configured_delay`.
- Land in its own spec, with thresholds picked from observed data — not from this spec's guesses.

This spec captures the data such a future feature would need (`request_delay_s`, `delay_source`, `retry_count` column on the row, `response_bytes`, JSONL event log) but does not implement the feature itself.
