# Issues page redesign — flat list

**Date:** 2026-04-17
**Status:** Design

## Motivation

The current `/validation` page groups issues by type into collapsible cards with per-group pagination. This makes it hard to scan recent activity across types, filter to a single run, or triage a large backlog (500+ rows). Info-level issues (`field_missing`) add noise without prompting action.

This spec replaces the grouped layout with a flat, filterable list modeled on `/shop-books`.

## Goals

- One scannable list of issues sorted by added time, newest first
- Filter by shop, issue type, run ID, and free-text search
- Fast enough to render at 500+ open rows (via server-side pagination at 50/page)
- Bulk-acknowledge and bulk-delete against the current filter
- Drop info-level issues entirely — only Critical and Warning remain

This redesign is scoped to the page and data model only. New detections (`scrape_error`, `inactive_spike`, `price_anomaly`) and external tooling (Sentry, GitHub Issues) are explicitly out of scope — they land in a follow-up spec.

## Non-goals

- Adding new issue detections
- Integrating external issue trackers
- Changing how issues are generated or how lifecycle transitions work
- Keeping backward compatibility with the grouped-view URLs (this is a personal project; the groups endpoint is replaced)

## User-facing design

### Page layout

```
┌─ Issues ─────────────────────────────────────────────────────────────┐
│                                                                       │
│ [Open 527] [New 84] [Recurring 443] [Ack'd 2,184]                    │
│                                                                       │
│ ▸ Open  · New  · Recurring  · Acknowledged  · All                     │
│                                                                       │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ Shop [vaga ▾]  Issue [suspicious_title ▾]  Run [#142]           │ │
│ │ Search [________________]  [Filter] [Reset]                      │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│ Showing 1–50 of 527 open  [Ack 527 matching] [Delete 527 matching]   │
│                                                                       │
│ ┌──┬──────┬─────┬──────────┬──────┬──────────┬─────┬─────┬────┐    │
│ │☐ │ Added│State│ Issue    │Field │Book/URL  │Raw  │Run  │ ⨯  │    │
│ │  │      │     │          │      │          │value│     │    │    │
│ ├──┼──────┼─────┼──────────┼──────┼──────────┼─────┼─────┼────┤    │
│ │☐ │ts    │new  │● susp…   │title │linked    │...  │#142 │Ack │    │
│ │☐ │ts    │rec  │● inv_isbn│isbn  │linked    │...  │#142 │Ack │    │
│ └──┴──────┴─────┴──────────┴──────┴──────────┴─────┴─────┴────┘    │
│                                                                       │
│         [50/pg]  ← Prev  1  2  3  4  …  11  Next →                   │
└───────────────────────────────────────────────────────────────────────┘
```

### Components

**Stat strip** (top): counts for Open, New, Recurring, Acknowledged. Respects the active shop filter.

**Lifecycle tabs**: `Open` (default), `New`, `Recurring`, `Acknowledged`, `All`. Clicking a tab preserves other filters.

**Filter bar** (single GET form, submit = Filter button):
- `Shop` — dropdown populated from the shops table + "All shops"
- `Issue` — dropdown grouped by severity with `<optgroup>Critical</optgroup>` and `<optgroup>Warning</optgroup>` + "All types"
- `Run` — numeric input (run ID)
- `Search` — case-insensitive substring match against `url` and `shop_books.title` (joined when resolvable)
- `Filter` submits; `Reset` clears every filter except the active lifecycle tab

**Sort**: `Added` column header toggles between desc (default) and asc. No other columns are sortable in v1.

**Action bar** (above the table):
- Left: `Showing X–Y of Z <lifecycle> issues [for <shop>] [type: <t>] [run: #<n>]`
- Right: two buttons operating on the current filter, not checkbox selection:
  - `Acknowledge N matching` — bulk-updates `lifecycle_state = 'already_seen'` for every row matching the active filter (regardless of page)
  - `Delete N matching` — hard-deletes rows matching the active filter. Confirm dialog required. Destructive.

**Row checkboxes**: render but are inert in v1. They reserve the visual slot for future row-selection work; bulk actions operate on the filter, not the selection. Revisit once real usage shows row-granular ack is needed.

**Table columns**:

| Column | Content |
|---|---|
| ☐ | Checkbox (inert, v1) |
| Added | `YYYY-MM-DD HH:MM:SS` from `validation_issues.id`'s correlated `scrape_runs.started_at` (see Data section). Default sort column. |
| State | Badge: `new` (red), `recurring` (amber), `seen` (neutral) |
| Issue | `● issue_type` — colored dot is severity (red=Critical, amber=Warning), text is monospace issue name |
| Field | Raw field name, muted text |
| Book/URL | Linked shop-book title if resolved; otherwise clickable raw URL. Max-width 240px with ellipsis. |
| Raw value | Monospace, truncated to ~60 chars with ellipsis. Full value in title attribute. |
| Run | `#<run_id>` link to `/runs/<id>` |
| (action) | `Ack` button (POST single-issue acknowledge). Hidden when `lifecycle_state == 'already_seen'`. |

