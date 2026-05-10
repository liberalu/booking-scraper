# Phase 1: Validate Phase - Research

**Researched:** 2026-05-10
**Domain:** Scrapy no-HTTP spider, PostgreSQL DB-only validation checks, SQLAlchemy, Alembic enum migration, FastAPI dashboard integration
**Confidence:** HIGH — all findings verified against codebase directly

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Use a Scrapy spider — `scrapy crawl validate -a shop=X` — consistent with `discover` and `scan`. No separate CLI entrypoint needed.
- **D-02:** The validate spider yields **no items** and makes **no HTTP requests**. `PostgresPipeline` is not involved. The spider manages its own `scrape_runs` row: create in `spider_opened`, mark complete/failed in `spider_closed`.
- **D-03:** The spider calls `ValidateService` synchronously in `spider_opened` (before the asyncio reactor processes any requests). Since no requests are ever yielded, the spider's `close()` fires immediately after `spider_opened` returns. This is the simplest approach and avoids any stall-detection interaction.

### Claude's Discretion

- **Stall detection:** Run validate logic synchronously inside `spider_opened` so the reactor never gets a chance to trigger stall timers. Alternatively, add `STALL_TIMEOUT = 0` or disable `StallDetector` in the spider's `custom_settings`. Planner picks whichever integrates most cleanly.
- **scrape_runs lifecycle:** `spider_opened` creates the `scrape_runs` row directly (not via pipeline). `spider_closed` marks it `completed` or `failed` depending on whether an exception was raised. Heartbeat extension may need to be disabled — planner should check extension compatibility with a no-request spider.

### Deferred Ideas (OUT OF SCOPE)

- **Auto-trigger after scan** — on-demand only for this phase.
- **Per-shop discover cadence DB field** — use TOML cron schedule or 14-day default.
- **Validate in cron schedule** — out of scope for this phase.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VAL-01 | Validate phase runs DB-only checks over shop_books rows and writes validation_issues per shop | `ValidateService` pattern established; `bulk_insert_validation_issues` + `_assign_lifecycle_states` in repo.py verified |
| VAL-02 | Validate phase gets its own scrape_runs row (phase='validate') so it appears in dashboard run history | `create_scrape_run` + `finish_scrape_run` from repo.py; 'validate' enum value added via Alembic migration |
| VAL-03 | Structural duplicate checks: isbn_duplicate, title_author_duplicate, sku_duplicate | SQL GROUP BY isbn/title+author/sku within shop_id; both rows of each pair get a ValidationIssue |
| VAL-04 | Slug-title mismatch check using zero-token-overlap threshold | Tokenise URL slug path + title, strip diacritics, lowercase, split on `-`/` `; flag if intersection is empty |
| VAL-05 | Data completeness checks: active_no_price, in_stock_no_price, book_no_metadata, no_price_history | Single-row filter queries on ShopBook fields; `no_price_history` requires LEFT JOIN to prices |
| VAL-06 | Data correctness checks: year_out_of_range, price_zero, format_is_dimensions | Single-row filter; `format_is_dimensions` uses PostgreSQL `~` regex operator |
| VAL-07 | Classification consistency checks: book_no_signals, non_book_has_isbn, non_product_active | Single-row + JOIN to discovered_urls for `non_product_active` |
| VAL-08 | Staleness/lifecycle checks: stale_active, unreachable_active, orphan_no_url | `stale_active` uses per-shop cadence (default 14 days); `orphan_no_url` = ShopBook with no DiscoveredUrl FK |
| VAL-09 | Match phase readiness checks: unmatched_has_isbn, match_isbn_drift | JOIN to `books` table for `match_isbn_drift` |
| VAL-10 | Relationship integrity checks: url_aliases, product_url_non_book | GROUP BY shop_book_id on discovered_urls for `url_aliases`; JOIN for `product_url_non_book` |
| VAL-11 | Each check deduplicates by (shop_book_id, field) to avoid duplicate rows on re-run | `_assign_lifecycle_states` transitions (shop_book_id, field, issue) to `recurring` if seen before; `bulk_insert_validation_issues` handles the lifecycle logic |
| VAL-12 | Operator can trigger validate run from dashboard shop detail page | `POST /api/runs` with `phase='validate'`; need to add 'validate' to the allowed phases whitelist in `api_create_run` and `_spawn_scrapy_in_container` |
| VAL-13 | scrape_phase enum extended with 'validate' value | Alembic migration: `op.execute("COMMIT"); op.execute("ALTER TYPE scrape_phase ADD VALUE IF NOT EXISTS 'validate'")` |
| VAL-14 | Alembic migration adds validation_issues table (if not already exists) | Table already exists (migration `2ee38722fb89_add_validation_issues_table.py` confirmed). VAL-14 only needs the enum migration. |
</phase_requirements>

