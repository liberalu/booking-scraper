# Single-Row Restarts + Auto-Retry Failed URLs

**Date:** 2026-05-09
**Status:** Approved (brainstorming → spec)

## Problem

Today, every time a scrape run stalls and re-spawns, a new `scrape_runs` row is created via `inherit_pending_items`. One logical scan can fan out to 5–10+ rows that all share the same intent. The dashboard shows them as separate runs, the timeline lives across rows, and operators have to mentally stitch them back together.

Separately, when a `scrape_url_item` fails for a transient reason (HTTP 5xx, timeout, parse error on a transient blip), it stays in `failed` status forever. There is no automatic retry — only manual operator intervention via the "Retry failures" button can re-queue those URLs.

## Goals

1. **One logical run = one `scrape_runs` row.** Process restarts (stall, heartbeat timeout, container reboot, operator Continue) mutate the existing row instead of creating a new one. Each restart appears as a `restarted` event on the row's timeline.
2. **Auto-retry failed URLs once at end of run.** Before marking the run `completed`, sweep `scrape_url_items` with `status='failed' AND attempts < 3` and re-queue them. Cap at 3 total fetch attempts per URL; capped items remain `failed` (sticky).

Validation issues (`validation_issues` table) are out of scope — items that fetched OK but failed pydantic validation are not retried.

## Non-Goals

- Per-shop retry cap configuration (cap is a single global constant).
- Per-`error_reason` retry filter (retry-all, no allowlist/denylist).
- Time-based cap reset (sticky failure stays sticky).
- Reset of `attempts` when a URL is re-discovered by the discover phase.
- Operator UI to bulk-reset `attempts` (manual SQL acceptable for now).

## Architecture

### Schema changes

**`scrape_url_items`** — new column:

```sql
ALTER TABLE scrape_url_items
  ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
```

Server default `'0'`. Counter increments atomically each time the item is claimed for fetch (existing `claim_scrape_url_item` UPDATE adds `attempts = attempts + 1` to its SET clause).

**`scrape_run_events`** — extend the `event_type` CHECK constraint to include `'restarted'`:

```sql
ALTER TABLE scrape_run_events
  DROP CONSTRAINT ck_scrape_run_events_event_type,
  ADD CONSTRAINT ck_scrape_run_events_event_type
    CHECK (event_type IN (
      'started','paused','resumed','stop_requested','retry_failures',
      'rerun','continued','resumed_after_failure','restarted',
      'completed','failed','subdivided'
    ));
```

`book_scraper/db/scrape_run_events.py`:

```python
RESTARTED: Final = "restarted"
```

`RESUMED_AFTER_FAILURE` constant kept for legacy event read-back; new code stops emitting it.

**Backfill:** none. Existing `attempts` defaults to 0 for all rows. Existing failed URLs become eligible for up to 3 auto-retries on first run after deploy. Acceptable one-time spike on shops with large failed backlogs (humanitas, patogupirkti). Documented in CLAUDE.md.

### Restart-in-place mechanism

**Where:** `book_scraper/services/scan.py::prepare_scan_create_run` and the matching path in `book_scraper/services/discover.py::DiscoverService`.

**Today**, when `find_resumable_run` returns a `failed` row with `resumable_after_failure=True`, the service calls `create_scrape_run` for a new row, emits `RESUMED_AFTER_FAILURE` on the new row, and `inherit_pending_items` re-points pending `scrape_url_items` from the old run to the new.

**New behavior:** mutate the existing row in place.

```python
resumable.status = "running"
resumable.finished_at = None
resumable.close_reason = None
resumable.resumable_after_failure = False
resumable.pid = os.getpid()
resumable.last_heartbeat = datetime.now(UTC)
```

Emit `restarted` on the same `run_id` with payload:

```json
{
  "previous_close_reason": "stall_timeout",
  "attempt": 3,
  "urls_processed_snapshot": 12345
}
```

`attempt` = count of prior `restarted` events on this run + 1. `urls_processed_snapshot` is captured for the zero-progress circuit breaker (see below).

Reset items: `reset_retryable_failures(session, run_id)` — extracted from `inherit_pending_items` — flips items with `error_reason IN ('run_aborted', 'stuck_in_processing', 'subdivision_5xx')` from `failed` to `pending`. The existing `reset_processing_scrape_url_items` handles in-flight items still in `processing`. Items already point to the same `run_id`; no cross-row repointing needed.

**Atomicity:** the mutation UPDATE and the `restarted` event INSERT happen in a single transaction. A crash between them would leave the row `running` with no `restarted` marker, breaking the circuit-breaker counts that key off event history.

