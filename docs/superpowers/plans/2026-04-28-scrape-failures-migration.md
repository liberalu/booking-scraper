# Scrape failures migration: dedicated `scrape_failures` table

## Context

Today, scrape failures are scattered and double-written:

- **`scrape_url_items.error_reason` / `http_status`** — denormalized columns on the queue row, overwritten on every retry. The retry history is lost.
- **`validation_issues`** — receives a parallel `http_4xx` / `http_5xx` / `request_error` / `empty_response` / `redirect_to_homepage` row for each failure ([scan.py:297, 324, 470, 488](book_scraper/spiders/scan.py)). Same fact, written twice, kept in sync by the spider's hot path.
- **No lifecycle / acknowledgments** for scrape failures. An operator can't mark a permanently-dead URL as "known" — the failure card surfaces it on every run.
- **No cross-run recurrence** signal. A 503 that's been failing for a week looks the same as a brand-new 503.

The fix is a dedicated **`scrape_failures`** table: append-only, FK-linked to `scrape_url_items`, holding the failure event with its own lifecycle. The queue row keeps `status` only; the failure detail moves out. `validation_issues` returns to its original purpose (data-quality issues on successfully fetched pages).

This is a three-PR migration. Each PR is independently shippable and reversible.

## End state

```
scrape_url_items                    scrape_failures (NEW)              validation_issues
─────────────────                   ───────────────────────            ──────────────────
status                              id PK                              id
url                                 scrape_url_item_id FK              scrape_run_id FK
url_type                            run_id, shop_id, url   (denorm)    url, field, issue
claimed_at, done_at                 discovered_url_id      (denorm)    raw_value
retry_count                         occurred_at                        lifecycle_state
                                    error_reason  (nullable)           ...
(error_reason DROPPED)              http_status   (nullable)
(http_status DROPPED)               attempt_number
                                    response_bytes
                                    error_detail
                                    lifecycle_state
                                    acknowledged_at
                                    acknowledged_note

   queue + audit                    failure event log + triage         data-quality triage
   one row per (run, url)           one row per failure event          one row per quality issue
   spider writes                    spider writes; operator acks       parser writes; operator acks
```

What goes where, end state:

| Trigger | Today | After |
|---|---|---|
| HTTP 4xx/5xx | `scrape_url_items.error_reason` + `validation_issues` (`http_4xx`/`http_5xx`) | `scrape_failures` only |
| Request errors (timeout, DNS, conn refused) | `scrape_url_items.error_reason` + `validation_issues` (`request_error`) | `scrape_failures` only |
| `empty_response` (body < 1024B) | `validation_issues` only | `validation_issues` (unchanged — quality signal on a successful fetch, not a transport failure) |
| `redirect_to_homepage` | `validation_issues` only | `validation_issues` (unchanged — same reason) |
| `run_aborted` / `stuck_in_processing` bulk-cleanup | `scrape_url_items.error_reason` only | `scrape_failures` (with `error_detail='bulk_cleanup'`) |
| Missing/invalid title, price, ISBN, etc. | `validation_issues` | unchanged |
| `scrape_run_failed` (one per failed run) | `validation_issues` | unchanged |
| Run-level close_reason | `scrape_runs.close_reason` | unchanged |

## Schema (additive)