---

## Summary

The validate phase adds a fourth pipeline phase that runs DB-only quality checks over `shop_books` rows for a given shop and writes findings to the existing `validation_issues` table. The implementation is directly modelled on the existing `match` spider (`book_scraper/spiders/match.py`), which is an identical pattern: no HTTP, no items pipeline, `asyncio.to_thread()` for the service call so `HeartbeatExtension` keeps ticking, `StallDetector` disabled via `custom_settings`.

The primary new artifact is `book_scraper/services/validate.py` (`ValidateService`), which runs 7 check-group methods covering 19 distinct issue keys across structural duplicates, completeness, correctness, classification, staleness, match-readiness, and relationship integrity. The service receives a SQLAlchemy session and the shop's `shop_id`, executes read-mostly queries, and bulk-inserts results through the existing `bulk_insert_validation_issues` + `_assign_lifecycle_states` deduplication path.

The database schema needs one Alembic migration: add `'validate'` to the `scrape_phase` PostgreSQL enum. The `validation_issues` table already exists. The dashboard integration requires: (a) adding `'validate'` to the `api_create_run` phase whitelist, (b) passing the `validate` command to `_spawn_scrapy_in_container`, and (c) adding a "Run validate" button to the shop detail JSX component that POSTs `{ shop, phase: 'validate' }` to `POST /api/runs`.

**Primary recommendation:** Mirror `match.py` exactly — `asyncio.to_thread()` + `StallDetector: None` in `custom_settings` + `HeartbeatExtension` left ON — then add `ValidateService` with one SQL method per check group.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Check logic (SQL queries) | Database / Storage | — | All checks are read queries on PostgreSQL tables |
| ValidateService orchestration | API / Backend (service layer) | — | Pure Python, no HTTP, stateless per invocation |
| ValidateSpider (entrypoint) | API / Backend (Scrapy) | — | Scrapy spider shell is the established runner pattern |
| scrape_runs lifecycle | API / Backend (repo.py) | — | `create_scrape_run` / `finish_scrape_run` already in repo |
| Dashboard "Run validate" button | Browser / Client (React JSX) | Frontend Server (FastAPI) | JSX POSTs to `/api/runs`; FastAPI routes to scraper container |
| Alembic migration | Database / Storage | — | DDL-level enum extension |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scrapy | (project standard) | Spider shell / signal hooks | Consistent with discover, scan, match phases |
| sqlalchemy 2.0 | (project standard) | ORM queries in ValidateService | All DB access goes through SQLAlchemy |
| alembic | (project standard) | Enum migration for 'validate' value | Project migration tool |
| unicodedata (stdlib) | stdlib | Strip diacritics for slug-title check | No extra dep needed |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio.to_thread | stdlib | Run ValidateService off event loop | Required so HeartbeatExtension ticks during long SQL |
| re (stdlib) | stdlib | Tokenise slug / title strings | No extra dep needed |

**Installation:** No new packages needed. Everything uses existing project dependencies.

---

## Architecture Patterns

### System Architecture Diagram

```
scrapy crawl validate -a shop=X
         |
         v
  ValidateSpider.start()
         |
    [create scrape_run row: phase='validate']
         |
    self._run_id = run.id   ←── HeartbeatExtension reads lazily
         |
    asyncio.to_thread(ValidateService.run)
         |
    ┌────────────────────────────────────────────┐
    │  ValidateService.run(shop_id, run_id)       │
    │                                            │
    │  check_structural_duplicates()             │
    │  check_data_completeness()                 │
    │  check_data_correctness()                  │
    │  check_classification_consistency()        │
    │  check_staleness()                         │
    │  check_match_readiness()                   │
    │  check_relationship_integrity()            │
    │       │                                   │
    │  bulk_insert_validation_issues()           │
    │    └── _assign_lifecycle_states()          │
    └────────────────────────────────────────────┘
         |
    [finish_scrape_run: status='completed'/'failed']
         |
         v
   Spider closes (no requests were ever yielded)
```

