# Live Observability — Follow-up Tasks

**Date:** 2026-04-26 (amended after corner-case review)
**Spec:** `docs/superpowers/specs/2026-04-26-live-scrape-observability-design.md`
**Plan:** `docs/superpowers/plans/2026-04-26-live-scrape-observability-plan.md`
**Shipped in:** PR #3 (commits `0ac3256`, `9762a6b`, `193fa29`) + PR #4 (throttle fix) + PR #5 (UI label / docs) + PR #6 (httpx client rotation) + PR #7 (per-shop reset config) + `b934f0f` (abort-processing-on-terminal)

The observability work landed end-to-end. These items came up during implementation, Stage 0 verification, the post-merge zombie-run incident (run 173), the post-throttle-fix stall (run 178), and a corner-case review of the shipped code.

Items numbered 1–10 are from the original write-up. Items 11–18 surfaced during the corner-case review and are likely the more impactful next steps.

---

## P1 — Real bugs

### 1. `HttpxMiddleware` silently bypasses `DOWNLOAD_DELAY` and AUTOTHROTTLE — ✅ **CLOSED**

**Status:** Fixed in the `claude/throttle-fix-and-times` follow-up PR. Per-host pacing is now enforced inside `HttpxMiddleware` itself with an `asyncio.Lock` (one in-flight per host = `CONCURRENT_REQUESTS_PER_DOMAIN = 1` semantics) and an adaptive delay that drifts toward `response_latency / TARGET_CONCURRENCY`, bounded by `DOWNLOAD_DELAY` (floor) and `AUTOTHROTTLE_MAX_DELAY` (ceiling). Smoke confirmed `request_delay_s` records actual sleeps and `delay_source='autothrottle'`. Below kept for historical context.

**Source:** Stage 0 Gate A probe — surveyed 30 requests, observed `request.meta['download_slot']` was `None` on every dispatch and inter-dispatch intervals were 3–50 ms in tight bursts despite `DOWNLOAD_DELAY = 2.0` and `AUTOTHROTTLE_ENABLED = True`.

**Symptom:** the spider runs at host speed, not the configured pace. The "1 req/s with adaptive backoff" the project assumes is fictional. Every shop is exposed to bursty access patterns regardless of settings.

**Why:** `HttpxMiddleware.process_request()` (`book_scraper/download_handler.py`) returns an `HtmlResponse` directly. This skips Scrapy's normal downloader handoff, so:
- `request.meta['download_slot']` is never populated
- `response_downloaded` signal never fires
- `AutoThrottle` extension has no slot to update
- Scrapy's per-domain rate limiter is bypassed

**Fix options (pick one):**
- **A. Pace explicitly inside HttpxMiddleware.** `asyncio.sleep` based on a per-domain `last_dispatch_at` map, with a configurable per-shop delay (already supported by `DOWNLOAD_DELAY` semantically; just enforce it ourselves). Loses adaptive throttling but trivial to implement.
- **B. Re-emit Scrapy's signals from HttpxMiddleware.** Manually fire `request_reached_downloader` and `response_downloaded` so `AutoThrottle` keeps working. More work; couples us to Scrapy internals.
- **C. Replace HttpxMiddleware with Scrapy's native downloader.** `HttpxMiddleware` was added because Twisted's HTTP client hangs on vaga.lt after ~120 requests. Investigate whether a connection-keepalive fix or `scrapy-playwright` would solve the underlying issue without bypassing the engine.

**Priority:** P1. The site is not currently being protected by the throttling we believe is active. Operators have been seeing 67-URL bursts in <100 ms (per the Gate A probe).

**Effort:** Option A is ~1 hour. Option C is days.