**Idempotency:** if two processes race to mutate (advisory lock serializes them; second waits, then re-reads), the second observes `status='running'` from the first's mutation and takes the existing "resumable-running" branch — returns the same `run_id`, emits no event. The mutation is a no-op when the row is already in the target state.

`ScanPlan` / `DiscoverPlan` lose the `_inherit_from_run_id` field. The service returns the same `run_id` it found.

`started_at` is left untouched — it now reflects when the *logical* run first kicked off, across all process restarts. Cumulative counters (`urls_processed`, `items_added`, `errors_4xx`, `errors_5xx`) keep accumulating naturally on the row.

### Counter race during process handover

With the chain-row model, old and new processes wrote to *different* rows during the handover window — natural separation, no overlap. Single-row model removes that separation. After `StallDetector` fires, the old process can keep draining for up to `STALL_FORCE_EXIT_S=60s` (or longer if `PostgresPipeline` is backed up). During that window the new process may have already mutated the row to `running` and started incrementing the same `urls_processed` / `items_added` / `errors_*` counters.

**What's safe:** queue claims via `claim_scrape_url_item` are atomic (`UPDATE … WHERE status='pending' RETURNING …`), so the same URL is never double-processed. Each counter UPDATE is atomic per-statement, so concurrent increments don't corrupt the row.

**What can drift:** statistic counters may double-count by a small number (the items the dying old process processed during the overlap). Not corruption — additive drift bounded by what the old process can push through during ~60s of post-stall draining. Operators occasionally seeing `urls_processed > urls_total` is acceptable.

**Mitigation deferred:** see *Architectural alternatives considered → Process fencing*. Recommend monitoring for drift in production before adding fencing complexity.

### Subprocess respawn (unchanged)

The three restart triggers — `StallDetector` in `book_scraper/extensions.py`, `book_scraper/scripts/reconcile_runs.py` at container boot, and the dashboard `POST /api/runs/{id}/continue` endpoint — all keep spawning new `scrapy crawl` subprocesses via `subprocess.Popen(start_new_session=True)`. The behavior change is entirely inside the spawned process's service layer.

The Continue button keeps emitting `continued` (already exists). The auto-respawn paths emit `restarted`. Same row mutation in both cases; only the event type and actor differ.

**Continue endpoint:** `book_scraper/dashboard/routes/api.py::api_continue_run` already mutates the same row in place (flips `failed → running`, clears `finished_at` / `close_reason` / `pid`, emits `continued`) before spawning the subprocess. The spawned subprocess then hits `find_resumable_run` and matches the `status='running'` branch (Case A) which already reuses the row. **No code change needed for the operator path** — the only path changing is the auto-resume / boot-reconcile path that currently hits the `failed + resumable_after_failure` branch (Case B) and creates a new row. After this change, Case B mutates the same row instead.

### End-of-run retry

**Hook:** Scrapy's `spider_idle` signal fires when the scheduler queue is empty and there are no in-flight requests. Connect a handler in `book_scraper/spiders/scan.py` and `book_scraper/spiders/discover.py`:

```python
@classmethod
def from_crawler(cls, crawler, *args, **kwargs):
    spider = super().from_crawler(crawler, *args, **kwargs)
    crawler.signals.connect(spider._end_of_run_retry, signal=signals.spider_idle)
    return spider

def _end_of_run_retry(self):
    if self._end_of_run_retry_done:
        return  # already swept; let the spider close
    eligible = repo.fetch_retryable_failed(
        self.session, self._run_id, cap=RETRY_CAP
    )
    if not eligible:
        self._end_of_run_retry_done = True
        return
    repo.reset_to_pending(self.session, [item.id for item in eligible])
    for item in eligible:
        self.crawler.engine.crawl(self._build_request(item))
    self._end_of_run_retry_done = True
    raise DontCloseSpider
```

`fetch_retryable_failed(session, run_id, cap)` — new repo helper. Returns `scrape_url_items WHERE run_id=:run_id AND status='failed' AND attempts < :cap`. No filter on `error_reason`.

`reset_to_pending(session, item_ids)` — flips `status` to `pending` for the given ids. Does not touch `attempts` (that ticks on the next claim).

`RETRY_CAP` — constant `3` in `book_scraper/settings.py`. Applied as the `cap` argument. Not configurable per shop.

**Loop guarantee:** `_end_of_run_retry_done` is a per-spider-instance flag. Set after the first sweep regardless of whether items were re-queued. Second `spider_idle` fire (after the retry pass drains) returns immediately and the spider closes naturally.

**Counter increment:** the existing `claim_scrape_url_item(session, run_id)` does an atomic `UPDATE scrape_url_items SET status='processing' WHERE id=… AND status='pending' RETURNING …`. Add `attempts = attempts + 1` to the SET. One increment per fetch attempt — initial fetch counts as attempt 1, each retry pass increment makes 2, 3.