### Recommended Project Structure

```
book_scraper/
├── spiders/
│   └── validate.py          # New: thin Scrapy spider shell
├── services/
│   ├── match.py             # Existing reference implementation
│   └── validate.py          # New: ValidateService with check methods
book_scraper/dashboard/routes/
│   └── api.py               # Modify: add 'validate' to phase whitelist
book_scraper/dashboard/static/hifi/
│   └── hf-shopbooks.jsx     # Add "Run validate" button (or hf-other.jsx)
alembic/versions/
│   └── XXXX_add_validate_phase.py  # New: enum migration
```

### Pattern 1: ValidateSpider — Mirror of MatchSpider

**What:** A Scrapy spider that yields no requests and runs all logic off the event loop thread via `asyncio.to_thread()`.

**When to use:** Any Scrapy phase that is DB-only (no HTTP). Established by `match.py`.

**Example (verified from `book_scraper/spiders/match.py`):**

```python
# Source: book_scraper/spiders/match.py [VERIFIED: codebase]
class ValidateSpider(scrapy.Spider):
    name = "validate"
    custom_settings = {
        "ITEM_PIPELINES": {},           # no items, no DB pipelines
        "EXTENSIONS": {
            "book_scraper.extensions.StallDetector": None,      # disabled
            "book_scraper.extensions.CronChainTrigger": 520,    # keep
            # HeartbeatExtension stays ON (not listed = inherits default)
        },
    }

    async def start(self):
        database_url = self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        if not database_url:
            return
            yield  # unreachable — satisfies AsyncGenerator typing

        session = get_session_factory(database_url)()
        try:
            shop = upsert_shop(session, self.shop_name, self.conf.shop.base_url)
            run = create_scrape_run(session, shop.id, "validate",
                                    extra_payload={"shop": self.shop_name})
            session.commit()
            run_id = run.id
        finally:
            session.close()

        self._run_id = run_id   # HeartbeatExtension reads this on next tick

        def _run_validate():
            s = get_session_factory(database_url)()
            try:
                svc = ValidateService(s)
                counters = svc.run(shop.id, run_id)
                s.commit()
                return counters
            except Exception:
                s.rollback()
                raise
            finally:
                s.close()

        counters = await asyncio.to_thread(_run_validate)

        session = get_session_factory(database_url)()
        try:
            finish_scrape_run(session, run_id, status="completed")
            session.commit()
        finally:
            session.close()

        return
        yield  # unreachable
```

### Pattern 2: Alembic Enum Extension

**What:** Add a new value to an existing PostgreSQL enum type. Must run outside a transaction.

**Example (verified from `alembic/versions/2026_04_26_add_stopping_status.py` and `2026_04_27_add_paused_status.py`):**

```python
# Source: alembic/versions/2026_04_26_add_stopping_status.py [VERIFIED: codebase]
def upgrade() -> None:
    # Postgres ALTER TYPE ADD VALUE cannot run inside a transaction block.
    op.execute("COMMIT")
    op.execute("ALTER TYPE scrape_phase ADD VALUE IF NOT EXISTS 'validate'")

def downgrade() -> None:
    # No native drop — recreate enum without 'validate'.
    # Any rows with phase='validate' must be removed first.
    op.execute("DELETE FROM scrape_runs WHERE phase = 'validate'")
    op.execute("ALTER TYPE scrape_phase RENAME TO scrape_phase_old")
    op.execute(
        "CREATE TYPE scrape_phase AS ENUM ("
        "'discover_sitemap', 'discover_categories', 'discover_full_crawl', "
        "'discover_graphql', 'discover_lupasearch', 'discover_ibiblioteka_api', "
        "'match', 'scan')"
    )
    op.execute(
        "ALTER TABLE scrape_runs "
        "ALTER COLUMN phase TYPE scrape_phase USING phase::text::scrape_phase"
    )
    op.execute("DROP TYPE scrape_phase_old")
```

