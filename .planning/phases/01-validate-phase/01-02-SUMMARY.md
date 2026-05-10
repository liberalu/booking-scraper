---
phase: 01-validate-phase
plan: 02
subsystem: api
tags: [scrapy, sqlalchemy, postgres, validate, spider, service]

# Dependency graph
requires:
  - phase: 01-validate-phase/01-01
    provides: Alembic migration adding 'validate' to scrape_phase enum + validation_issues table confirmed present
provides:
  - ValidateSpider (scrapy crawl validate -a shop=X entrypoint, no HTTP, asyncio.to_thread dispatch)
  - ValidateService with structural duplicate checks (isbn/title_author/sku) and slug_title_mismatch check
  - _tokenize and _should_flag_slug_title module-level helpers for plan 03 to reuse
  - VALIDATE_STALE_CADENCE_DAYS = 14 constant for plan 03 staleness checks
affects:
  - 01-validate-phase/01-03  # adds check_* methods to ValidateService
  - 01-validate-phase/01-04  # dashboard integration, api_create_run whitelist

# Tech tracking
tech-stack:
  added: []
  patterns:
    - asyncio.to_thread dispatch pattern (mirrors match.py) for no-HTTP Scrapy spiders
    - closed() failsafe using finalize_run_failsafe(database_url, ...) — scan.py pattern
    - _tokenize: NFD decomposition + Mn category filter for Lithuanian diacritic stripping

key-files:
  created:
    - book_scraper/services/validate.py
    - book_scraper/spiders/validate.py
    - tests/unit/test_validate_service_structural.py
    - tests/unit/test_validate_spider.py
  modified: []

key-decisions:
  - "closed() uses finalize_run_failsafe(database_url, ...) matching scan.py — idempotent, safe to call after successful finish_scrape_run"
  - "ValidateService.run() returns plain dict[str, int] counters (not a dataclass like MatchCounters) — no items_updated propagation needed"
  - "check_structural_duplicates uses EXISTS sub-selects so both rows of each pair receive a ValidationIssue"

patterns-established:
  - "No-HTTP spider pattern: ITEM_PIPELINES={}, StallDetector=None, HeartbeatExtension ON, asyncio.to_thread dispatch"
  - "_run_id assigned BEFORE to_thread dispatch (heartbeat-ordering invariant)"

requirements-completed: [VAL-01, VAL-02, VAL-03, VAL-04, VAL-11]

# Metrics
duration: 15min
completed: 2026-05-10
---

# Phase 1 Plan 02: Validate Phase Spider + Service Skeleton Summary

**ValidateSpider + ValidateService skeleton with structural duplicate checks (isbn/title_author/sku) and slug-title mismatch detection via zero-token-overlap with Lithuanian diacritic stripping**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-05-10T13:40:00Z
- **Completed:** 2026-05-10T13:44:35Z
- **Tasks:** 2
- **Files modified:** 4 (2 production, 2 test)

## Accomplishments

- ValidateService class with check_structural_duplicates + check_slug_title_mismatch, using bulk_insert_validation_issues for lifecycle deduplication
- ValidateSpider mirroring match.py: asyncio.to_thread dispatch, self._run_id ordering invariant, closed() failsafe
- 14 unit tests (9 service structural, 5 spider invariant) — all passing, ruff + mypy clean

## Task Commits

1. **Task 1: ValidateService skeleton with structural + slug-title checks** - `755c124` (feat, TDD)
2. **Task 2: ValidateSpider mirroring match.py + spider invariant tests** - `6f9fe3a` (feat, TDD)

**Plan metadata:** (this commit)

_Note: Both tasks followed TDD — tests written first (RED: import error), implementation second (GREEN: all pass)_

## Files Created/Modified

- `book_scraper/services/validate.py` — ValidateService class, _tokenize, _should_flag_slug_title, VALIDATE_STALE_CADENCE_DAYS = 14
- `book_scraper/spiders/validate.py` — ValidateSpider: no HTTP, StallDetector disabled, asyncio.to_thread, closed() failsafe
- `tests/unit/test_validate_service_structural.py` — 9 pure unit tests for tokenisation and constant
- `tests/unit/test_validate_spider.py` — 5 spider invariant tests (run_id ordering, off-thread, success path, args, ValueError)

## Decisions Made

- `closed()` uses `finalize_run_failsafe(database_url, ...)` (takes a URL string, not a session) — the plan's action code was wrong; fixed per Rule 1
- ValidateService returns `dict[str, int]` not a dataclass; no `items_updated` propagation (nothing to propagate for a validation run)
- Both rows of each duplicate pair get a ValidationIssue — implemented via EXISTS sub-selects in check_structural_duplicates

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed closed() signature: finalize_run_failsafe takes database_url string, not a session**
- **Found during:** Task 2 (ValidateSpider implementation)
- **Issue:** The plan's `<action>` block showed `closed()` opening a session and passing it to `finalize_run_failsafe()`. The actual function signature is `finalize_run_failsafe(database_url: str, run_id: int, status: str, reason: str)` — it creates its own session internally (verified in repo.py L1048).
- **Fix:** `closed()` passes `database_url` string (from `self.settings.get("DATABASE_URL")`) directly, matching scan.py's usage pattern.
- **Files modified:** `book_scraper/spiders/validate.py`
- **Verification:** mypy exits 0, tests pass
- **Committed in:** 6f9fe3a (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Essential correctness fix. No scope creep.

## Issues Encountered

None beyond the deviation above.

## Known Stubs

None — all check methods execute real SQL and write real ValidationIssue rows. No hardcoded empty values.

## Next Phase Readiness

- Plan 03 can add check_completeness, check_correctness, check_classification, check_staleness, check_match_readiness, check_relationship_integrity methods directly to ValidateService — no spider changes needed
- The four public extension points are ready: `run()`, `check_structural_duplicates()`, `check_slug_title_mismatch()`, `VALIDATE_STALE_CADENCE_DAYS`
- Integration tests (real DB) deferred to plan 03 as planned

---
*Phase: 01-validate-phase*
*Completed: 2026-05-10*