**Restart interaction:** if the process dies during the retry pass, items currently `processing` are caught by `reset_processing_scrape_url_items` on next restart and flipped to `pending` (their `attempts` already incremented from the claim). The new process's `_end_of_run_retry_done` resets — second sweep on the new process finds either no eligible items (retried already) or only fresh ones. No double-charge of `attempts`.

### Retry storm risk

On shops with large failed-URL backlogs (humanitas had ~1k+ at last count, similar magnitude possible on patogupirkti), the first post-deploy retry sweep adds significant tail to the run. FlareSolverr-backed shops average 5–10s/request → 1k retries at concurrency=2 = ~1.5–3 hours of retry tail alone. Risks:

1. **Heartbeat timeout mid-sweep** if a single retry stalls past `STALL_TIMEOUT=180s`. Existing stall handling kicks in normally (mutation, `restarted` event, resume).
2. **Run never completes if every restart triggers a fresh retry attempt for the same items.** Bounded by the `attempts < 3` cap — at most 3 fetches per URL across all restarts/sweeps within a logical run. Finite.
3. **Cron schedule overlap** — if the run's tail extends past the next cron tick, the next scheduled run for the same shop+phase observes the lock held and exits cleanly (existing `try_acquire_*_lock` behavior).

**Mitigation:** none built-in for the first deploy. Operator action if needed: temporarily set `attempts=3` on a subset of stale failures via SQL to grandfather them as exhausted, or adjust per-shop concurrency. Document this in CLAUDE.md after deploy.

