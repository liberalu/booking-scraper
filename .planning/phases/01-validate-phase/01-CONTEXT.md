# Phase 1: Validate Phase - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a fourth pipeline phase (`validate`) that runs DB-only checks over `shop_books` rows and writes `validation_issues` findings. No HTTP requests. No auto-fix. No new tables needed. The phase gets its own `scrape_runs` row and a "Run validate" dashboard button on the shop detail page.

Spec fully defined in `docs/superpowers/specs/2026-05-10-shop-books-validate-phase-design.md` — all 5 check groups (structural, completeness, correctness, classification, staleness) and severity tiers are locked.

</domain>

<decisions>
## Implementation Decisions

### Entrypoint

- **D-01:** Use a Scrapy spider — `scrapy crawl validate -a shop=X` — consistent with `discover` and `scan`. No separate CLI entrypoint needed.
- **D-02:** The validate spider yields **no items** and makes **no HTTP requests**. `PostgresPipeline` is not involved. The spider manages its own `scrape_runs` row: create in `spider_opened`, mark complete/failed in `spider_closed`.
- **D-03:** The spider calls `ValidateService` synchronously in `spider_opened` (before the asyncio reactor processes any requests). Since no requests are ever yielded, the spider's `close()` fires immediately after `spider_opened` returns. This is the simplest approach and avoids any stall-detection interaction.

### Claude's Discretion

- **Stall detection:** Run validate logic synchronously inside `spider_opened` so the reactor never gets a chance to trigger stall timers. Alternatively, add `STALL_TIMEOUT = 0` or disable `StallDetector` in the spider's `custom_settings`. Planner picks whichever integrates most cleanly.
- **scrape_runs lifecycle:** `spider_opened` creates the `scrape_runs` row directly (not via pipeline). `spider_closed` marks it `completed` or `failed` depending on whether an exception was raised. Heartbeat extension may need to be disabled — planner should check extension compatibility with a no-request spider.

### Unresolved (spec open questions — planner resolves)

- **stale_active cadence:** How to obtain per-shop discover frequency. Spec says "either read from the cron schedule or add a `discover_cadence_days` field to `shops`." Planner should pick the simpler path; if the TOML cron schedule is parseable, use it; otherwise default to 14 days until a shops column is added.
- **title_author_duplicate threshold:** Flag on `title + author` match only (more sensitive, more false positives) or require `title + author + year` (more precise). Default to `title + author` only for now, consistent with spec's original intent.
- **Auto-trigger after scan:** Deferred to v2. Validate is on-demand only for this phase (dashboard button).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Spec (primary)
- `docs/superpowers/specs/2026-05-10-shop-books-validate-phase-design.md` — Full check definitions, severity tiers, deduplication rules, output schema. All check logic must match this doc exactly.

### Existing DB Schema
- `book_scraper/db/models.py` — `ValidationIssue` model (lines ~602–641), `scrape_phase_enum` (lines ~336–347), `ScrapeRun` model. Note: `ValidationIssue.url` is NOT NULL — populate from `shop_book.url`.
- `book_scraper/db/repo.py` — `bulk_insert_validation_issues` (line ~1500) + `_assign_lifecycle_states` for lifecycle management. Consider whether to reuse or call lower-level insert.

### Existing Spider Patterns (reference for scrape_runs lifecycle)
- `book_scraper/spiders/scan.py` — How scan spider manages the scrape_runs row in spider_opened/spider_closed.

### Dashboard (for button integration)
- `book_scraper/dashboard/app.py` — Existing phase trigger buttons on shop detail page.
- `book_scraper/dashboard/queries.py` — Queries surfacing validation_issues in the Issues tab.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ValidationIssue` SQLAlchemy model (`book_scraper/db/models.py`) — fully defined, no schema changes needed beyond populating `url` from `shop_book.url`
- `bulk_insert_validation_issues` + `_assign_lifecycle_states` (`book_scraper/db/repo.py`) — handles lifecycle transitions (new → already_seen) for deduplication
- `scrape_phase_enum` — needs `'validate'` added via Alembic migration (currently: discover_*, match, scan)
- `ScrapeRun` model — already has `phase` field; validate spider creates row with `phase='validate'`

### Established Patterns
- Spider-per-phase with `-a shop=X` argument: discover and scan follow this pattern; validate mirrors it
- `spider_opened` / `spider_closed` hooks manage `scrape_runs` row lifecycle in scan spider — validate does the same
- ValidateService should live in `book_scraper/services/validate.py` (new file, analogous to no existing service layer but mirrors `ValidateService` name from spec)
- Shop-specific parsers are NOT needed (validate is shop-agnostic — same SQL checks apply to all shops)
- `custom_settings` dict on the spider class overrides Scrapy settings per-spider

### Integration Points
- `scrape_phase_enum` in `book_scraper/db/models.py`: add `'validate'` value via Alembic migration
- Dashboard shop detail page: add "Run validate" button alongside existing discover/scan buttons
- `book_scraper/dashboard/queries.py`: ValidationIssue queries already exist for Issues tab — no changes expected
- Tests: add to `tests/unit/` (ValidateService logic) and `tests/integration/` (full pipeline with real DB)

</code_context>

<specifics>
## Specific Ideas

- The validate spider is the first Scrapy spider with no HTTP requests and no items pipeline. It's essentially a "DB job runner" wearing a spider shell. Keep it thin — all logic in `ValidateService`.
- Each check group is a method on `ValidateService`: `check_structural_duplicates`, `check_data_completeness`, `check_data_correctness`, `check_classification_consistency`, `check_staleness`, `check_match_readiness`, `check_relationship_integrity`.
- For `isbn_duplicate` / `title_author_duplicate`: both rows of the pair get a `validation_issue` row (spec requirement).
- `slug_title_mismatch`: tokenize by splitting on `-` and ` `, strip diacritics, lowercase, compare token intersection. Flag only when intersection is empty (0 common tokens).
- Deduplication: check deduplicates by `(shop_book_id, field)` at insert time — use `_assign_lifecycle_states` which transitions existing issues to `already_seen` rather than inserting duplicates.

</specifics>

<deferred>
## Deferred Ideas

- **Auto-trigger after scan** — The spec's open question about auto-triggering validate after each scan. Deferred to v2; keep validate on-demand only for this phase.
- **Per-shop discover cadence DB field** — `shops.discover_cadence_days` for `stale_active` check precision. Deferred; use TOML cron schedule or a 14-day default for this phase.
- **Validate in cron schedule** — Wiring validate into the existing docker-compose cron. Out of scope for this phase.

</deferred>

---

*Phase: 1-Validate Phase*
*Context gathered: 2026-05-10*