```sql
-- alembic migration: add scrape_failures
CREATE TABLE scrape_failures (
    id                   SERIAL PRIMARY KEY,
    scrape_url_item_id   INTEGER NOT NULL
                         REFERENCES scrape_url_items(id) ON DELETE CASCADE,
    run_id               INTEGER NOT NULL REFERENCES scrape_runs(id),
    shop_id              INTEGER NOT NULL REFERENCES shops(id),
    url                  TEXT NOT NULL,
    discovered_url_id    INTEGER REFERENCES discovered_urls(id),

    occurred_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_reason         TEXT,                                   -- nullable: real bucket
    http_status          INTEGER,                                -- nullable: real bucket
    -- attempt_number intentionally omitted: order by occurred_at; compute
    -- "Nth attempt" at read time via ROW_NUMBER() if needed. Avoids the
    -- "where does the count come from" footgun (retry_count is read-only
    -- in this codebase; deriving from MAX() races; an explicit counter
    -- adds an invariant nobody enforces).
    response_bytes       INTEGER,
    error_detail         TEXT,                                   -- exception class / body excerpt

    lifecycle_state      validation_lifecycle_enum NOT NULL DEFAULT 'new',
    acknowledged_at      TIMESTAMPTZ,
    acknowledged_note    TEXT
);

-- Failure-card grouping query (filter run_id, group by reason+http)
CREATE INDEX ix_scrape_failures_run_bucket
    ON scrape_failures(run_id, error_reason, http_status);

-- Cross-run recurrence ("has this URL+reason failed before?")
CREATE INDEX ix_scrape_failures_shop_url
    ON scrape_failures(shop_id, url);

-- Open-issues inbox query (already_seen rows hidden by default)
CREATE INDEX ix_scrape_failures_lifecycle_open
    ON scrape_failures(lifecycle_state) WHERE lifecycle_state != 'already_seen';

-- "What failed in the last hour" timeline queries
CREATE INDEX ix_scrape_failures_occurred_at
    ON scrape_failures(occurred_at DESC);
```

`validation_lifecycle_enum` already exists ([db/models.py:541](book_scraper/db/models.py:541)) — reuse it. `ON DELETE CASCADE` mirrors the existing `cleanup_scrape_url_items` semantics: if the queue row is gone, decontextualized failure events go with it.

---

## PR 1 — Schema, model, dual-write, backfill

**Goal:** `scrape_failures` exists and gets populated for every new failure. Old data is backfilled. No reads change. Existing `validation_issues` and `scrape_url_items.error_reason` writes are preserved (dual-write).

### 1.1 Alembic migration

`alembic/versions/<rev>_add_scrape_failures.py`:
- Schema as above.
- Backfill in the same migration:
  ```sql
  INSERT INTO scrape_failures
    (scrape_url_item_id, run_id, shop_id, url, discovered_url_id,
     occurred_at, error_reason, http_status,
     response_bytes, error_detail, lifecycle_state)
  SELECT
      sui.id, sui.run_id, sui.shop_id, sui.url, sui.discovered_url_id,
      COALESCE(sui.done_at, sui.claimed_at, NOW()),
      sui.error_reason, sui.http_status,
      NULL, NULL, 'new'
  FROM scrape_url_items sui
  WHERE sui.status = 'failed';
  ```
  This gets the historical 144 failures on run #199 (and every other failed row in the table) into the new table. One row per failed item — retry history before the migration is lost (it's already lost on `scrape_url_items`), but going forward each retry creates its own row.

### 1.2 Model

[book_scraper/db/models.py](book_scraper/db/models.py): add `class ScrapeFailure(Base)` mirroring the schema. Reuse `validation_lifecycle_enum`. Add backref `scrape_url_item.failures: Mapped[list[ScrapeFailure]]`.

### 1.3 Repo: dual-write helper

[book_scraper/db/repo.py](book_scraper/db/repo.py):
- New helper. Append-only — no idempotency check, no derived attempt counter. Each call site fires exactly once per failure event by construction (single writer, transaction-scoped). If a real double-call ever surfaced as duplicate rows, that's a bug worth seeing in the data, not papering over with a silent skip.
  ```python
  def record_scrape_failure(
      session: Session,
      *,
      scrape_url_item: ScrapeUrlItem,
      error_reason: str | None,
      http_status: int | None,
      response_bytes: int | None = None,
      error_detail: str | None = None,
  ) -> None:
      """Append a scrape_failures row for a failure event."""
      session.add(ScrapeFailure(
          scrape_url_item_id=scrape_url_item.id,
          run_id=scrape_url_item.run_id,
          shop_id=scrape_url_item.shop_id,
          url=scrape_url_item.url,
          discovered_url_id=scrape_url_item.discovered_url_id,
          error_reason=error_reason,
          http_status=http_status,
          response_bytes=response_bytes,
          error_detail=error_detail,
      ))
  ```