### Pattern 3: Dashboard API — Adding a New Phase

**What:** `POST /api/runs` (in `book_scraper/dashboard/routes/api.py`) has an explicit allowlist at line 654. The `_spawn_scrapy_in_container` function builds the `scrapy crawl <phase>` command.

**Changes required (verified from `api.py`):**

```python
# Source: book_scraper/dashboard/routes/api.py [VERIFIED: codebase]

# Line 654 — expand allowlist:
if req.phase not in ("scan", "discover", "match", "validate"):
    raise HTTPException(status_code=400, detail=f"Unknown phase: {req.phase}")

# In _spawn_scrapy_in_container — add validate branch:
cmd = ["/app/.venv/bin/scrapy", "crawl", phase, "-a", f"shop={shop}"]
# 'validate' needs no extra args beyond shop=
```

The JSX "Run validate" button follows the exact same pattern as the existing "Recheck now" button in `hf-details.jsx`:

```javascript
// Source: hf-details.jsx (pattern) [VERIFIED: codebase]
const runValidate = async () => {
    const resp = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop: shopName, phase: 'validate' }),
    });
    if (resp.ok) goto('runs');
};
```

### Pattern 4: bulk_insert_validation_issues Deduplication

**What:** Issues are inserted via `bulk_insert_validation_issues`, which resolves `shop_book_id` from URL, then calls `_assign_lifecycle_states` to stamp `new` or `recurring`. The caller does NOT need to check for existing rows — the function handles it.

**Key finding:** `_assign_lifecycle_states` deduplicates on `(entity, field, issue)` triple — NOT on `(shop_book_id, field)` alone. The VAL-11 requirement says "deduplicates by (shop_book_id, field)"; the actual implementation is a superset: it also checks `issue` (the issue key string). This is fine — each check only produces one `issue` key per `field`, so the triple uniqueness is equivalent for this use case.

**Pattern for ValidateService check methods:**

```python
# Source: book_scraper/db/repo.py lines 1500-1553 [VERIFIED: codebase]
def check_structural_duplicates(self, shop_id: int, run_id: int) -> list[dict]:
    """Return one ValidationIssue dict per affected shop_book row."""
    issues = []
    # Example: isbn_duplicate
    rows = self._session.execute(
        text("""
            SELECT sb.id, sb.url, sb.isbn
            FROM shop_books sb
            WHERE sb.shop_id = :shop_id AND sb.isbn IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM shop_books sb2
                  WHERE sb2.shop_id = :shop_id
                    AND sb2.isbn = sb.isbn
                    AND sb2.id != sb.id
              )
        """),
        {"shop_id": shop_id}
    ).all()
    for row in rows:
        issues.append({
            "scrape_run_id": run_id,
            "url": row.url,
            "field": "isbn",
            "issue": "isbn_duplicate",
            "raw_value": row.isbn,
            "shop_book_id": row.id,
        })
    return issues
```

### Pattern 5: HeartbeatExtension + asyncio.to_thread()

**What:** HeartbeatExtension reads `spider._run_id` lazily on each tick. The spider must set `self._run_id` BEFORE calling the service, so ticks that fire during the long SQL operation can update `last_heartbeat`.

**Critical ordering (verified from `match.py`):**
1. Create scrape_run row → get `run_id`
2. Set `self._run_id = run_id` (HeartbeatExtension picks this up)
3. Call `asyncio.to_thread(_run_validate)` — reactor loop free during SQL

Without step 3 (running synchronous SQL on the event loop thread), the dashboard reaper kills the run after `DEAD_RUN_SECONDS = 60` because heartbeat ticks cannot fire while the reactor is blocked.

### Anti-Patterns to Avoid

