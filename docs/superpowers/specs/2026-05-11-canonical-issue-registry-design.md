# Canonical Issue Registry Design

**Date:** 2026-05-11  
**Status:** Approved

## Problem

`validation_issues` is an append-only log: every validation run inserts fresh rows for every
detected problem. A single known data-quality fact (e.g., humanitas book with no ISBN) generates
one new row per run, so after 50 runs the table holds 50 identical rows. The inbox mixes truly
new problems with hundreds of recurring, already-accepted issues — there is no clean signal.

Two symptoms:
1. **Inbox flooding** — "Open" tab shows `new` and `recurring` together; hard to spot real problems.
2. **Unbounded table growth** — known issues accumulate without bound.

## Goal

Transform `validation_issues` from an append-only log into a **canonical issue registry**: one row
per unique (entity × field × issue_type), updated in-place each run. The inbox default shows only
genuinely new problems. A grouped view surfaces fleet-level patterns.

---

## Data Model

### Schema Changes

| Column | Change | Notes |
|--------|--------|-------|
| `scrape_run_id` | rename → `last_seen_run_id` | FK to the most recent run where detected |
| `shop_id` | add (INT, FK shops, NOT NULL) | denormalized for fast per-shop queries |
| `first_seen_run_id` | add (INT, FK scrape_runs) | for "first seen" display |
| `run_count` | add (INT, NOT NULL, default 1) | how many runs this issue appeared in |
| `resolved_at` | add (TIMESTAMP nullable) | set when issue stops appearing |
| `snoozed_until` | add (TIMESTAMP nullable) | for future per-issue snooze |

### Lifecycle States (enum `validation_lifecycle`)

| Old value | New value | Meaning |
|-----------|-----------|---------|
| `new` | `new` | First detected, or reappeared after resolution |
| `recurring` | *removed* | Signal replaced by `run_count > 1` |
| `already_seen` | `acknowledged` | User accepted this issue |
| *(none)* | `snoozed` | Suppressed until `snoozed_until` datetime |
| *(none)* | `resolved` | Not detected in most recent full shop validation |

### Unique Constraints

Three partial unique indexes enforce one canonical row per entity × issue pair:

```sql
UNIQUE (shop_book_id, field, issue)      WHERE shop_book_id IS NOT NULL
UNIQUE (discovered_url_id, field, issue) WHERE discovered_url_id IS NOT NULL
UNIQUE (url, field, issue)               WHERE shop_book_id IS NULL AND discovered_url_id IS NULL
```

### State Machine

```
         [user ack]              [not detected next run]
new ─────────────────→ acknowledged ──────────────────────→ resolved
 ↑    [not detected]                                            │
 │    next run         [user ack]                               │
 │   new ───────────→ resolved                                  │
 └────────────────────── reappears ────────────────────────────┘
 
new ──[user snooze]──→ snoozed ──[expires + still detected]──→ new
                               ──[not detected]───────────────→ resolved
```

Transitions:
- `new` → `acknowledged`: explicit user action
- `new` / `acknowledged` / `snoozed` → `resolved`: automatic when issue absent from next full run
- `resolved` → `new`: automatic when issue reappears in a later run
- `snoozed` → `new`: automatic when `snoozed_until` has passed and issue still detected

---

## Write Path

### Replace bulk_insert with upsert

`bulk_insert_validation_issues` and `_assign_lifecycle_states` are replaced by a single
`upsert_validation_issues(session, issues, shop_id, run_id)` function.

**Per detected issue:**

```
canonical_row = lookup by (entity_key, field, issue_type)

if not found:
    INSERT lifecycle_state='new', run_count=1, first/last_seen_run_id=run_id

elif canonical_row.lifecycle_state == 'resolved':
    UPDATE lifecycle_state='new', last_seen_run_id=run_id, run_count++, raw_value

else:  # new / acknowledged / snoozed
    UPDATE last_seen_run_id=run_id, run_count++, raw_value
    if snoozed and snoozed_until <= now():
        lifecycle_state = 'new'
```