**Pagination**: 50 per page. Always server-side. Footer row with `← Prev`, numeric page buttons (current, first, last, ±2 around current), `Next →`. No infinite scroll.

### Data changes

**Drop info-level issues entirely.** In `book_scraper/pipelines.py`:
- Remove all `field_missing` `_warn()` calls (both "was: {old}" and "never populated" branches)
- No migration needed for historical rows — they remain in the DB and are simply filtered out of the UI by the severity map. Optionally a one-shot cleanup script can be run, but the spec does not require it.

**Severity map** stays where it is now (`ISSUE_DESCRIPTIONS` and `ISSUE_SEVERITY` in `book_scraper/dashboard/queries.py`). The `field_missing` entry is removed from both maps.

**New timestamp column on validation_issues**: the current schema has no explicit creation time on `validation_issues`. Two options:
- **A.** Add `created_at` column (Alembic migration, default `now()`). Clean, precise per-row.
- **B.** Use `scrape_runs.started_at` via the existing FK. No migration, but all issues from the same run share a timestamp (OK — they were scraped together).

**Decision: B.** Cheaper, accurate enough — run IDs already group issues temporally. The `Added` column joins through `scrape_runs`. If granularity becomes a problem later, adding `created_at` is a trivial migration.

## Routes

### Replace

- `GET /validation` — now renders the flat list. Query params:
  - `state` (default `open`) — `open | new | recurring | already_seen | all`
  - `shop` (default ``) — shop name or empty for all
  - `issue_type` (default ``) — specific issue type or empty for all
  - `run_id` (default ``) — run ID or empty
  - `q` (default ``) — substring search against url/title
  - `sort` (default `added`) — only `added` supported
  - `order` (default `desc`) — `asc | desc`
  - `page` (default `1`) — 1-indexed

### Remove

- `GET /validation/{issue_type}` — legacy grouped detail. Deleted. Links from `/runs/{id}` updated to use the new filtered query.
- `GET /api/validation/{issue_type}/rows` — HTMX partial for the collapsed groups. Deleted.

### Add

- `POST /validation-issues/delete-matching` — bulk delete. Accepts the same filter params as `/validation` as form fields. Hard-deletes rows. Returns 303 back to `/validation` with filters preserved. Requires confirm on the client.

### Keep

- `POST /validation-issues/{id}/acknowledge` — single-row ack
- `POST /validation-issues/acknowledge-all` — now accepts the full filter set (shop, issue_type, run_id, q, state), not just issue_type + state

## Implementation notes

- `queries.py` gets a new `get_issues_page(session, filters, page, per_page)` that returns `(rows, total)` with a single JOIN through `scrape_runs` (for shop filter + timestamp) and a LEFT JOIN on `shop_books` (for title resolution). Shape is similar to `get_shop_books_page`.
- The existing `get_validation_groups`, `get_validation_issues_for_group`, and `get_validation_lifecycle_counts_by_type` helpers are removed. `get_validation_lifecycle_counts` stays, now accepts the full filter set.
- The new `validation.html` template is a clean rewrite patterned on `shop_books.html`. The existing `validation.html` and `validation_rows.html` (just added) are deleted.
- `validation_detail.html` is deleted.
- Row checkboxes render but have no wired behavior in v1 — no JS. They are a visual placeholder.
- Raw value truncation: server-side `{{ raw[:60] ~ '…' if raw|length > 60 else raw }}`, with full value in the `title` attribute so hover shows it. No modal, no expand.

## Testing

Integration tests (extend `tests/integration/test_dashboard_routes.py`):
- `GET /validation` renders without error at every lifecycle state
- Filter combinations: shop only, issue only, run only, shop+issue, search only, all-four
- Pagination: page 1, page 2, out-of-range page clamps
- Sort desc (default) and asc both render
- `POST /validation-issues/acknowledge-all` respects every filter param
- `POST /validation-issues/delete-matching` actually deletes matching rows and nothing else
- `GET /validation/<issue_type>` returns 404 (legacy route gone)

Unit tests for `pipelines.py`: confirm `field_missing` is no longer emitted from the field-diff path.

## Rollout

One PR, one commit. Docker rebuild of `dashboard` + `scraper` (the pipeline changed). Smoke test after:

```bash
docker compose build dashboard scraper && docker compose up -d dashboard scraper
uv run pytest tests/integration/test_dashboard_routes.py -v
```

No data migration. Historical `field_missing` rows stay in the DB, filtered out by the UI.

## Open questions

*Resolved during brainstorming:*
- Info-level handling → dropped entirely (option A)
- Scope → redesign only; new detections and tooling land later (option D)

*Deferred to follow-up specs:*
- New issue types to detect (`scrape_error`, `inactive_spike`, `price_anomaly`)
- External tool integration (Sentry / GitHub Issues) — likely unnecessary