- Wire into every site that flips a row to `failed`:
  - [`mark_scrape_url_item_response`](book_scraper/db/repo.py:1477) — when `success=False`. Pass response_bytes and the exception class string as `error_detail` if available.
  - [`run_aborted` cleanup](book_scraper/db/repo.py:754) — bulk-fail with `error_detail='run_aborted'`. Use `bulk_save_objects` for performance.
  - [`mark_orphan_runs_failed`](book_scraper/db/repo.py:953) and the stuck-in-processing reaper at line 824 — same shape, `error_detail='stuck_in_processing'` / `'orphan_on_boot'`.

  Each call site continues to set `scrape_url_items.error_reason` and `http_status` as before (dual-write) so PR 2 readers can still see the values during the transition.

### 1.4 Tests

[tests/integration/test_repo.py](tests/integration/test_repo.py) (or new `test_scrape_failures.py`):
- A failed mark inserts exactly one `ScrapeFailure`; second mark with the same `attempt_number` is idempotent.
- A retry (incremented `retry_count`) inserts a new row with `attempt_number=2`.
- Bulk cleanup (`run_aborted`) inserts one row per affected item.
- Backfill migration test: seed `scrape_url_items` rows pre-migration, run upgrade, assert `scrape_failures` count matches.

### 1.5 Verification

```bash
PYTHONPATH=. uv run alembic upgrade head
uv run pytest tests/integration/test_repo.py -v
uv run pytest tests/integration/test_dashboard_routes.py -v
```