**Future option (deferred):** cap sweep batch size per pass (e.g. retry up to N items per sweep, leave overflow for the next run's sweep). Adds complexity; defer until we see a real problem.

### Circuit breakers

**Auto-restart cap (`STALL_AUTO_RESUME_MAX=3`):** counts `restarted` events on the run instead of walking a chain via `previous_run_id` payloads. `count_auto_resume_chain_depth` in `book_scraper/db/repo.py` refactored to count events on one row. When cap reached, auto-respawn is skipped, row stays `failed`, operator must hit Continue.

**Zero-progress circuit breaker (threshold=2):** compares `urls_processed_snapshot` across the two most recent `restarted` events. If both restarts fired with the same snapshot value (no progress between them), bail out and leave the row `failed`. `count_consecutive_zero_progress_resumes` in `book_scraper/db/repo.py` updated to read the new payload field.

**Manual Continue bypasses both caps:** operator click is an explicit override.

### Dashboard

**Run list page:** structurally unchanged. Side effect — fewer rows, less noise.

**Run detail → Timeline card:** existing component renders `scrape_run_events` rows. Add an icon and tooltip for `restarted` events (e.g. ↻ glyph), distinct from the legacy `resumed_after_failure` (▷). Tooltip surfaces `previous_close_reason`, `attempt`, `urls_processed_snapshot` from the payload.

**Legacy chain-rendering compatibility:** pre-deploy data has `RESUMED_AFTER_FAILURE` events on per-restart rows with `previous_run_id` payloads pointing back across the chain. Whatever the dashboard does today to stitch chained rows into one logical timeline (lookup by `previous_run_id`, JOINs across `scrape_runs`) stays in place — read-only support for historical runs. New runs after deploy generate single-row events and don't exercise the chain-stitching path. Two render branches coexist; legacy path can be retired later once historical runs are no longer interesting.

**Run detail → Failures card:** add an `attempts` column (e.g. "2/3"). Capped items (`attempts=3`) get a visual marker (red lock icon) signalling that auto-retry is exhausted.

**Run summary header:** `started_at` reflects logical run start. If the run has at least one `restarted` event, add a secondary line "Last restart: <Yh ago>". Duration = `(finished_at or now) - started_at`, total wall time across all process attempts.

**Continue button:** API and UI unchanged. Mutates same row, emits `continued`.

**Retry-failures button** (`POST /api/runs/{id}/retry-failures`): when operator-triggered, **resets `attempts` to 0** for the failed items being re-queued. Manual click is an explicit operator decision to give another chance and bypasses the cap.

### Reaper / freshness logic

`mark_stale_runs_failed` and any code that judges run freshness must key off `last_heartbeat`, not `started_at` — `started_at` no longer indicates how recently the process was alive. Implementation step: grep for `started_at` reads in reaper paths and switch any that meant "process boot time" to `last_heartbeat`.

## Migration

One Alembic revision:

1. `ALTER TABLE scrape_url_items ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0` (server_default `'0'`).
2. Drop and re-add `ck_scrape_run_events_event_type` with `'restarted'` in the allowed list.

No data backfill. Idempotent.

**In-flight runs at deploy time:** any run currently `running` during scraper container restart is flipped to `failed/orphan_on_boot` with `resumable_after_failure=True` by `reconcile_runs.py`. The next scrapy spawn picks it up and mutates the same row to running. One bonus `restarted` event lands on the row, no data loss.

**Roll-back:** if reverting the migration is needed, drop the constraint first (so post-deploy `restarted` events don't block the column drop), then drop the `attempts` column. Code revert is a `git revert`.

## Testing

**Unit** (no DB):

- `services/scan.py` and `services/discover.py` restart-mutation: same `run_id` returned, fields cleared correctly, `restarted` event emitted with correct `attempt` and `urls_processed_snapshot`.
- `reset_retryable_failures` resets only `run_aborted`/`stuck_in_processing`/`subdivision_5xx`; leaves other failed reasons alone.
- End-of-run retry hook: handler re-queues eligible items, raises `DontCloseSpider` once, no-ops on the second idle.
- Cap respected: items with `attempts=3` excluded from sweep.

**Integration** (real DB on port 5433):

- Stall simulation: mark run `failed`+`resumable_after_failure`, run service, assert same row mutated, `restarted` event added.
- 3 simulated stalls: 4th respawn refuses (cap), row stays `failed`.
- Zero-progress: two restarts with identical `urls_processed_snapshot`, third refuses.
- End-of-run retry e2e: seed failed items with mixed `attempts` counts, run scan with stub fetcher, assert eligible items retried, capped items skipped, `completed` event emitted only after the retry pass.
- Migration: backfill leaves `attempts=0` everywhere; existing failed items eligible for retry on first post-migration run.
- Continue button: mutates capped run back to `running`.

**Smoke** (post-deploy, per CLAUDE.md):

- `uv run pytest tests/integration/test_dashboard_routes.py -v`.
- Trigger short scan: `scrapy crawl scan -a shop=vaga -a max_urls=5`. Confirm one run row, no errors.
- Force a stall (set `STALL_TIMEOUT=10s` on dev): confirm same row mutated, `restarted` event lands on the timeline.

## Architectural alternatives considered

**Process fencing (deferred).** Add `process_token UUID` column on `scrape_runs`. New process writes a fresh token on mutation. Pipeline UPDATEs add `WHERE process_token = :my_token`. Old process's writes become no-ops once the new token replaces it, eliminating counter drift entirely. **Cost:** every counter UPDATE gains a token check; pipeline code touched in many places; small added schema surface. **Decision:** defer. Counter drift bounded by the ~60s overlap window is too small a problem to justify the complexity. Revisit if production drift exceeds cosmetic levels.

**Persisted retry-pass-done flag (rejected).** Store `retry_pass_completed BOOLEAN` on `scrape_runs` rather than the per-process in-memory `_end_of_run_retry_done` flag. Survives process death, never re-fires. **Problem:** if the process died mid-sweep, persisted-true would skip remaining failed items. Currently the in-memory flag re-fires per process and the `attempts < cap` guard makes the total work finite (≤ cap fetches per URL per logical run). **Decision:** keep in-memory.

**Separate retry phase (rejected).** Instead of a `spider_idle` hook, run a dedicated `retry` phase as its own scrapy spawn after `scan` completes. Cleaner separation of concerns. **Cost:** additional phase to maintain, additional spawn, additional row in `scrape_runs` if naively implemented (or this design's mutation logic again, but for a different phase). **Decision:** keep the hook — single-process cohesion is cheaper.

**Reuse `continued` for auto-restart (rejected).** Drop the new `restarted` event type; differentiate auto vs operator restarts by the existing `actor` field on `scrape_run_events`. **Cost:** circuit-breaker queries that count auto-restarts must filter by payload/actor — less indexable, harder to read in raw event logs. **Decision:** keep `restarted` as a distinct event type for clarity and queryability.

**Display-only collapse of chain rows (rejected upstream).** Considered during brainstorming as Approach C — keep the chain-row model unchanged, group rows in the dashboard for display. Operator preferred true single-row semantics so all downstream queries (counters, durations, "current state") work without aggregation gymnastics.

**`scrape_run_attempts` child table (rejected upstream).** Considered as Approach B during brainstorming — parent `scrape_runs` row immutable per logical run, child rows per process attempt. Audit-friendly but every read query touching process state needed updating. The existing `scrape_run_events` table already provides the per-attempt audit trail in lighter form.

## Open Questions

None at spec time. Items deferred to "Out of scope" / "Non-Goals" / "Architectural alternatives considered" are explicit decisions, not unresolved questions.