**Blocks:** the deferred throttle-retry feature (per the observability spec's Future Work) — that feature requires AUTOTHROTTLE actually working, i.e., this fix landing first.

---

### 2. Live view detects "dead" in 30 s; the run-row stays `running` for 30 minutes

**Source:** post-merge cleanup of zombie run 173.

**Symptom:** when a spider dies forcibly (SIGKILL, container recreate, OOM), the live view correctly shows the run as "dead" within 30 s of the heartbeat going stale, but `scrape_runs.status` stays `running` and `finished_at` stays `NULL` until the dashboard reaper fires — which has a 30-minute threshold (`DEAD_RUN_MINUTES = 30`). During that window:
- The run-list page shows the run as "running" (using the run-list health check, not the live view)
- The reaper-driven `abort_processing_scrape_url_items` (from `b934f0f`) doesn't fire, so 17 stuck `processing` rows hang on
- New runs see the zombie as "still running" and skip work that should re-queue

**Why:** the live view's threshold is intentionally sharp (operator UX during an active run) while the reaper's threshold is intentionally conservative (don't false-positive on a slow heartbeat tick). They were designed independently; their thresholds are now disconnected.

**Fix:** couple them. If the live view treats heartbeat-stale-by-30s as "dead", that's also when the reaper should mark the row failed and abort processing rows.

Concretely:
- Split thresholds explicitly: keep `DEAD_RUN_MINUTES = 30` only for the run-list page's coarse "stale" badge; add `DEAD_RUN_SECONDS = 60` for the reaper's actual transition. Live view stays at 30 s as the visual signal, reaper acts at 60 s. The 30 s gap absorbs heartbeat-tick lag.
- Run the dashboard background reaper every 30 s (currently it appears to run on demand only — confirm + fix).
- Don't have the live view mutate state itself. Polling endpoints should be read-only; mixing read + write makes them harder to test and prone to N concurrent dashboards racing on the same row.

**Corner cases the simple fix misses:**
- **Spider-vs-reaper race.** The reaper marks a run `failed` based on stale heartbeat; meanwhile the spider that "looked dead" was just blocked on a slow synchronous parse and resumes 5 s later. It then writes to a run row that's already `failed`. **Fix:** every spider write that touches `scrape_runs.status` or `scrape_url_items` for a run should re-check the run's status under the same transaction and abort if it's terminal. Cheapest: add a `WHERE status = 'running'` clause to the heartbeat UPDATE; add a guard in `_mark_response` that no-ops on terminal runs.
- **Heartbeat ticks after reaper marks failed.** Heartbeat extension keeps writing `last_heartbeat` even after the reaper transitioned the run to `failed`. The status stays `failed` (we only update last_heartbeat) but the row looks "alive" again, which can confuse a second reaper pass. **Fix:** heartbeat extension UPDATE must include `WHERE status = 'running'`.
- **Concurrent reaper runs (multi-process safety).** If two dashboard processes run reapers simultaneously (current setup has 3+ dashboards from other worktrees), both could try to fail the same run. The UPDATE is naturally idempotent if the WHERE clause filters on `status='running'`, but the abort-processing helper isn't — it stamps `done_at = now()`, which would be re-stamped by the second reaper. **Fix:** add `AND done_at IS NULL` to `abort_processing_scrape_url_items` so the second reaper is a no-op.
- **Slow `prepare_scan` on cold cache.** `create_scrape_run` flips status to `running` immediately, but `prepare_scrape_url_items` can take 30+ s on first run (~3,000 row inserts). During this time the heartbeat extension hasn't started yet (it waits for `run_started`, which fires AFTER `_run_id` is assigned and the queue is loaded). A reaper with a 60 s threshold could mark the run dead before the spider's first request ever goes out. **Fix:** emit `run_started` immediately after `create_scrape_run` returns (before queue prep), so heartbeat ticks during queue setup. OR: have `create_scrape_run` set `last_heartbeat = now()` (it already does) and the reaper's age check uses `max(last_heartbeat, started_at)`, so a young run with just `started_at` set isn't reaped.
- **Timezone drift.** Comparing `last_heartbeat` (timezone-aware) against `now()` requires both to be UTC. Existing code is mostly careful but not consistently. A test that pins it would prevent a regression.
- **Reap-then-resume contract.** After reaper marks a run `failed`, the next scheduled scan should resume from the queue. `find_resumable_run` looks for `status='running'` runs only — it won't pick up the `failed` one's pending rows. The `pending` rows of run 173 are still there (~2,800 of them), but no future run sees them. **Fix:** when reaper transitions to `failed` due to stall (vs. genuine failure), a new run should inherit the queue. Already partly addressed by item #10's auto-resume idea.

**Priority:** P1. It's the difference between "the dashboard told me my run died and the data is consistent" vs. "the dashboard told me my run died but the queue still thinks it's running for 28 more minutes."

**Effort:** the simple version (split thresholds + 30 s reaper cadence) is ~30 minutes. The full corner-case fix (status-guard on heartbeat + WHERE clauses + queue inheritance) is ~3 hours. Worth doing the full version — partial fix leaves real bugs.

---

## P2 — Improvements

### 3. Boot reconcile only catches pre-boot orphans

**Source:** post-merge zombie run 173.

**Context:** `mark_orphan_runs_failed` runs in the scraper container's entrypoint. It marks every `running` row failed at boot. But run 173 was *created after* the new container's entrypoint had already passed reconcile — likely by another worktree's dashboard hitting the shared Postgres, or a background subprocess that started post-boot. The boot-time reconcile is blind to anything created after it ran.

**Why this matters:** in a single-machine setup with multiple worktrees sharing the DB, or with the dashboard's `/scrape` POST route fork-and-forgetting subprocesses, "boot orphan" is the wrong abstraction. Orphans can appear at any time.

**Fix:** rely on the dashboard reaper exclusively (which runs continuously, not just at boot) — covered by the fix in #2 above. The boot-time `mark_orphan_runs_failed` becomes redundant once the reaper is fast enough.

**Priority:** P2. Subsumed by #2 if that fix lands.

---

### 4. Stage 1 unit tests not landed

**Source:** the original plan listed `tests/unit/test_heartbeat_extension.py`, `tests/unit/test_events_log.py`, and `tests/unit/test_batch_ownership.py`. None were added in the Stage 1 commit. Stage 2's `tests/integration/test_run_live_route.py` (7 tests) is the only new test file in PR #3.

**What's missing:**
- `HeartbeatExtension`: assert tick fires after `run_started`, no tick before, clean shutdown on `spider_closed`, DB error swallowed
- `event_log.log_response_event`: writes valid JSONL, all fields present, file-write failure swallowed
- `mark_scrape_url_item_response`: idempotent, sets correct fields per success/failure, doesn't touch unaffected columns
- Batch ownership: calling `flush_progress` doesn't modify `scrape_url_items.status`/`done_at`/`http_status` (pins the ownership split from drifting)

**Priority:** P2. The integration tests cover the path end-to-end, but a regression in (say) `mark_scrape_url_item_response`'s field-update logic would only be caught by running the full live-route test suite. Unit tests would localise failures and fail faster.

**Effort:** ~2 hours.

---

### 5. Verify DB statement timeout actually works on the heartbeat session

**Source:** plan's Open Questions / Risks.

**Context:** `HeartbeatExtension` uses `SET LOCAL statement_timeout = '2s'` to ensure a hung Postgres can't pile up ticks. SQLAlchemy + psycopg2/asyncpg may or may not surface the timeout as a clean exception depending on driver. We assumed it works; never proved it.

**Test:** simulate a slow query (`pg_sleep(5)` injected into the heartbeat path), confirm the heartbeat tick fails fast at 2 s and the next tick still fires.

**Corner cases:**
- **Connection pool reuse.** `SET LOCAL` is scoped to the transaction. Each heartbeat tick gets a fresh transaction (we commit after the UPDATE), so the timeout is correctly applied each time. ✓
- **Stale connection in pool — see new item #11.** If the connection is dead before we `SET LOCAL`, the SET itself fails. The exception path swallows it; next tick gets a different connection. As long as `pool_pre_ping` is on, this is fine. With `pool_pre_ping = False` (current state), a dead connection silently fails the heartbeat indefinitely until the pool eventually evicts it.
- **Driver-level timeout vs SET LOCAL.** psycopg2's `connect_timeout` and statement_timeout are separate. A connection that's hung in the OS-level TCP layer (server stopped responding mid-handshake) waits up to `connect_timeout` first. Combined with the 2 s statement timeout, a tick could take up to ~10 s in worst case. Acceptable but worth knowing.

**Priority:** P2. Defensive — only matters if Postgres ever genuinely hangs.

**Effort:** ~30 minutes.

---

### 6. Confirm immediate-write throughput at scale

**Source:** plan's Open Questions / Risks.

**Context:** Stage 1 switched from one batched `UPDATE scrape_url_items` per 50 responses to one `UPDATE` per response. At 1 req/s this is trivial. At higher rates (or if the throttling bug #1 stays unfixed and the spider runs at host speed), the write volume could matter.

**Test:** after a few hours of production runs, query `pg_stat_statements` for the `mark_scrape_url_item_response` UPDATE — check call count, total time, mean time. Compare against the `flush_progress` cluster.

**Priority:** P2. No symptoms yet; prophylactic check.

**Effort:** ~15 minutes once data has accumulated.

---

## P3 — Future work

### 7. Throttle-aware retry (per spec's "Future work" section)

**Source:** observability spec's Future Work section.

**Original plan:** Stage 3 in the staged plan, dropped before implementation because:
- Mechanically broken in this codebase (slot delay applies to *next* dispatch, not current)
- Architecturally suspect even if mechanics were fixed (high delay = AUTOTHROTTLE protecting us; retrying amplifies the load)

**A defensible future version would:**
- Trigger on multi-signal evidence of bad scrape state (silent block / soft block / error-rate spike), not delay alone
- Be confidence-gated on `delay_source = 'autothrottle_slot'` (which currently never happens — see #1)
- Treat retry as "defer + try again later" with explicit cooldown, not "retry immediately"
- Land in its own spec with thresholds picked from observed data

**Block list:** depends on #1 being fixed first (`delay_source` needs to actually become `autothrottle_slot` for any retry signal to be trustworthy).

**Priority:** P3. Speculative. Don't start until #1 lands and we've watched a few weeks of `delay_source` data.

---

### 8. Per-shop dashboard label customisation

**Source:** observability spec's Risks section ("UI labelling").

**Context:** the dashboard currently labels all delays as "dispatch delay (observed)" because Gate A failed for vaga.lt. If a future shop is added where AUTOTHROTTLE *does* update correctly (e.g., a shop scraped via Scrapy's native downloader, not HttpxMiddleware), the label should switch to "throttle delay (verified)" automatically. The `delay_source` column already supports this; only the React component's `delaySourceLabel` mapping needs to be aware of the per-row source.

Already implemented in `hf-runs.jsx` — verify when a non-vaga shop is added.

**Priority:** P3. Cosmetic; the UI already handles all three values, just not exercised yet.

---

## P1 — Just-surfaced (post-throttle-fix)

### 10. vaga.lt rate-limits us after ~100 requests; httpx hangs silently

**Source:** PR #4 smoke run (run 178) hit a 220-second silence after exactly 100 successful responses, followed by `StallDetector` firing.

**Symptom:** scan completes ~100 URLs successfully, then httpx requests hang (no response, no immediate error). My adaptive throttle ratchets `current_delay` to the `AUTOTHROTTLE_MAX_DELAY` ceiling on the first timeout, so subsequent attempts are 30 s sleep + 60 s `HARD_REQUEST_TIMEOUT_S` = 90 s/attempt. After 2–3 back-to-back hangs, `STALL_TIMEOUT = 60 s` (with my throttle's overshoot) makes `StallDetector` fire and the run is correctly marked failed at the spider level — but ~2,400 URLs of the queue remain unprocessed.

**Note from history:** the existing code comment says *"Twisted's HTTP client hangs on some servers (e.g. vaga.lt) after ~120 requests. This middleware intercepts all requests and uses httpx async client, which handles the same requests without issues."* The httpx switch shifted the wall from ~120 to ~100, but the wall is still there. The underlying issue is on the server side, not the client.

**Possible mitigations:**
- **Connection rotation.** Force httpx to drop and re-open the connection every N requests (we already set `Connection: close`, but maybe httpx is reusing the underlying socket pool anyway). Combine with an explicit `httpx.AsyncClient` reset every ~80 requests.
- **IP rotation.** Proxy the requests through a rotating-IP service. Heavyweight; only worth it if scrape volume justifies the cost.
- **Auto-resume on stall.** When `StallDetector` fires, mark the *run* as needing-resume rather than `failed`, and let the next scheduled run pick up the remaining `pending` rows. The existing `find_resumable_run` machinery already supports this — just don't transition to `failed` on `stall_timeout`.
- **Cool-down + retry the run itself.** After a stall, schedule a fresh run for the same shop in N minutes (vaga.lt's rate limit appears to be transient — a new run after a pause works again).

**Priority:** P1. The scraper currently can't complete a full ~3,000-URL run for vaga.lt in a single attempt without hitting this wall.

**Effort:** auto-resume on stall is the cheapest win — ~1 hour. Connection rotation is ~1 day of investigation. IP rotation is a project.

**Surfaced by:** the live observability work (PR #3) made the stall pattern visible in real time. Without `recent_activity` and the JSONL log, "scan ran for 7 minutes then stopped" would have been the only signal.

---

## Cleanup

### 9. Stash on main repo: `pre-PR3-merge: superseded observability draft`

Local stash created during the PR #3 merge to preserve a stale local draft of the same observability work (older naming: `autothrottle_delay_s` instead of `request_delay_s`, no `delay_source` column). Superseded by what landed.

**Action:** `git -C /Users/evaldas/projects/book-scraper stash drop` once you're sure nothing in there is worth recovering.

---

## P0 / P1 — Surfaced by corner-case review

These weren't in the original write-up. Several are root causes of bugs we already chased; landing the fixes preemptively would close the underlying class of issues, not just specific symptoms.

### 11. SQLAlchemy engine has no `pool_pre_ping` — stale connections silently fail

**Source:** root cause of run 178's `psycopg2.OperationalError: server closed the connection unexpectedly` mid-run. Engine config in `book_scraper/db/session.py` sets `connect_args` for `idle_in_transaction_session_timeout` but does NOT enable `pool_pre_ping`.

**Symptom:** SQLAlchemy's pool keeps connections warm for reuse. Postgres or any intermediate (firewall, NAT, kernel TCP timeout) can drop an idle connection silently. The next time SQLAlchemy hands that connection out, the first query gets `OperationalError: server closed the connection unexpectedly`. The exception bubbles up, the spider's pipeline dies mid-write, the run is marked `failed` for what looks like a Postgres outage but is actually just a stale TCP socket.

**Why it's bigger than just the heartbeat:** every per-response `mark_scrape_url_item_response` opens a session, every flush_progress, every dashboard query. All of them are exposed.

**Fix (one-liner):**
```python
return create_engine(
    sync_url,
    pool_pre_ping=True,   # validate connection before checkout
    pool_recycle=300,     # close idle connections after 5 min
    connect_args={"options": "-c idle_in_transaction_session_timeout=300000"},
)
```

`pool_pre_ping` issues a tiny `SELECT 1` before handing out a pooled connection. If it fails, the connection is dropped and a fresh one is created. ~1 ms overhead per checkout, eliminates this entire failure class. `pool_recycle=300` proactively rotates connections every 5 min so they don't go stale to begin with.

**Corner case:** the dashboard's FastAPI engine may be configured separately. Check `book_scraper/dashboard/deps.py` for `get_engine` or similar — apply the same options there.

**Priority:** P1. The `OperationalError` we saw is a textbook symptom; this is one of the most common SQLAlchemy production gotchas. Should have been there from day one.

**Effort:** 5 minutes for the engine config + 5 minutes to verify on a long-running scan.

---

### 12. JSONL events log path is CWD-relative

**Source:** `book_scraper/event_log.py` defaults to `Path("logs/scrapy_events.log")`.

**Symptom:** if scrapy is invoked from a directory other than the project root (e.g., from a cron job that doesn't `cd /app` first, or via Docker exec from `/`), `logs/scrapy_events.log` is created next to wherever scrapy happened to start. We've been "lucky" because cron does `cd /app` and the dashboard subprocess inherits CWD. One mis-configured cron line and events vanish into a tmp directory.

**Fix:** resolve to an absolute path at module load time, anchored to the project root:

```python
_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # book_scraper/event_log.py → repo root
_DEFAULT_LOG_PATH = Path(
    os.environ.get("SCRAPY_EVENTS_LOG", _PROJECT_ROOT / "logs" / "scrapy_events.log")
)
```

The env var override stays in place for tests / staging.

**Priority:** P2. Latent failure; will only bite when something changes the invocation path.

**Effort:** 5 minutes.

---

### 13. JSONL log has no rotation — appends forever

**Source:** `event_log.py` opens with mode `"a"` and writes one line per response. No rotation, no size cap.

**Math:** at 1 req/s a record is ~250 bytes → ~22 MB/day → ~660 MB/month → multi-GB/year. Eventually fills the volume.

**Fix options:**
- **Logrotate.** Add `/etc/logrotate.d/scrapy_events` to the scraper Dockerfile (daily, keep 14, compress). Standard, no code change.
- **Python `RotatingFileHandler`.** Wrap the writer in a logging.handlers.RotatingFileHandler with `maxBytes=100MB`, `backupCount=10`. Application-level, more portable.
- **Switch to logging module entirely.** The current code uses raw `path.open("a")`. Routing through stdlib `logging` would let the existing log config (already in `settings.py`) handle rotation. Cleanest but requires re-plumbing.

**Recommended:** logrotate. Zero code change, OS-standard, works the same whether scrapy is run via cron or interactively.

**Corner case:** rotation while a write is in progress. Logrotate uses `copytruncate` or a SIGHUP signal. We don't handle SIGHUP; copytruncate is safe (writer keeps appending to the new file via the same fd; old file gets truncated). Use `copytruncate`.

**Priority:** P2. Disk-fill is months away; not urgent but should be set up before the first multi-week scrape.

**Effort:** 10 minutes (logrotate) or ~1 hour (`RotatingFileHandler` + tests).

---

### 14. Concurrent JSONL writes are not guaranteed atomic for large records

**Source:** `event_log.log_response_event` opens the file, writes one line, closes. Multiple async coroutines (or worse, multiple OS processes — dashboard subprocess + cron-fired scan) can write simultaneously.

**Symptom:** POSIX guarantees atomic appends only for writes < `PIPE_BUF` (4 KB on Linux). Our records average ~250 bytes — safe. But a record with a long URL or `error_reason` could exceed 4 KB on Windows or non-Linux. Two concurrent writes could interleave bytes, corrupting both records.

**Fix:** add an `asyncio.Lock` (or `threading.Lock` for cross-thread; `multiprocessing.Lock` for cross-process). Easiest: one global lock in `event_log.py` since the function is called from the spider's event loop. Multi-process is unlikely in our setup but worth noting.

```python
_write_lock = asyncio.Lock()  # or threading.Lock for sync paths

async def log_response_event(...):
    async with _write_lock:
        # write
```

Wait — `log_response_event` is currently sync, called from spider's `_mark_response`. If the spider is async-only, switch the lock. If it can be called from sync paths (e.g., `closed()`), use threading.

Easier alternative: open in `O_APPEND | O_DSYNC` mode and accept the kernel's append guarantee for typical record sizes. POSIX `O_APPEND` is atomic for any size if the filesystem supports it (ext4 does on Linux). Cross-process, cross-thread safe.

**Priority:** P3. No reports of corruption yet; record sizes are well below the safe threshold. Worth adding as belt-and-braces before a high-throughput shop is added.

**Effort:** 15 minutes.

---

### 15. Heartbeat blackout window during slow `prepare_scan`

**Source:** code-path review while writing item #2's corner cases.

**Symptom:** sequence is:
1. `create_scrape_run` — DB row created with `status='running'`, `last_heartbeat=now()`.
2. `prepare_scrape_url_items` — inserts ~3,000 rows into `scrape_url_items`. Takes 5–30 s on cold cache.
3. Spider yields its first request — `run_started` signal fires, heartbeat extension starts ticking.

Between step 1 and step 3 is a heartbeat blackout — `last_heartbeat` is fixed at the timestamp from step 1. If a reaper with a 60 s threshold polls during a slow step 2, the run looks dead (no fresh heartbeat for 30+ s) and gets failed prematurely.

**Fix:** emit `run_started` immediately after `create_scrape_run`, before `prepare_scrape_url_items`. Heartbeat ticks during queue prep. The sole prerequisite for `run_started` is that `_run_id` is set, which happens at step 1 — there's no reason to wait until step 3.

**Alternative:** the reaper could compute "age" as `now() - max(last_heartbeat, started_at)` and require the run to be at least 60 s old (instead of just stale-by-60s). Same effect, slightly cleaner.

**Priority:** P1. Becomes urgent once item #2 lands and the reaper runs every 30 s with a 60 s threshold — that's exactly when this race becomes visible.

**Effort:** 15 minutes.

---

### 16. Multi-shop concurrent scans against the same shop double the load

**Source:** code review of `HttpxMiddleware`'s per-host lock.

**Symptom:** the per-host lock is per-`HttpxMiddleware` instance. Each Scrapy process gets its own instance. If two Scrapy processes both scrape vaga.lt simultaneously (e.g., dashboard fires a /scrape POST while cron runs the scheduled scan), each holds its own lock — vaga.lt sees 2× the request rate.

**Fix:** the `find_resumable_run` mechanism already prevents two `running` runs for the same shop+phase from co-existing. Surface it as a hard guard in `prepare_scan`: if a `running` run already exists, exit cleanly with a clear log message instead of just resuming. Today the second invocation tries to resume the first run's queue, which is correct but the two scrapy processes both write to the same run — they're not coordinated.

Concrete fix: in `prepare_scan`, after `find_resumable_run`, also lock-check. If another process is already running, exit early. Use Postgres advisory locks (`pg_try_advisory_xact_lock`) for cross-process serialization — single-machine, no extra infra.

**Priority:** P2. We've already seen this happen (run 173 was created by some cross-worktree subprocess while run 172 was being killed). Symptom = doubled effective load on vaga.lt = sooner stall.

**Effort:** ~1 hour (advisory lock + integration test).

---

### 17. Spider's `_progress_session` is long-lived without recycle

**Source:** code review of `book_scraper/spiders/scan.py`.

**Symptom:** the spider creates `_progress_session` on first response and reuses it for all subsequent flushes + final close. Sessions hold a connection from the pool. With our throttle (1 req/s) and 50-response batch, the session is "active" for ~100 s between flushes — well within `idle_in_transaction_session_timeout`. But on a long run (hours) the connection ages and could go stale (same root cause as item #11).

**Fix:** combination of #11 (`pool_pre_ping=True`) + a defensive recreate every N flushes:

```python
def _flush_progress(self):
    if self._progress_session is not None and self._urls_responded % 500 == 0:
        self._progress_session.close()
        self._progress_session = None
    if self._progress_session is None:
        ...
```

Or: just rely on item #11 — `pool_pre_ping` makes recycling unnecessary because dead connections are caught at checkout.

**Priority:** P3. Subsumed by #11 in practice. Worth mentioning so we don't forget the long-lived session exists.

**Effort:** 0 if #11 lands; 15 minutes for explicit recycle if needed.

---

### 18. No alerting / on-call signal for stalled runs

**Source:** the live view shows stalls in real time, but the operator has to be looking at the dashboard. Run 178's stall sat un-noticed for 30+ minutes until the operator (you) happened to refresh.

**Fix:** when the dashboard's reaper transitions a run to `failed` *because of stall_timeout* (vs. natural completion or other failures), emit a notification. Cheapest implementations:
- **Slack webhook.** One env var (`SLACK_WEBHOOK_URL`), one POST per stall. Free, instant, ignores quiet hours.
- **Email via SMTP.** Slightly heavier; needs SMTP creds.
- **macOS notification (local).** Native `osascript` — only works when the operator's machine is alive, but trivial to set up for local dev.
- **GitHub issue.** `gh issue create` from the reaper. Permanent record but heavyweight.

**Recommended:** Slack webhook. The `recent_activity` JSON has all the context the message needs (last URL, last error, run id, heartbeat age).

**Corner case:** notification storms. If the reaper transitions 5 zombie runs at once (say, after a long power outage), don't send 5 messages. De-dupe by run_id and rate-limit (e.g., max 1 stall notification per 10 min).

**Priority:** P2 if scrape continuity matters; P3 if the operator checks the dashboard daily. Up to you.

**Effort:** ~1 hour for Slack with de-dupe + rate limit.

---

## P1/P2 — UX gaps surfaced from real use

These came up after watching the dashboard during real scrapes — operator workflows the current UI doesn't support yet.

### 19. "Re-run failed run" button

**Source:** operator workflow gap. When a run fails (stall, error, etc.) there's no way to re-trigger it from the dashboard — operator either waits for cron or shells in to run `scrapy crawl scan` manually.

**Fix:** add a "Re-run" button on the run detail page, visible only when `data.status === 'failed'`. POSTs to a new endpoint `POST /api/runs/{id}/rerun`.

Server-side behavior options:
- **Resume from queue** (preferred when failure was a stall, queue still has pending rows) — create a new `scrape_run`, mark the old run's pending rows under the new `run_id`, fire a fresh scrapy subprocess. Reuses the queue, doesn't waste the work that succeeded.
- **Restart from scratch** — call `prepare_scan` from clean state. Simpler, slower (re-discovers URLs).
- **Operator chooses** — radio in a small confirm dialog: "resume queue" vs "fresh discover".

**Corner cases:**
- **Already-running run for the same shop.** Reject with 409 — the existing run is still doing work, re-running creates contention. Surface the existing run id in the error message.
- **Concurrent rerun clicks.** Idempotency: hash the `run_id` into a Postgres advisory lock, second click within N seconds gets 409.
- **Stale dashboard view.** If the operator clicks rerun on a run that another process already reran, return the new run id rather than failing — the operator's intent is satisfied.
- **Auth.** No auth in the dashboard today. If this gets exposed externally, add a simple shared-secret header before shipping.
- **Subprocess stdout.** The existing `/scrape` POST uses `subprocess.Popen` fire-and-forget. Same pattern is fine; output goes to `scrapy_errors.log` + the JSONL events log.

**Priority:** P1. Currently the only way to retry a failed run is shell access — that's a real gap.

**Effort:** ~1.5 hours. Most of it is the API endpoint + the queue-inheritance logic. The UI is a single button + confirm dialog.

---

### 20. "Stop run" button (kill running scan)

**Source:** operator workflow gap. When a scan is going badly (high error rate, looking-stuck-but-not-yet-stalled, operator changed their mind) there's no UI to stop it cleanly. Existing code has a `kill_run` route per `b934f0f`'s commit message ("the kill_run route's PID-already-dead branch") but it's not surfaced in the React UI.

**Fix:** add a "Stop" button on the run detail page, visible only when `data.status === 'running'`. POSTs to `/api/runs/{id}/stop`.

**Design principle:** lifecycle mutations live in the DB, not in process/PID mechanics. The Stop endpoint mutates `scrape_runs.status` to `'stopping'` (new state); the spider polls its own status between requests and exits cleanly when it sees `stopping`. SIGTERM signaling is an *optimization* (faster shutdown when the dispatcher process is reachable), not the control plane.

Server-side flow:
1. Atomic UPDATE: `SET status='stopping' WHERE id=:run_id AND status='running'` — idempotent, race-safe (item #2's terminal-state-guard pattern).
2. Spider's per-request poll (item #23 reuses this primitive): between requests, query `SELECT status FROM scrape_runs WHERE id=:run_id`. If `stopping`, exit `start()` cleanly. Spider's `closed()` callback transitions `stopping → failed` (or a new `stopped` state) and runs `abort_processing_scrape_url_items`.
3. Optimization: `os.kill(pid, signal.SIGTERM)` if the dashboard happens to be in the same PID namespace as the scraper (uncommon — typically not). Documented as best-effort; the DB poll is the contract.
4. If the spider doesn't transition within 60 s (heartbeat went stale, process died, whatever): the existing reaper (item #2) marks it `failed` with `error_reason='stop_timeout'`. No special-cased dashboard timeout logic; reuse the lifecycle invariants.

**Why this is cleaner than PID-signaling:**
- **Cross-container/cross-host already works.** The DB is the universal channel. No control sockets, no NOTIFY plumbing, no PID-namespace gymnastics. A worktree's dashboard, the docker scraper, a cron-fired host process — all see the same `scrape_runs.status` column.
- **Crash safety.** If the dashboard dies between issuing kill and confirming, the spider still transitions on its own poll. SIGTERM-based control loses this — kill issued, dashboard crashes before logging, did the spider receive it? Unknown.
- **Single source of truth.** The same UPDATE the operator triggers is what the reaper would have eventually issued anyway. No two paths to fail-the-run.

**Corner cases:**
- **Race with natural completion.** Operator clicks Stop just as the spider finishes its last URL. UPDATE includes `WHERE status='running'`; if `closed()` already wrote `status='completed'`, the operator's UPDATE is a no-op and returns 200 with the latest status. UI shows "already completed" gracefully.
- **Spider's poll cadence.** Polling on every request is fine at 1 req/s — adds one cheap SELECT per dispatch (~1 ms with `pool_pre_ping`). At higher rates, batch the poll (e.g., every N requests, or piggyback on the heartbeat tick which already runs every 5 s).
- **`stopping` vs `stopped` vs `failed`.** Choosing the post-stop terminal state. Use `failed` with `error_reason='stopped_by_operator'` to keep the existing failed/completed dichotomy; introducing `stopped` as a peer to those is more states + more code paths for a cosmetic distinction.
- **Click-spam.** Disable the button in the UI for 5 s after click; the UPDATE is idempotent so second clicks are 200 no-ops.
- **Pause + Stop interaction.** If a paused run (item #23) is stopped, the spider unblocks its pause-poll, sees `stopping`, exits. No special handling.

**Priority:** P1. Combined with #19, this gives the operator full lifecycle control from the UI.

**Effort:** ~1.5 hours (down from the original 2 h estimate — DB-mediated mechanism is simpler than the cross-container signal plumbing). The new `stopping` state needs the spider's poll loop, an enum value, and the API route.

---

### 21. Live view shouldn't hide when run reaches terminal state — keep it static

**Source:** operator feedback. After PR #4 (commit `22d28f2`) the live panel disappears when the run transitions to `failed` / `completed`. Operator wants the panel to stay visible — the last "Now Fetching" + Recent activity is exactly what they want for a postmortem.

**Current behavior** (`hf-runs.jsx`'s polling effect):
```jsx
if (currentStatus !== 'running') {
  if (liveData) setLiveData(null);   // ← hides the panel
  ...
}
```

**Desired behavior:**
- Keep `liveData` populated with the last snapshot.
- Stop polling (no point).
- Render the panel with the last known state.
- Adjust the title / subtitle: "Live · refreshed every 2s · health: dead" → "Final state · health: <last>" or similar — make it clear the data is frozen.
- Health pill shows the final health (e.g., "dead" or empty for cleanly-completed runs).

**Corner cases:**
- **Initial-load on a finished run.** When the page loads against an already-completed run, `data.status === 'completed'` from the parent fetch. The polling effect should still issue ONE fetch to populate `liveData`, then stop. Currently the gate is `!== 'running'` → returns immediately, so the panel stays empty. Fix: do one final fetch when transitioning to (or starting in) terminal state, then stop polling.
- **Status mirroring (from PR #4's polling fix).** Currently when `liveData.status` flips terminal, we both null `liveData` AND mirror status into `data`. Keep the mirror; drop the null.
- **Rate counter and "now fetching" fields.** On a terminal run, "Now fetching" should clearly read "—" or "no requests in flight". The live API correctly returns `in_flight: []` once the run ends, so this is automatic — just don't hide the panel.
- **Recent activity table shows old data forever.** That's the point. Maybe label the timestamps as "X minutes ago" with a footnote that the run is no longer active.

**Priority:** P2. Pure UX improvement; the operator can already see this data on /runs/<id>/urls page, but the live panel's pre-baked summary is more readable.

**Effort:** ~30 minutes. Mostly: do one final fetch on terminal-status transition (for the case where the page loads against a finished run), don't null `liveData`, swap the panel title.

---

## P1/P2 — Run-management gaps (operator workflow, beyond just observability)

The earlier UX items (#19–#21) were small surface controls. These are about making the run *lifecycle* something an operator can live with day-to-day, not just observe.

### 22. Schedule / next-run / ETA visibility

**Source:** there's no way to see when the next cron-fired run will happen, when this one will finish, or when the last successful run completed without reading the crontab + scrape_runs table by hand.

**Three small additions, each independently useful:**

- **"Next run in 4h 23m"** badge on the run-list page header. Read from `cron_jobs` (cron_expression → croniter → next firing). One small helper, displayed in the page header.
- **"Last successful run: 3 hours ago"** badge. `MAX(finished_at) WHERE status='completed' AND shop_id=X`. Pairs with the next-run badge so the operator sees the cadence.
- **"ETA ~25 min"** on the live view of a running run. Compute `pending_count / current_rate_per_minute`. Displayed alongside the existing rate counter.

**Corner cases:**
- **First-run bootstrap.** No prior data → ETA is null/unknown rather than "Infinity". Same for "last successful" if no run has succeeded yet.
- **Throttle-induced stalls.** If `current_rate` drops to 0 (we're in the 220-second silence pattern), ETA goes to infinity. Cap at "—" and flag visually.
- **Cron schedule changes.** If the operator edits `cron_jobs`, the badge needs to refresh. Recompute on each dashboard fetch (cheap).

**Priority:** P2. Quality-of-life; operator currently has to mentally track "is the scan still going? when did the last one finish?".

**Effort:** ~1 hour total for all three.

---

### 23. Pause / Resume (distinct from Stop)

**Source:** there's no graceful "halt without killing" option. The current Stop button (#20) tears down the spider; a brief "pause for maintenance" requires Stop + Rerun, which fragments the run into multiple `scrape_runs` rows and risks losing in-flight state.

**Use cases:**
- Operator about to deploy something — pause briefly, deploy, resume.
- Vaga.lt is having an outage — pause for 10 minutes, resume.
- Disk space getting low — pause until cleanup completes.

**Implementation:**
- `POST /api/runs/{id}/pause` — flips `scrape_runs.status` to `'paused'` (new state). The spider polls `status` between requests; on `paused` it sleeps until status returns to `running`.
- `POST /api/runs/{id}/resume` — flips back to `'running'`.
- New status badge in the UI: yellow "paused" pill.
- Heartbeat continues to tick during pause (so the run doesn't look dead).

**Corner cases:**
- **Pause during a long HTTP request.** The current request finishes (no point cancelling); next one waits on the pause check. Pause latency = roundtrip time of in-flight request, ~2 s. Acceptable.
- **Pause during `prepare_scan`.** The queue prep finishes; pause kicks in before the first dispatch. Spider's poll loop checks status inside `start()` after queue load.
- **Crash during pause.** The reaper sees stale heartbeat → marks failed. But heartbeat keeps ticking during pause, so this only triggers on actual crash. ✓
- **Pause-while-paused / resume-when-running.** Both should be idempotent no-ops, not 4xx. Spec the API as "set state" rather than "transition".
- **Auto-unpause timeout.** Optional but recommended: if a run sits in `paused` for >1 hour, auto-resume. Prevents forgotten pauses from blocking cron.

**Priority:** P2. Need-to-have for any operator who runs the scraper through a maintenance window. Skip if you don't.

**Effort:** ~3 hours including the new state in the schema, spider poll loop, and UI controls.

---

### 24. Run retention / cleanup policy

**Source:** `scrape_runs` rows accumulate forever; `scrape_url_items` rows stay (post-PR #3 we explicitly stopped deleting them — they're now the source of truth for per-URL history). At ~3,000 rows × 1 run/day × 365 days = ~1.1M rows/year of `scrape_url_items` for a single shop. JSONL log is also append-only (#13).

**Symptom (latent):** disk fills slowly, dashboard queries get slower, backups balloon. Months away, but worth designing now.

**Fix — retention policy in three layers:**

- **`scrape_runs`:** keep all completed/failed runs forever (cheap, valuable for trend analysis — they're hundreds of bytes each).
- **`scrape_url_items`:** keep last N runs per shop with full per-URL detail; older runs aggregated into `scrape_runs` columns only (urls_total, items_added, etc. — already there). Concretely: a daily cleanup job that DELETEs `scrape_url_items` where `run_id NOT IN (last 30 runs per shop) AND run is terminal AND finished_at < now() - interval '30 days'`.
- **JSONL log:** logrotate with 14-day retention (already proposed in #13).

**Corner cases:**
- **Active run protection.** Cleanup must filter `WHERE run.status NOT IN ('running','paused')` to never touch active queues.
- **Cascade safety.** `scrape_url_items.run_id` is FK to `scrape_runs.id`. Deleting items doesn't affect runs ✓. But `validation_issues.scrape_run_id` exists too — verify deletion order. Probably want to keep validation issues longer (cheap, valuable for trend analysis).
- **Foreign-key from `discovered_urls`?** Check the schema — if discovered_urls reference scrape_url_items, deletion order matters.
- **Concurrent run while cleanup runs.** Cleanup wraps deletes in a transaction; if a run is mid-flight, its rows are excluded by the WHERE clause. Lock contention is minimal (different rows).

**Priority:** P2. Not urgent (months runway), but easier to implement before the table hits a million rows than after.

**Effort:** ~2 hours including the cleanup script, cron-installable Postgres job (`pg_cron` extension or a small Python script), and a dashboard "DB size by table" widget so the operator can see it working.

---

### 25. Repeated-failure detection / alerting

**Source:** if 5 consecutive runs for the same shop fail with the same `error_reason`, that's a systemic problem (server-side block, broken parser, expired auth) — not transient. Today the operator only notices when they happen to look. Pairs with #18 (alerting) but is more specific.

**Detection rule:** "N consecutive runs for the same shop+phase ended in `failed` status with the same `error_reason` cluster in the last K hours."

**Where to compute it:**
- Cheapest: a SQL view + dashboard query, computed on each list-page fetch. No background job.
- Slightly fancier: a Postgres trigger on `scrape_runs.status` change to terminal that increments a per-shop "consecutive failures" counter, resets on success.

**Surface in UI:**
- Red banner at the top of the run-list page when a shop has 3+ consecutive failures.
- Same context surfaced in the per-shop detail page.
- Optional: tied into #18's Slack hook.

**Corner cases:**
- **Different error_reason each time.** Genuinely transient — don't alert. The "same cluster" requirement matters.
- **Cron retries the next day.** A single retry shouldn't reset the counter — only `status='completed'` should. Keep the consecutive count across days.
- **Manual reruns (#19) interleaved.** A manual rerun that succeeds should reset the counter; a manual rerun that fails should advance it. Same rule as cron.
- **Threshold tuning.** N=3 vs N=5 changes false-positive rate. Start at 3 with an env-var override.

**Priority:** P1 if you run unattended for >1 day at a time; P2 otherwise.

**Effort:** ~2 hours for the SQL view + UI banner + tests.

---

### 26. Run-list filtering / search

**Source:** the run-list page shows the most recent N runs. Once you have hundreds of runs, finding "all failed runs in the last week for vaga.lt" requires a SQL query.

**Add to the run-list page:**
- Filter dropdowns: shop, status, phase. Already partly exists in `/api/runs` query params; surface in the React UI.
- Date range picker: "from"/"to" timestamps.
- Free-text search across `error_reason` (server-side `ILIKE`).
- URL-state for filters (so a saved bookmark links to the same view).

**Corner cases:**
- **Search-as-you-type vs explicit submit.** At a few-hundred-run scale, on-blur or explicit submit is fine. Debounced search-as-you-type at 300 ms is friendlier.
- **Empty result.** Show "No runs match these filters" with a "Clear filters" button. Don't show a stale list.
- **Pagination.** Already implemented; verify it composes with filters.

**Priority:** P2. Comfort feature; only matters once the run list gets long.

**Effort:** ~1.5 hours.

---

### 27. Pre-flight checks before starting a run

**Source:** `/scrape` POST and the rerun button (#19) both fire-and-forget a scrapy subprocess with no validation. If the DB is down, migrations are pending, disk is full, or another run is already active for the shop, the subprocess starts then fails 30 s in. Operator sees "run created, then immediately failed" with no useful diagnostic.

**Pre-flight checks** (run synchronously in the POST handler before spawning the subprocess):

| Check | Failure mode if skipped |
|---|---|
| DB reachable + migrations up-to-date | Spider crashes on first query |
| No `running`/`paused` run for this shop+phase | Two concurrent scans = doubled load (#16) |
| Disk space > 1 GB free on `/var/log` | JSONL log writes fail mid-run |
| `cron_jobs` row exists (or operator opted out) | Run is one-off; OK but log it |
| Shop config TOML loads without error | Spider crashes immediately |

If any check fails: return 400 with the specific reason; do not spawn. Operator sees a crisp error message instead of a mysterious failed run.

**Corner cases:**
- **DB-reachable check is itself a query.** Use `pool_pre_ping` (item #11) — same connection check, free.
- **"Running" check has its own race.** Two operators clicking at the same instant. Use Postgres advisory lock (item #16) for the actual run-creation transaction.
- **Disk-space check on a Docker volume.** Use `shutil.disk_usage("/var/log")` from inside the container; the mount point may not be the path the operator expects, document clearly.

**Priority:** P2. Saves a class of "I clicked Scrape and it failed for no reason" debugging.

**Effort:** ~1.5 hours.

---

### 28. Per-rerun config overrides

**Source:** rerun button (#19) currently uses the shop's TOML config as-is. Common operator need: "rerun this with `DOWNLOAD_DELAY=10` to be gentler on the server" or "rerun with a different shop". Currently requires editing TOML and rebuilding.

**Add to the rerun dialog (#19):**
- A small form: download_delay (number), max_urls (cap), httpx_client_reset_after_requests (number). Pre-filled from the original run / shop config.
- Submit overrides them as `-s` flags on the spawned scrapy command.
- The override values are stored on the new `scrape_run` row (new column `config_overrides JSONB`) so post-mortems can see what the operator changed.

**Corner cases:**
- **Override leaks across runs.** Each rerun creates its own scrape_run with its own config_overrides; cron-fired runs use the TOML default. No persistence across reruns unless the operator edits the TOML.
- **Invalid override (negative delay, non-integer max_urls).** Validate in the POST handler before spawning. Return 400 with the field-specific error.
- **Schema migration.** Adding `config_overrides` column to `scrape_runs` is a small migration; old rows have NULL ✓.

**Priority:** P3. Useful but not blocking; the workaround (edit TOML, restart, rerun) takes 30 seconds.

**Effort:** ~2 hours.

---

## Suggested order of attack (revised — two tracks)

**Design principle, applied throughout:** *lifecycle mutations live in the database, not in process or PID mechanics.* Status transitions, kill signals, pause/resume, "is this run still active" checks — all read and write `scrape_runs.status` (and related columns) under transaction guards. Process-level mechanisms (SIGTERM, PID lookups, in-memory state) are optimisations on top of that contract, never the source of truth. Cross-container, cross-worktree, cross-host: the DB is the universal channel.

That principle drives the ordering: stability first (the DB lifecycle invariants), then operator controls layered on top.

### Track A — Stability foundation (lifecycle bundle)

Land these together, in this order, as one or two PRs. They establish: *one active worker owns a shop+phase, heartbeats are trustworthy, stale runs are failed promptly, terminal runs stop accepting writes, stalls don't strand the queue.*

1. **#11 (`pool_pre_ping` + `pool_recycle`)** — 5 min. Stale connection failures (run 178's `OperationalError`) gone. Prerequisite for everything else: every fix below assumes DB writes don't sporadically die.
2. **#16 (advisory lock — single active scan per shop+phase)** — 1 h. *Promoted from later in the list.* Without this, two processes can attach to the same queue and the rest of the lifecycle work papers over symptoms instead of fixing the cause. Cheap insurance; belongs in the lifecycle bundle.
3. **#15 (heartbeat blackout fix)** — 15 min. Emit `run_started` immediately after `create_scrape_run` so the heartbeat ticks during `prepare_scrape_url_items`. Prerequisite for #2 to not false-positive on long queue prep.
4. **#2 (full reaper coupling with terminal-state guards)** — 3 h. Splits thresholds (live view at 30 s, reaper at 60 s), adds `WHERE status='running'` guards on every spider write so a reaped run can't be resurrected, queue inheritance on `stall_timeout`. Don't ship the "simple" version — it leaves the race in.
5. **#10 partial (auto-resume on stall)** — 1 h. When `StallDetector` fires, the run's pending rows stay queued for the next scheduled run instead of being abandoned.

After Track A lands, the invariant holds: **at most one process owns a shop+phase, the heartbeat is the truth about liveness, and terminal state in the DB is final.**

### Track B — Operator controls

Layer on top of Track A. Each item assumes the lifecycle invariants are sound — without Track A, these create more weird states than they fix.

6. **#21 (live view stays static on terminal)** — 30 min. Pure UX, immediately observable. Operator-requested.
7. **#19 ("Re-run failed" button)** — 1.5 h. Pairs naturally with #10 (rerun creates a new run that inherits the failed run's queue).
8. **#20 ("Stop" button)** — 1.5 h. **DB-mediated** (status `→ 'stopping'`, spider polls between requests). SIGTERM is an optimisation, not the control plane. See item #20's revised design notes.
9. **#27 (pre-flight checks)** — 1.5 h. *Promoted from later.* Validates *before* spawning a subprocess: DB reachable, no concurrent run, disk space, config loads. Prevents bad runs cleanly; matters more than the schedule/ETA niceties below because it stops symptoms at the source.
10. **#25 (repeated-failure detection)** — 2 h. Banner on the run-list page when N consecutive runs failed with the same `error_reason` cluster. Essential for unattended operation.

### Track C — Quality of life

These polish the experience but don't change correctness. Do when Tracks A/B are stable.

11. **#22 (schedule + ETA visibility)** — 1 h. "Next run in 4h", "ETA ~25 min". Three small badges.
12. **#4 (unit tests)** — 2 h. Lock in Track A's design from regressing.
13. **#24 (retention / cleanup)** — 2 h. Set-and-forget; do before the DB hits a million rows.
14. **#23 (pause / resume)** — 3 h. Skip if you don't run through maintenance windows. Reuses #20's DB-poll primitive.
15. **#26 (run-list filtering)** — 1.5 h. Comfort feature; only matters with hundreds of runs.
16. **#13 (logrotate)** — 10 min, set-and-forget.
17. **#12 (absolute log path)** — 5 min.
18. **#5, #6** — small verification tasks, batch them.
19. **#28 (per-rerun config overrides)** — 2 h. Do when editing TOML becomes annoying.
20. **#18 (alerting)** — only if you actually want pager-style notifications. Pairs with #25.
21. **#7 (throttle retry)** — only after #1 actually surfaces real `autothrottle_slot` data (not just our internal `'autothrottle'` source). Currently the precondition isn't met.

### Items NOT worth doing right now

- **#1 (AUTOTHROTTLE bypass).** Functionally closed by PR #4's internal pacing. Re-emitting Scrapy signals (option B) would only matter if we wanted Scrapy's stats / extensions to see the requests, which we don't.
- **#3 (boot reconcile).** Subsumed by #2 — once the dashboard reaper transitions stale runs aggressively, boot-time reconcile is redundant.
- **#14 (atomic JSONL writes).** Speculative; defer until we see corruption.
- **#17 (long-lived session recycle).** Subsumed by #11 — `pool_pre_ping` makes stale-connection recycling unnecessary.

### Natural PR batches

- **Track A bundle (~5.5 h, one PR):** #11 + #16 + #15 + #2 + #10. They all touch the same files (`session.py`, the reaper, spider close path, repo helpers). Ship together so the lifecycle invariants land coherently — partial Track A is worse than no Track A.
- **Track B bundle (~5 h, one PR):** #21 + #19 + #20 + #27 + #25. Dashboard React + a few small API routes. Pre-flight (#27) and failure detection (#25) share the same query layer as the Track B controls.
- **Track C is à la carte** — each item is independent and small enough to ship on its own.
