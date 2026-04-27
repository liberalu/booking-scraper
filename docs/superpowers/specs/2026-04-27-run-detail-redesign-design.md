# Run Detail Page Redesign

**Date:** 2026-04-27
**Status:** Approved for implementation
**Scope:** Frontend (hifi React mockup serving real data) + small read-side API change. No DB migration.

## Goal

Replace the current `HFRunDetail` layout with the new design from `_download 3/hifi/hf-runs.jsx` (~April 27 mockup), wired to live APIs. Re-add the operator action buttons (Pause / Resume / Stop / Re-run) that the new mockup shipped without. Surface a derived `close_reason` for terminal runs. Delete the dormant Jinja `run_detail.html` template and its dead query paths.

## Non-goals

- Redesign of `HFRuns` list page (deferred)
- New backends for "Retry group" / "Skip permanently" / "Open parser" / "Open issue" / Logs export (UI placeholders only)
- New `close_reason` column or schema migration

## Layout (replaces existing `HFRunDetail`)

In rendered order:

1. **Shell header**
   - Title: `Run #<id>` + status pill + `close_reason` pill (terminal runs only, e.g. `failed · heartbeat_timeout`)
   - Subtitle: `shop=<name> · phase=<phase> · started <ago> · triggered by <by>`
   - Breadcrumb: `Runs / #<id>`
   - Actions (right): `Logs` · `Pause` (running) | `Resume` (paused) · `Stop run` (active) · `Re-run` (terminal)
2. **KPI strip**: Progress · Elapsed · Errors (`errors_4xx · errors_5xx`) · Workers
3. **In flight card** (live only)
   - Big "Now fetching" tile: URL, worker id, claimed-ago, dispatch ms, attempt N/M, indeterminate sweep
   - Right side: Rate (last 60s) — done card (green) + failed card (red, with % rate)
   - Health pill in card header
4. **Failures card**
   - One row per `error_reason` group, sorted by count desc
   - Pill (HTTP code or label), reason name, `× count`, `RECURRING` (seen in prior runs) or `NEW` (this run)
   - Expanded body: pattern blurb, example URLs (max 3), "+ N more" link, since/last-seen line, per-group action buttons
   - Card-level action buttons: `Retry all` · `Open issue` (disabled placeholders)
   - Per-group buttons: `Retry group` · `Open parser` · `Skip permanently` · `View all <count>` (all disabled placeholders for now)
5. **Throughput card**
   - Items/min last 60s, rolling 2s samples (existing `throughputHistory`)
   - Y-axis labels (0 / 5 / 10 / 15 / 20), X-axis time markers (−60s / −45s / −30s / −15s / now)
   - Header right: `done` and `failed` legend with current per-min values
   - Done-only series for now if `liveData.rate.failed` is absent; layout reserves the legend slot regardless
6. **History card**
   - Tabs: `all` · `pending` · `processing` · `done` · `failed` (with counts)
   - Columns: `ID` · `URL` (mono + ext-link icon) · `STATUS` (pill stack with embedded HTTP/error code) · `DISCOVERED URL` · `STARTED` · `TYPE` · `DURATION`
   - Existing per-page selector + pagination; URL state persisted in query string (current behavior preserved)
7. **Parameters card**
   - Existing rows + new rows: `urls_processed`, `items_added`, `items_updated`, `close_reason` (terminal only)

## Data wiring

### Existing endpoints (no change)
- `GET /api/runs/{id}` — base run detail
- `GET /api/runs/{id}/live` — 2s polling source of truth for status, in-flight, rate
- `GET /api/runs/{id}/urls?status=&page=&per_page=&sort=&order=` — URL queue
- `POST /api/runs/{id}/{stop,pause,resume,rerun}` — operator actions

### New: `close_reason` derived field
Add `close_reason: str | None` to the `/api/runs/{id}` JSON.

Derivation in `queries.get_run_detail`:
- `status == "completed"` and `error_count == 0` → `"completed_ok"`
- `status == "completed"` and `error_count > 0` → `"completed_with_errors"`
- `status == "failed"` → look up the `validation_issues` row for this run with `issue == "scrape_run_failed"` (idempotent, one per run — see `record_scrape_run_failed_issue` in `db/repo.py`) and read `raw_value` (e.g. `heartbeat_timeout`, `stall_timeout`, `stop_timeout`, `stopped_by_operator`, `orphan_on_boot`, `finished_failed`). If no such row exists, fall back to `"failed"`.
- `status` in (`running`, `paused`, `stopping`, `queued`) → `None`

Render rule: only show the pill / parameter row when `close_reason is not None`.

### Failure grouping (client-side)
Group `urlData.rows` (where `status == "failed"`) by `error_reason`. Compute `count`, take first 3 examples, derive `pattern` heuristically from URL prefix where possible (else null and skip the line).

`RECURRING` / `NEW` flagging is **not** computed for now (no cross-run data on the client). Render as plain rows without the badge unless we add a backend in a follow-up. **Decision recorded:** keep the badge code path so a future endpoint can populate it without touching the layout.

## Component changes

- **`book_scraper/dashboard/static/hifi/hf-runs.jsx`** — replace `HFRunDetail` (lines 451–964) with new layout, keeping all hooks/effects/state/callbacks (URL filter state, throughput buffer, live polling guard, action handlers).
- **`book_scraper/dashboard/static/hifi/hf-ui.jsx`** — port `HFExtLink` from the new file (the open-in-new-tab icon link used in History rows and the in-flight tile).
- **`book_scraper/dashboard/queries.py`** — extend `get_run_detail` with `close_reason` derivation. Drop `created` / `changed` / `unchanged` lists if only consumed by the Jinja template.
- **`book_scraper/dashboard/routes/runs.py`** — remove the `run_detail` GET handler that renders `run_detail.html` (line 84+); SPA index serves `/runs/{id}` already. Keep the action POST routes.
- **`book_scraper/dashboard/templates/run_detail.html`** — delete.

## Testing

- `uv run pytest tests/integration/test_dashboard_routes.py -v` — confirm the route smoke tests still pass after Jinja removal (route should now serve the SPA shell, not the deleted template).
- Manually browse `/runs/195` (or any recent run id) and verify:
  - Live run: in-flight panel populates, throughput rolls, history tabs filter correctly
  - Terminal run: `close_reason` pill + parameter row shows, failure groups render
  - Operator actions: Pause→Resume cycle works, Stop transitions to `stopping` then terminal, Re-run navigates to `runs` list
- Add unit test for `close_reason` derivation in `tests/unit/test_dashboard_queries.py` covering the four status branches.

## Rollout

Single PR. After merge: rebuild dashboard container only (`docker compose build dashboard && docker compose up -d dashboard`); no scraper rebuild required (no model changes).

## Open follow-ups (not in this change)

- Real backends for `Retry group` / `Skip permanently` / `Open parser` / `Open issue`
- Cross-run failure history (`RECURRING` badge backend)
- Splitting throughput into done-vs-failed series in `liveData.rate`
- Logs export
