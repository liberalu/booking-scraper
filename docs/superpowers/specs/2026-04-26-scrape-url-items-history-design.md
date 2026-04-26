# Per-URL Run History via `scrape_url_items`

**Status:** Implemented — commit `b4386c8` (migration `7c441ea07eb2`)
**Date:** 2026-04-26

## Problem

`scrape_url_items` was designed as a transient work queue for the scan
spider. Rows were inserted by `ScanService.prepare_scan`, transitioned
`pending → processing → done|failed` while the spider ran, then deleted
on run finish via `cleanup_scrape_url_items`.

Per-URL outcomes (which URLs 404'd, which timed out, which were
classified non-product) only existed in aggregate columns on
`discovered_urls` — `last_http_status`, `last_checked_at`, `fail_count`
— and only for the *most recent* check. Once a run finished, you could
no longer answer "what was attempted in run #N" without a fragile time-
window join.

Three concrete pain points:

1. The run detail page couldn't show "URLs touched" for finished scan
   runs without joining `discovered_urls.last_checked_at` against the
   run's `[started_at, finished_at]` window. Two scans of the same shop
   in close succession would collide on the join.
2. No per-URL failure attribution. The run row carried `errors_4xx`,
   `errors_5xx`, `error_count` totals, but you couldn't see *which URLs*
   timed out vs returned 503 vs were classified non-product.
3. Cross-run forensic queries — "has this URL been failing every run for
   the past week?" — required data that didn't exist.

## Solution

Keep `scrape_url_items` rows after the run finishes. Add per-URL outcome
columns. Surface the data on the run detail page.

## Schema

Migration `7c441ea07eb2`:

```sql
ALTER TABLE scrape_url_items
  ADD COLUMN http_status   integer NULL,
  ADD COLUMN error_reason  text    NULL;

CREATE INDEX ix_scrape_url_items_shop_claimed_at
  ON scrape_url_items (shop_id, claimed_at);
```

- `http_status` — final HTTP status for the URL (200, 404, 503, …) or
  `NULL` for transport-level failures (DNS, timeout, connection reset).
- `error_reason` — short free-form string. Not an enum, so the spider
  can introduce new categories without a migration. Current values:
  - `http_<code>` — e.g. `http_404`, `http_503`
  - `request_error:<exception_class>` — e.g. `request_error:TimeoutError`
  - `non_product` — page parsed OK but classifier rejected it
- `(shop_id, claimed_at)` index — supports cross-run history queries
  ("recent activity for shop=vaga"). Per-run lookups are already
  covered by the existing `(run_id, status)` index.

The existing columns on the table fully describe the per-URL timeline:
`created_at` (queued), `claimed_at` (request dispatched), `done_at`
(response or final failure recorded), `status`, `url_type`. Duration is
computed at read time as `done_at - claimed_at` — no stored column.

## Behaviour changes

- `ScanService.finish_scan` no longer calls
  `cleanup_scrape_url_items`. The function itself remains; the
  discover service still uses it (see Out of scope).
- `ScanSpider._queue_url_status_update` accepts an optional
  `error_reason` argument and threads it through into the update dict.
  The spider populates it on every outcome path:
  - 4xx response  → `error_reason="http_<code>"`
  - 5xx response  → `error_reason="http_<code>"`
  - non-product   → `error_reason="non_product"`
  - errback fired → `error_reason="http_<code>"` or
                    `request_error:<ExceptionClass>"`
  - book product  → `error_reason=None` (success)
- `ScanService.flush_progress` and `finish_scan` pop the new key out of
  the update dict before forwarding to `update_discovered_url_status`,
  then pass `http_status` + `error_reason` to
  `mark_scrape_url_item_done`/`mark_scrape_url_item_failed`.
- `mark_scrape_url_item_done` and `mark_scrape_url_item_failed` accept
  optional `http_status` and `error_reason` kwargs and write them on the
  matching row.
- `update_discovered_url_status` is unchanged — `discovered_urls`
  remains the latest-state aggregate; `scrape_url_items` is the per-run
  detail.

## Read path

Before: the dashboard had two source paths for the run detail URL list —
live `scrape_url_items` for runs that still had rows, fallback time-
window join on `discovered_urls.last_checked_at` for finished scan runs
whose staging rows had been wiped.

After: `scrape_url_items` is the single source of truth for scan runs,
running or finished.
- `get_run_url_breakdown` and `get_run_url_items` (in
  `book_scraper/dashboard/queries.py`) read directly from the table.
- `get_run_discovered_urls` is now a thin helper that only handles the
  *discover*-phase fallback (matches `last_seen_run_id == run.id`). For
  scan runs it returns an empty list — the caller is expected to
  prefer the live data.