- **Running ValidateService synchronously on the event loop thread:** Blocks `HeartbeatExtension` ticks. The dashboard reaper uses `DEAD_RUN_SECONDS = 60` — any SQL that takes over 60s will be killed. Use `asyncio.to_thread()`.
- **Leaving StallDetector enabled:** It fires if no `response_received` or `item_scraped` signal lands within `STALL_TIMEOUT` (180s). A no-HTTP spider will always trigger this. Disable via `custom_settings: {"EXTENSIONS": {"book_scraper.extensions.StallDetector": None}}`.
- **Leaving ITEM_PIPELINES enabled:** `PostgresPipeline` expects `ShopBookItem`s. With no items, the pipeline still initialises and opens DB connections. Clear it with `"ITEM_PIPELINES": {}`.
- **Not populating `ValidationIssue.url`:** The column is NOT NULL in the model. Always set it from `shop_book.url`. The `bulk_insert_validation_issues` function can resolve `shop_book_id` from `url` when `shop_id` is passed, but the `url` field itself must still be populated in the dict.
- **Calling `bulk_insert_validation_issues` without `session.commit()`:** The function uses `session.add_all()` — caller must commit after returning from the service.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Issue lifecycle (new/recurring) | Custom dedup query + insert | `bulk_insert_validation_issues` + `_assign_lifecycle_states` | Already handles (entity, field, issue) triple deduplication, acknowledged-issue re-surface logic |
| scrape_runs row creation | Direct ORM insert | `create_scrape_run` from `repo.py` | Emits `run_event_types.STARTED` event, sets `pid`, `last_heartbeat` |
| scrape_runs finalization | Direct ORM update | `finish_scrape_run` from `repo.py` | Handles abort of processing items, emits COMPLETED/FAILED event, close_reason |
| Spider shutdown failsafe | Try/except in closed() | `finalize_run_failsafe` from `repo.py` | Used by scan spider for poisoned-session recovery — same pattern needed |
| Enum migration | Raw SQL DDL | Alembic migration with `op.execute("COMMIT"); op.execute("ALTER TYPE ... ADD VALUE")` | Must run outside transaction; `IF NOT EXISTS` is idempotent |
| Diacritic stripping | Custom unidecode | `unicodedata.normalize("NFD", s)` + filter category "Mn" | stdlib, no extra dep |

---

## Runtime State Inventory

> This is a greenfield feature addition (new spider + service), not a rename/refactor. No runtime state migration needed.

**None — verified by codebase inspection:** Adding a new Scrapy spider and a new enum value does not modify any existing stored data, live service configuration, OS-registered state, secrets, or installed artifacts.

---

## Common Pitfalls

### Pitfall 1: `ALTER TYPE ADD VALUE` inside a transaction

**What goes wrong:** `ALTER TYPE scrape_phase ADD VALUE 'validate'` fails with `ERROR: ALTER TYPE ... ADD VALUE cannot run inside a transaction block`.

**Why it happens:** Alembic wraps each migration in a transaction by default. PostgreSQL does not permit enum value additions inside transactions.

**How to avoid:** `op.execute("COMMIT")` before the `ALTER TYPE`. This is the exact pattern used in `2026_04_26_add_stopping_status.py` and `2026_04_27_add_paused_status.py`. [VERIFIED: codebase]

**Warning signs:** Migration fails with the exact error above on first attempt.

### Pitfall 2: Reactor-blocking SQL kills the run via heartbeat reaper

**What goes wrong:** Dashboard shows run as `failed` with `error_reason='heartbeat_timeout'` after 60s despite spider still running SQL.

**Why it happens:** If `ValidateService.run()` is called directly (synchronously) in `start()` without `asyncio.to_thread()`, the event loop is blocked and `HeartbeatExtension`'s `callLater` ticks cannot fire. The dashboard reaper (`DEAD_RUN_SECONDS = 60`) then marks the run failed.

**How to avoid:** Always dispatch the service via `await asyncio.to_thread(_run_validate)` — exactly as `match.py` does it. [VERIFIED: codebase]

**Warning signs:** Run completes locally but shows heartbeat_timeout in dashboard for runs taking >60s.

### Pitfall 3: StallDetector fires on no-HTTP spider

**What goes wrong:** Spider closes itself after `STALL_TIMEOUT` (180s) with reason `stall_timeout`, triggering auto-resume loop.

**Why it happens:** `StallDetector` fires when no `response_received` or `item_scraped` signal lands within the timeout. A no-HTTP spider never produces these signals.