In the running scraper:
```bash
docker compose exec scraper uv run scrapy crawl scan -a shop=vaga -a max_urls=20
docker compose exec postgres psql -U postgres -d book_scraper -c \
  "SELECT count(*), error_reason FROM scrape_failures GROUP BY 1, 2 ORDER BY 1 DESC;"
```
Expect rows for any HTTP errors that occurred during the smoke run, and the historical 144 (from run #199 etc.) from the backfill.

---

## PR 2 — Switch reads to scrape_failures; add recurrence + acknowledgments

**Goal:** Failure card, `/issues` page, retry endpoint all read from `scrape_failures`. Cross-run recurrence ships. Acknowledgment UI ships.

### 2.1 Failure card grouping (current failures only)

[book_scraper/dashboard/queries.py](book_scraper/dashboard/queries.py:613) — `get_run_failure_groups`:
- The card answers "what is failed *right now* in this run". Source must therefore filter on **current queue state**, not on the append-only event log.
- Query shape (using a window function to pick each item's latest event):
  ```python
  latest = (
      session.query(
          ScrapeFailure,
          func.row_number().over(
              partition_by=ScrapeFailure.scrape_url_item_id,
              order_by=ScrapeFailure.occurred_at.desc(),
          ).label("rn"),
      )
      .filter(ScrapeFailure.run_id == run_id)
      .subquery()
  )
  q = (
      session.query(latest.c.error_reason, latest.c.http_status, func.count())
      .join(ScrapeUrlItem, ScrapeUrlItem.id == latest.c.scrape_url_item_id)
      .filter(latest.c.rn == 1, ScrapeUrlItem.status == "failed")
      .group_by(latest.c.error_reason, latest.c.http_status)
  )
  ```
  This keeps the public payload contract (`reason`/`reason_display`/`reason_is_null`/`http`/`http_is_null`/`count`/`examples`) but the rows that retry-and-succeed disappear from the card the moment the queue row flips to `done`. The full event history stays in `scrape_failures` for `/issues` and the timeline view.
- Filter out `lifecycle_state='already_seen'` (on the latest event) by default; add `?include_acked=true` query param to surface them.
- New field per group: `recurring_in_runs` — the count of distinct prior runs (last 5, same `shop_id`+`error_reason`+`http_status`) that had ≥1 `scrape_failures` event in the same bucket. **Status-blind on purpose** — recurrence asks "how often has this kind of failure happened historically", not "is it still bleeding right now". Surfaces as a chip on the failure card row.

### 2.2 URLs view filter

[book_scraper/dashboard/queries.py:730](book_scraper/dashboard/queries.py:730) — `get_run_url_items`:
- Today filters by `scrape_url_items.error_reason` / `http_status` directly (work done in the prior session).
- Switch the `error_reason` / `http_status` predicates to a `LATERAL`-style subquery picking the **latest** `scrape_failures` row per item by `occurred_at`:
  ```python
  latest = (
      session.query(
          ScrapeFailure.scrape_url_item_id,
          ScrapeFailure.error_reason,
          ScrapeFailure.http_status,
          func.row_number().over(
              partition_by=ScrapeFailure.scrape_url_item_id,
              order_by=ScrapeFailure.occurred_at.desc(),
          ).label("rn"),
      )
      .subquery()
  )
  q = q.outerjoin(
      latest,
      and_(latest.c.scrape_url_item_id == ScrapeUrlItem.id, latest.c.rn == 1),
  )
  if error_reason_is_null:
      q = q.filter(latest.c.error_reason.is_(None))
  elif error_reason:
      q = q.filter(latest.c.error_reason == error_reason)
  # same for http_status
  ```
  The History card row rendering reads `error_reason` / `http_status` from the joined latest failure (NULL for non-failed rows). When the current `status` is `done` after a retry-success, the JOIN brings back the *historical* latest failure — but the History row's status pill is `done`, so the operator sees the right thing visually (success row, with an attribute showing what its last failure had been). If that's confusing, the row renderer can suppress the failure detail for non-failed rows.

### 2.3 Retry endpoint

[book_scraper/dashboard/routes/api.py](book_scraper/dashboard/routes/api.py) `api_retry_run_failures`:
- Filter selection: candidate rows are `scrape_url_items.status='failed'` whose **latest** `scrape_failures` event matches the requested `error_reason` / `http_status` (same window-function subquery as the failure card). This guarantees consistency: retry acts on exactly the rows the failure card just showed.
- The reset itself still UPDATEs `scrape_url_items` (status → pending, claimed_at/done_at → NULL). It no longer needs to NULL `error_reason`/`http_status` on the queue row (those columns are about to be dropped in PR 3); for the duration of PR 2 it still sets them to NULL for consistency with anything still reading them.
- Don't touch `scrape_failures` rows on retry — they are the **history**. The next failure for the same item INSERTs a fresh row; ordering is by `occurred_at`.

### 2.4 `/issues` page UNION

[book_scraper/dashboard/queries.py:903](book_scraper/dashboard/queries.py:903) — `get_issues_page`:
- Build a UNION ALL of two subqueries:
  - `validation_issues` (existing shape).
  - `scrape_failures` projected to the same shape: `kind='scrape_failure'`, `issue=error_reason or 'unknown'`, `severity` from new `SCRAPE_FAILURE_SEVERITY` map, `lifecycle_state` from the row.
- Add `kind` column to the API response. Frontend tab strip gains "All / Data quality / Scrape failures" filters.

### 2.5 Severity for scrape failures

[book_scraper/dashboard/queries.py:78](book_scraper/dashboard/queries.py:78):
```python
SCRAPE_FAILURE_SEVERITY = {
    "http_4xx":          "warning",     # bucket — matched by http_status range
    "http_5xx":          "warning",     # bucket — matched by http_status range
    "request_error":     "critical",    # prefix match (request_error:Foo)
    "rate_limited":      "warning",
    "anti_bot_detected": "critical",
    "robots_disallowed": "warning",
    "soft_404":          "warning",
    "schema_drift":      "critical",
}

def severity_for_failure(error_reason: str | None, http_status: int | None) -> str:
    """Classify a scrape failure. http_status range wins when present so
    error_reason='http_503' (per-status, today's actual writes) maps to
    the http_5xx bucket without a backfill rewrite."""
    if http_status is not None:
        if 400 <= http_status < 500:
            return SCRAPE_FAILURE_SEVERITY["http_4xx"]
        if 500 <= http_status < 600:
            return SCRAPE_FAILURE_SEVERITY["http_5xx"]
    if error_reason:
        prefix = error_reason.split(":", 1)[0]
        return SCRAPE_FAILURE_SEVERITY.get(prefix, "warning")
    return "warning"
```
This handles the actual data shape (`error_reason='http_503'`, `http_status=503`) without rewriting historical rows. `request_error:TimeoutError` falls through to the prefix lookup and resolves to `critical`. NULL/unknown both default to `warning`.

### 2.6 Acknowledgment UI

[book_scraper/dashboard/static/hifi/hf-runs.jsx](book_scraper/dashboard/static/hifi/hf-runs.jsx) — Failure card per-group row:
- Add **Mark as known** button (was "Skip permanently disabled" in the expanded row). POSTs to new `POST /api/runs/{run_id}/failures/ack` with `error_reason`, `http_status`, `*_is_null` flags.
- Endpoint flips matching `scrape_failures.lifecycle_state` to `already_seen`, sets `acknowledged_at = now()`. Card refreshes; bucket disappears (or shows dimmed if `?include_acked=true`).

### 2.7 Tests

- Failure-card grouping returns expected groups + recurrence count for a multi-run fixture.
- Retry endpoint still flips matching items to pending; assert `scrape_failures` history is preserved (not deleted).
- `/api/issues?kind=scrape_failure` returns scrape failures only; `kind=validation` returns the existing data-quality set; default returns both.
- Mark-as-known endpoint flips lifecycle and the bucket vanishes from the default failure card.

---

## PR 3 — De-dup `validation_issues`; drop denormalized columns

**Goal:** `validation_issues` no longer carries transport/HTTP errors. `scrape_url_items.error_reason` / `http_status` are gone. One source of truth for everything.

### 3.1 Stop writing transport errors to `validation_issues`

Remove the `_report_validation` calls for the **transport-failure** issue types only:

[book_scraper/spiders/scan.py:297, 324, 470, 488](book_scraper/spiders/scan.py):
- Remove `_report_validation("http_4xx", ...)`, `_report_validation("http_5xx", ...)`, `_report_validation("request_error", ...)`. These are double-writes — `scrape_failures` (from PR 1) is the single source of truth now.

**Keep** `_report_validation("empty_response", ...)` at [scan.py:352](book_scraper/spiders/scan.py:352) and `_report_validation("redirect_to_homepage", ...)` at [scan.py:365](book_scraper/spiders/scan.py:365). These fire on **HTTP 200 fetches** that the spider continues to parse — the queue row goes to `done`, not `failed`. They're page-quality signals, the same kind of thing as `missing_isbn` / `suspicious_title`. Wrong table to remove them from.

[book_scraper/dashboard/queries.py:78](book_scraper/dashboard/queries.py:78) — `ISSUE_SEVERITY`: leave `empty_response` / `redirect_to_homepage` keys in (or add them if they're not currently mapped — both default to `warning` today). Don't add `http_4xx` / `http_5xx` / `request_error` to this map; their severity comes from `SCRAPE_FAILURE_SEVERITY` via the function in §2.5.

### 3.2 One-shot cleanup of orphaned `validation_issues` rows

Alembic data migration:
```sql
DELETE FROM validation_issues
 WHERE issue IN ('http_4xx','http_5xx','request_error');
```
Only the three transport-error issue types — they were the genuine double-writes; their factual content lives in `scrape_failures` (PR 1 backfill covered the historical rows). `empty_response` / `redirect_to_homepage` are kept (they were never duplicated; they're page-quality signals on HTTP 200 fetches). The `scrape_run_failed` summary row also stays — it's a run-level event.

### 3.3 Drop denormalized columns

Alembic migration:
```sql
ALTER TABLE scrape_url_items DROP COLUMN error_reason;
ALTER TABLE scrape_url_items DROP COLUMN http_status;
```
Update the model. Search-and-replace any remaining reader (run-detail page response shape includes these — they should already be reading from `scrape_failures` after PR 2; if anything still references them, it's a missed reader).

### 3.4 Verification

- Smoke run produces zero new `http_4xx` / `request_error` / etc. rows in `validation_issues`.
- Dashboard route tests still green.
- Failure card on `/runs/199` looks identical to before (same buckets, same counts, plus recurrence chip and ack button).

---

## Out of scope

- **`anti_bot_detected`, `soft_404`, `schema_drift` detectors** — these were named in the taxonomy but require parser-side detection logic not present today. Each is a separate small PR that emits the new `error_reason` value through the same `record_scrape_failure` path; no schema change.
- **Discover-phase failure capture** (`sitemap_fetch_failed`, `category_page_failed`) — currently only `validation_issues`. Same separate PR pattern: route them through `record_scrape_failure` with `url_type='sitemap'` / `'category'`.
- **`scrape_runs.close_reason='stalled'`** for the stall-detection extension. Mentioned as a gap; doesn't block this migration.
- **Operator UI for adding `acknowledged_note`** — endpoint accepts it, but the failure card UI just sends an empty string for now; adding a textarea is one frontend follow-up.

## Sequencing summary

| PR | Schema | Writes | Reads | Deletes |
|---|---|---|---|---|
| **1** | Add `scrape_failures` table | Dual-write (old + new) | unchanged | — |
| **2** | — | unchanged | Switch to `scrape_failures` | — |
| **3** | Drop `error_reason` / `http_status` from `scrape_url_items`; trim `validation_issues` | Stop writing dupes | unchanged from PR 2 | one-time `DELETE FROM validation_issues WHERE issue IN (...)` |

Each PR is reversible:
- PR 1 — no consumer reads from the new table; rolling back drops the table cleanly.
- PR 2 — readers can be flipped back to the old columns (still populated by dual-write).
- PR 3 — destructive (column drops, row deletes); should land only after PR 2 has soaked for a couple of runs.

## Verification (per PR)

```bash
# PR 1
PYTHONPATH=. uv run alembic upgrade head
uv run pytest tests/integration/ -v
docker compose build dashboard scraper && docker compose up -d dashboard scraper
docker compose exec scraper uv run scrapy crawl scan -a shop=vaga -a max_urls=20

# PR 2
uv run pytest tests/integration/test_dashboard_routes.py -v
# Manual: load /runs/199, confirm Failures card shows recurrence chip and Mark-as-known
# Manual: load /issues, confirm scrape failures appear with kind tab

# PR 3
PYTHONPATH=. uv run alembic upgrade head
uv run pytest tests/integration/ -v
docker compose exec scraper uv run scrapy crawl scan -a shop=vaga -a max_urls=20
docker compose exec postgres psql -U postgres -d book_scraper -c \
  "SELECT count(*) FROM validation_issues WHERE issue IN ('http_4xx','http_5xx','request_error');"
# Expect: 0
docker compose exec postgres psql -U postgres -d book_scraper -c \
  "SELECT count(*) FROM validation_issues WHERE issue IN ('empty_response','redirect_to_homepage');"
# Expect: > 0 if the smoke run produced any (these intentionally remain)
```
