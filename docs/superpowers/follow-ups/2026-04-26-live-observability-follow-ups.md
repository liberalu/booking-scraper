# Live Observability — Follow-up Tasks

**Date:** 2026-04-26
**Spec:** `docs/superpowers/specs/2026-04-26-live-scrape-observability-design.md`
**Plan:** `docs/superpowers/plans/2026-04-26-live-scrape-observability-plan.md`
**Shipped in:** PR #3 (commits `0ac3256`, `9762a6b`, `193fa29`) + `b934f0f` (abort-processing-on-terminal)

The observability work landed end-to-end. These items came up during implementation, Stage 0 verification, and the post-merge zombie-run incident (run 173). Each is out of scope for the observability spec but worth tracking.

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
- Reduce `DEAD_RUN_MINUTES` from 30 → 1–2 minutes (or split: keep 30 for the run-list "stale" badge, add a faster `DEAD_RUN_SECONDS = 60` threshold for actual reaping)
- Make the dashboard background reaper run more frequently (e.g., every 30 s) so the gap between detection and DB transition is small
- Or: have the live view *itself* trigger the reap when it sees a dead run (more invasive — the live view would need to mutate state, which it currently doesn't)

**Priority:** P1. It's the difference between "the dashboard told me my run died and the data is consistent" vs. "the dashboard told me my run died but the queue still thinks it's running for 28 more minutes."

**Effort:** ~30 minutes for the threshold tweak + reaper cadence change. Validate with a forced-kill test.

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

## Suggested order of attack

1. **#2 (live view ↔ reaper coupling)** — small, isolated, eliminates zombie-run confusion immediately.
2. **#1 (AUTOTHROTTLE bypass)** — bigger, but unblocks #7 and fixes a real safety issue. Option A first; consider C as a longer-term cleanup.
3. **#4 (unit tests)** — close the test-coverage gap before more code lands on top.
4. **#5, #6** — small verification tasks, batch them with #4.
5. **#7** — only after #1 lands and there's real `autothrottle_slot` data to design from.