- The API endpoint `GET /api/runs/{id}/urls` chooses `source="live"`
  whenever the breakdown sums to > 0; otherwise (only possible now for
  pre-migration scan runs and discover runs) it falls back to
  `source="history"`.

## API contract

`GET /api/runs/{run_id}/urls?status=<all|pending|processing|done|failed>&page=<n>&per_page=<n>`

Live (scan run, post-migration):

```jsonc
{
  "source": "live",
  "breakdown": {"pending": 0, "processing": 0, "done": 4, "failed": 1},
  "status": "all",
  "statuses": ["pending", "processing", "done", "failed"],
  "rows": [
    {
      "url": "https://vaga.lt/...",
      "status": "failed",
      "url_type": "product",
      "claimed_at": "2026-04-26T03:05:53.123Z",
      "done_at":    "2026-04-26T03:05:54.353Z",
      "http_status": 404,
      "error_reason": "http_404",
      "duration_ms": 1230
    }
  ],
  "total": 5, "page": 1, "per_page": 50, "pages": 1
}
```

History (discover run or pre-migration scan):

```jsonc
{
  "source": "history",
  "breakdown": {"pending": 0, "processing": 0, "done": 0, "failed": 0},
  "rows": [
    {"id": 21967, "url": "...", "url_type": "non_product",
     "last_http_status": 200, "last_checked_at": "2026-04-26T..."}
  ],
  ...
}
```

## UI

The SPA `HFRunDetail` component (in
`book_scraper/dashboard/static/hifi/hf-runs.jsx`) renders a "URL queue"
card for live source and "URLs touched" for history. The live view shows:

| URL | status pill | http pill | url_type | duration | error_reason |

`error_reason` is rendered red when present; otherwise the cell shows
the `done_at` timestamp. The card auto-refreshes every 3 s while the
run is `running`; it's static once the run reaches a terminal state.

A status filter (`all` · `pending` · `processing` · `done` · `failed`)
sits above the table; clicking a chip re-fetches with the corresponding
filter and resets pagination to page 1.

## Tradeoffs

| | Keep (chosen) | Cleanup (old) |
|---|---|---|
| Storage / year (vaga, 1 scan/day, ~4500 URLs) | ~200 MB | ~0 MB |
| Cross-run forensics | yes | no |
| Run detail read path | one source | two sources + fragile join |
| Effort to undo | one DELETE per column + re-enable cleanup | re-add cleanup call |

Storage at the current scale is a non-issue: Postgres handles tables
two orders of magnitude larger without breaking a sweat, and the
`(shop_id, claimed_at)` + `(run_id, status)` indexes cover every query
the dashboard issues today.

## Out of scope

- **Discover phase.** The discover service still calls
  `cleanup_scrape_url_items`. Rationale: discover runs produce roughly
  5× more rows per run (~20k sitemap URLs vs ~4k scan URLs), and per-
  URL outcome data has lower forensic value there (most rows are just
  "URL recorded"). Worth revisiting if/when discover failures become a
  recurring debugging target.
- **Retention.** The table grows unboundedly. At one scan/day for a
  single shop this is ~200 MB/year, which is fine for years. When this
  becomes a real concern, the simplest hook is a daily DELETE in the
  background reaper task that drops rows older than N days; that's a
  one-line addition to `book_scraper/dashboard/reaper.py` and a
  schema-free change.
- **Backfill of pre-migration runs.** The cleanup call deleted those
  rows long ago; the data is unrecoverable. Pre-migration runs continue
  to fall back to `source="history"` from `discovered_urls.last_seen_run_id`
  (discover) or come up empty (scan). Acceptable.
- **Per-URL retry counts.** `discovered_urls.fail_count` already
  tracks consecutive failures across runs; not duplicated here.
- **An `error_reason` enum.** Free-form text is intentional. Keeps the
  spider unconstrained; cardinality is low in practice; no migration
  needed when a new failure mode is added.

## Known gap

`claimed_at` is never set in the current spider implementation — items
go directly `pending → done|failed` without a `processing` transition.
That makes `duration_ms` always `null` in the API. Fix is small (stamp
`request.meta["claimed_at"]` at dispatch, write it through
`flush_progress`) and tracked separately.

## Test surface

- `tests/integration/test_scan_service.py::test_mark_scrape_url_item_done`
  exercises the existing flow; new kwargs are optional so the test
  continues to pass without modification.
- `tests/integration/test_dashboard_routes.py` covers the
  `/api/runs/{id}/urls` endpoint for live + history paths.
- The full unit + integration suites (177 + 69 tests) are green on the
  implementation commit.