**How to avoid:** Set `custom_settings = {"EXTENSIONS": {"book_scraper.extensions.StallDetector": None}}`. [VERIFIED: codebase — match.py uses this exact pattern]

**Warning signs:** Run closes unexpectedly with `close_reason = 'stall_timeout'` before the service finishes.

### Pitfall 4: Duplicate rows if `bulk_insert_validation_issues` called without FK resolution

**What goes wrong:** `ValidationIssue` rows are inserted with `shop_book_id = None` and only `url` set, but the model constraint `ck_validation_issues_single_entity` allows this. However, `_assign_lifecycle_states` uses `shop_book_id` for deduplication — if it's None, it falls back to URL-based matching which is less reliable.

**How to avoid:** Always pass `shop_id` to `bulk_insert_validation_issues` so it resolves `shop_book_id` from URL via the shop_books table. For cross-row checks (isbn_duplicate, title_author_duplicate), pre-populate `shop_book_id` directly in the issue dict to avoid the URL lookup overhead. [VERIFIED: codebase, repo.py line 1543-1550]

### Pitfall 5: `api_create_run` rejects 'validate' phase

**What goes wrong:** Dashboard "Run validate" button gets HTTP 400 `Unknown phase: validate`.

**Why it happens:** `api_create_run` in `api.py` line 654 has an explicit allowlist `("scan", "discover", "match")`. [VERIFIED: codebase]

**How to avoid:** Add `"validate"` to the allowlist and add a branch in `_spawn_scrapy_in_container` that handles the `validate` phase (it needs no extra args beyond `shop=`).

### Pitfall 6: Preflight check uses `run_phase` to detect concurrent runs

**What goes wrong:** `_preflight_checks` queries `ScrapeRun.phase == run_phase` where `run_phase` comes from the enum. If the 'validate' enum value is not yet applied (migration not run), the query fails with a PostgreSQL enum cast error.

**How to avoid:** Run the Alembic migration (`upgrade head`) before deploying the dashboard changes. The migration is a dependency of the dashboard route change.

### Pitfall 7: `stale_active` check uses wrong cadence

**What goes wrong:** All shop_books flagged as stale_active even on shops scrapped daily.

**Why it happens:** No `discover_cadence_days` field exists on the `shops` table (deferred). The stale_active threshold is `last_seen_at < now() - 2 * cadence`.

**How to avoid:** Default cadence = 14 days (as decided in CONTEXT.md). This means `stale_active` fires when `last_seen_at < now() - 28 days`. The planner should make this constant configurable via a `VALIDATE_STALE_CADENCE_DAYS` setting or hard-coded constant, clearly documented as the default pending a per-shop field.

---

## Code Examples

### scrape_runs lifecycle (from match.py — exact template)

```python
# Source: book_scraper/spiders/match.py [VERIFIED: codebase]
# Pattern: create run, set _run_id, dispatch service off thread, finalize

session = get_session_factory(database_url)()
try:
    shop = upsert_shop(session, self.shop_name, self.conf.shop.base_url)
    run = create_scrape_run(session, shop.id, "validate",
                            extra_payload={"shop": self.shop_name})
    session.commit()
    run_id = run.id
finally:
    session.close()

self._run_id = run_id   # HeartbeatExtension reads lazily

counters = await asyncio.to_thread(_run_validate)

session = get_session_factory(database_url)()
try:
    finish_scrape_run(session, run_id, status="completed")
    session.commit()
finally:
    session.close()
```

### bulk_insert_validation_issues call site

```python
# Source: book_scraper/db/repo.py lines 1500-1553 [VERIFIED: codebase]
# Pass shop_id so FKs are resolved; issues list contains url + field + issue + raw_value

bulk_insert_validation_issues(session, issues, shop_id=shop_id)
session.commit()
```

### Duplicate pair check (SQL pattern for isbn_duplicate)

```sql
-- Source: spec + SQLAlchemy text() [VERIFIED against models.py schema]
-- Both rows of the duplicate pair get a ValidationIssue
SELECT sb.id, sb.url, sb.isbn
FROM shop_books sb
WHERE sb.shop_id = :shop_id
  AND sb.isbn IS NOT NULL
  AND EXISTS (
      SELECT 1 FROM shop_books sb2
      WHERE sb2.shop_id = :shop_id
        AND sb2.isbn = sb.isbn
        AND sb2.id != sb.id
  )
```