Implementation uses `INSERT … ON CONFLICT DO UPDATE` (PostgreSQL upsert) for atomicity and
performance. Because the three unique partial indexes have different conflict targets
(shop_book_id, discovered_url_id, url×nulls), the batch is split into three typed sub-batches
before upserting — one per entity type.

### Auto-resolve Gone Issues

After upserting all detected issues, call `resolve_gone_issues(session, shop_id, run_id)`:

```sql
UPDATE validation_issues
SET    lifecycle_state = 'resolved',
       resolved_at     = now()
WHERE  shop_id          = :shop_id
  AND  last_seen_run_id != :run_id
  AND  lifecycle_state  IN ('new', 'acknowledged', 'snoozed')
```

This marks any open issue that was absent from the current run as resolved. If a shop fixes its
missing-ISBN problem, those canonical rows quietly move to Resolved in the same validation pass.

### ValidateService.run() Changes

```python
def run(self, shop_id: int, run_id: int) -> dict[str, int]:
    issues = []
    issues.extend(self.check_structural_duplicates(shop_id, run_id))
    # … other check groups unchanged …

    if issues:
        upsert_validation_issues(self._session, issues, shop_id=shop_id, run_id=run_id)

    resolve_gone_issues(self._session, shop_id=shop_id, run_id=run_id)

    return counters
```

---

## Read Path

### Query Layer Changes

- `get_issues_page()` updated: remove `recurring` filter branch; add `resolved_at`,
  `first_seen_run_id`, `run_count`, `snoozed_until` to returned fields.
- State filter mapping:

  | Tab | `state` param | SQL filter |
  |-----|--------------|-----------|
  | New | `new` | `lifecycle_state = 'new'` |
  | Acknowledged | `acknowledged` | `lifecycle_state = 'acknowledged'` |
  | Snoozed | `snoozed` | `lifecycle_state = 'snoozed'` |
  | Resolved | `resolved` | `lifecycle_state = 'resolved'` |
  | All | *(empty)* | no filter |

- New query function `get_issues_groups(session, group_by, shop_id?, state?)` — see Groups section.

### API Changes

`GET /api/issues` — same query params; `state` default changes to `"new"`. Response includes
new fields: `run_count`, `first_seen_at`, `last_seen_at`, `resolved_at`, `snoozed_until`.

New endpoint: `GET /api/issues/groups` — see Groups section.

---

## Grouped View

### Purpose

Surface fleet-level patterns: "234 humanitas books with no ISBN" is one line, not 234 rows.
Two grouping modes:

| Mode | Key | Example row |
|------|-----|-------------|
| **By type** | `issue_type` | `missing_isbn · critical · 234 books · [12 new · 220 ack]` |
| **By type × shop** | `(issue_type, shop)` | `humanitas / missing_isbn · 234 · [12 new · 220 ack]` |

### API Endpoint

```
GET /api/issues/groups
  ?group_by=type|type_shop
  &state=new|acknowledged|snoozed|resolved   (optional — filters which issues count)
  &shop=humanitas                             (optional)
```

Response row shape:
```json
{
  "issue_type": "missing_isbn",
  "shop": "humanitas",        // null when group_by=type
  "severity": "critical",
  "total": 234,
  "by_state": { "new": 12, "acknowledged": 220, "resolved": 2, "snoozed": 0 }
}
```

SQL: `GROUP BY issue, (shop_id)` with `COUNT(*)` and `COUNT(*) FILTER (WHERE lifecycle_state = …)`.

### Bulk Acknowledge

Each group row has an "Ack all" button → `POST /api/issues/bulk-acknowledge` with body
`{ "issue_type": "missing_isbn", "shop_id": 3 }` (shop_id optional for type-only groups).