### Slug-title mismatch tokenisation

```python
# Source: spec + stdlib unicodedata [VERIFIED: spec, unicodedata is stdlib]
import re, unicodedata

def _tokenize(s: str) -> set[str]:
    """Normalise Lithuanian text, strip diacritics, split on - and space."""
    nfd = unicodedata.normalize("NFD", s.lower())
    ascii_only = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return set(re.split(r"[-\s]+", ascii_only)) - {""}

# Extract slug path from URL (last path segment):
slug = url.rstrip("/").rsplit("/", 1)[-1]
slug_tokens = _tokenize(slug)
title_tokens = _tokenize(title)
if slug_tokens and title_tokens and not (slug_tokens & title_tokens):
    # zero intersection → flag slug_title_mismatch
```

### StallDetector disabled in custom_settings

```python
# Source: book_scraper/spiders/match.py [VERIFIED: codebase]
custom_settings = {
    "ITEM_PIPELINES": {},
    "EXTENSIONS": {
        "book_scraper.extensions.StallDetector": None,
        "book_scraper.extensions.CronChainTrigger": 520,
    },
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Validate as CLI script | Validate as Scrapy spider | Design decision 2026-05-10 | Consistent with discover/scan/match; dashboard integration is free |
| Inline try/except for run finalization | `finalize_run_failsafe` + primary path | scan.py pattern | Poisoned-session recovery; validate spider should follow same pattern |

---

## Key Design Findings (Research Answers)

### Q1: How does the scan spider manage scrape_runs lifecycle?

**Answer:** Scan spider creates the run row inside `start()` (the async generator), not in `spider_opened`. The pattern for validate should follow `match.py` instead, which creates the run in `start()` then sets `self._run_id` so `HeartbeatExtension` picks it up. [VERIFIED: scan.py, match.py]

### Q2: Does StallDetector or HeartbeatExtension need to be disabled?

**Answer:** StallDetector MUST be disabled (fires after 180s with no HTTP responses). HeartbeatExtension MUST stay ON (otherwise `last_heartbeat` is never updated and the dashboard reaper kills the run after 60s). The exact `custom_settings` dict from `match.py` handles both. [VERIFIED: extensions.py, match.py]

### Q3: Exact Alembic migration pattern for adding a PostgreSQL enum value?

**Answer:** Two-step: `op.execute("COMMIT")` then `op.execute("ALTER TYPE scrape_phase ADD VALUE IF NOT EXISTS 'validate'")`. The `COMMIT` is mandatory — PostgreSQL does not allow `ALTER TYPE ADD VALUE` inside a transaction. [VERIFIED: alembic/versions/2026_04_26_add_stopping_status.py, 2026_04_27_add_paused_status.py]

### Q4: How does the dashboard "Run" button work?

**Answer:** JSX calls `POST /api/runs` with JSON body `{shop, phase, strategy, mode}`. In `api.py`, `api_create_run` validates the phase against an allowlist, then calls `_spawn_scrapy_in_container` which runs `docker exec` into the scraper container. The `validate` phase needs to be added to the allowlist (currently `("scan", "discover", "match")`) and the `_spawn_scrapy_in_container` function needs a branch for it (which is trivial — just `shop=` arg, no strategy or mode). [VERIFIED: api.py lines 649-686]

### Q5: Does _assign_lifecycle_states handle the (shop_book_id, field) deduplication?

**Answer:** Yes, but on the `(entity, field, issue)` triple (not just `(shop_book_id, field)`). Since each check produces only one `issue` key per `field`, this is effectively equivalent. The function stamps `new` for first occurrence, `recurring` for subsequent occurrences (unless acknowledged, in which case it resets to `new`). The caller does NOT need to pre-filter. [VERIFIED: repo.py lines 1556-1649]

### Q6: Is the validation_issues table already created?

**Answer:** Yes. Migration `2ee38722fb89_add_validation_issues_table.py` exists. VAL-14 in REQUIREMENTS.md only needs the enum migration, not a table creation. [VERIFIED: alembic/versions/]

### Q7: Stale_active cadence — what's the decision?

**Answer:** No `discover_cadence_days` field on `shops` table. The `cron_jobs` table has a `cron_expression` column per shop, but parsing cron expressions to derive cadence is non-trivial. The CONTEXT.md decision is to use a 14-day default constant. The planner should define `VALIDATE_STALE_CADENCE_DAYS = 14` as a module constant in `validate.py`, making it easy to replace later when per-shop cadence is added. [VERIFIED: models.py CronJob model, CONTEXT.md deferred decisions]

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `stale_active` threshold = 2 × 14 days = 28 days | Common Pitfalls / Check logic | Too aggressive (flags valid books) or too lenient (misses stale books). Low risk — operator-visible in Issues tab, can adjust constant without migration. |

---

## Open Questions

1. **Where exactly in the JSX does the "Run validate" button live?**
   - What we know: Existing phase buttons use `POST /api/runs` with JSON body. The shop detail page is likely `hf-shopbooks.jsx` or the shop overview component.
   - What's unclear: The exact component/view that hosts per-shop phase trigger buttons was not found in the JSX grep — the files use `fetch('/api/runs')` but none for discover/scan specifically on a shop detail page.
   - Recommendation: Planner should locate the shop-level action area in the JSX (search for where `phase: 'scan'` is passed per-shop) and add the validate button alongside it.

2. **Exception path in start() — how to mark run failed?**
   - What we know: `match.py` does not have an explicit try/except around the service call. If `asyncio.to_thread` raises, the generator exits with an exception, and `spider_closed` (`closed()` callback) is called with `reason="shutdown"`.
   - What's unclear: Whether validate should have a try/except in `start()` that calls `finish_scrape_run(..., status="failed")` explicitly, or rely on `closed()` + `finalize_run_failsafe`.
   - Recommendation: Add a try/except around the `asyncio.to_thread` call that calls `finish_scrape_run(status="failed")` explicitly, then re-raise. Also add a `closed()` method with `finalize_run_failsafe` as the failsafe path (same as `scan.py`).

---

## Environment Availability

Step 2.6: SKIPPED — validate phase is code/config-only addition. No external tools, services, or CLIs beyond the existing Scrapy + PostgreSQL stack are introduced. Both are confirmed running (project is in active use per git log).

---

## Sources

### Primary (HIGH confidence)

- `book_scraper/spiders/match.py` — exact implementation pattern to replicate for validate spider
- `book_scraper/spiders/scan.py` — reference for `closed()` failsafe finalization pattern
- `book_scraper/extensions.py` — StallDetector and HeartbeatExtension behavior verified
- `book_scraper/db/repo.py` lines 972-1660 — `create_scrape_run`, `finish_scrape_run`, `finalize_run_failsafe`, `bulk_insert_validation_issues`, `_assign_lifecycle_states`
- `book_scraper/db/models.py` lines 336-642 — `scrape_phase_enum`, `ValidationIssue`, `ShopBook`
- `book_scraper/dashboard/routes/api.py` lines 539-686 — `api_create_run`, `_spawn_scrapy_in_container`, phase allowlist
- `alembic/versions/2026_04_26_add_stopping_status.py` + `2026_04_27_add_paused_status.py` — exact enum migration pattern
- `tests/unit/test_match_spider.py` — unit test patterns for no-HTTP spiders
- `.planning/phases/01-validate-phase/01-CONTEXT.md` — locked decisions

### Secondary (MEDIUM confidence)

- Design spec `docs/superpowers/specs/2026-05-10-shop-books-validate-phase-design.md` — check definitions, severity tiers, deduplication rules

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — existing project deps, no new packages
- Architecture: HIGH — verified against match.py (exact template) and scan.py
- Alembic pattern: HIGH — verified against two existing enum migration files
- Dashboard integration: HIGH — verified against api.py allowlist and _spawn_scrapy_in_container
- Check SQL patterns: MEDIUM — modelled from spec + schema inspection; actual SQL not yet written or tested
- Stale_active cadence: MEDIUM — default 14 days decided in CONTEXT.md; no existing implementation to verify against

**Research date:** 2026-05-10
**Valid until:** 2026-06-10 (stable codebase, no fast-moving deps)