```sql
UPDATE validation_issues
SET    lifecycle_state = 'acknowledged',
       acknowledged_at = now()
WHERE  issue            = :issue_type
  AND  (:shop_id IS NULL OR shop_id = :shop_id)
  AND  lifecycle_state  = 'new'
```

### UI

The issues page gains a view-mode toggle: **List | By type | By type × shop**.

- Default view: **List** (filtered to `new`).
- Clicking a group row navigates to the flat list filtered to that issue_type (and shop if applicable).
- Group rows show severity badge, total count, and a `new` sub-count badge.
- "Ack all" button on each group row; confirmation not required (reversible by un-acknowledging).

---

## Dashboard Tabs

Replace current tabs (Open / Needs triage / Known / Snoozed / Resolved / All):

| New Tab | `state` | Default |
|---------|---------|---------|
| New | `new` | ✓ |
| Acknowledged | `acknowledged` | |
| Snoozed | `snoozed` | |
| Resolved | `resolved` | |
| All | *(empty)* | |

The `New` tab count (shown in badge) is the primary health signal: zero means no unreviewed issues.

---

## Migration Strategy

Single Alembic migration in two phases within one transaction-safe script:

### Phase 1 — Schema

1. Add columns: `shop_id`, `first_seen_run_id`, `run_count` (default 1), `resolved_at`, `snoozed_until`.
2. Populate `shop_id` from `shop_books.shop_id` (join via `shop_book_id`) or
   `discovered_urls.shop_id` (join via `discovered_url_id`).
3. Populate `first_seen_run_id` = `last_seen_run_id` (same as current `scrape_run_id`).
4. Rename column `scrape_run_id` → `last_seen_run_id`.
5. Alter `validation_lifecycle` enum: add `acknowledged`, `snoozed`, `resolved`; keep `new`.

### Phase 2 — Data Deduplication

For each `(COALESCE(shop_book_id, -1), COALESCE(discovered_url_id, -1), url, field, issue)` group:

1. Identify the canonical row (highest `id`).
2. Update it: `run_count = COUNT(group)`, `first_seen_run_id = MIN(scrape_run_id of group)`,
   `lifecycle_state`:
   - Any in group acknowledged → `acknowledged`
   - Else `recurring` → `new`  
   - Else keep `new`
3. Delete all other rows in the group.

### Phase 3 — Constraints & Cleanup

1. Drop old `recurring` and `already_seen` from enum (after data migration).
2. Add partial unique indexes.
3. Add index on `(shop_id, lifecycle_state)`.
4. Add NOT NULL constraint on `shop_id` (after backfill).

---

## Files Changed

| File | Change |
|------|--------|
| `alembic/versions/XXXXXX_canonical_issue_registry.py` | Migration (schema + data) |
| `book_scraper/db/models.py` | Update `ValidationIssue` model + enum |
| `book_scraper/db/repo.py` | Replace `bulk_insert_validation_issues` + `_assign_lifecycle_states` with `upsert_validation_issues` + `resolve_gone_issues`; add `get_issues_groups` + `bulk_acknowledge_issues` |
| `book_scraper/services/validate.py` | Call `upsert_validation_issues` + `resolve_gone_issues` |
| `book_scraper/dashboard/queries.py` | Update `get_issues_page`; add `get_issues_groups` |
| `book_scraper/dashboard/routes/api.py` | Update `/issues` endpoint; add `/issues/groups` + `/issues/bulk-acknowledge` |
| `book_scraper/dashboard/static/hifi/hf-other.jsx` | Update `HFIssues` tabs, add view-mode toggle, group rows, "Ack all" |
| `tests/unit/test_validate_spider.py` | Update lifecycle state references |
| `tests/integration/test_scrape_runs_repo.py` | Update / add upsert + resolve tests |

---

## Out of Scope

- Per-issue snooze UI (column added, endpoint deferred).
- Notification/alerting on new issues.
- Issue comments or history log.
