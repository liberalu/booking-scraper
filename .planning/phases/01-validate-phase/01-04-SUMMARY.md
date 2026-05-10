---
phase: 01-validate-phase
plan: 04
subsystem: dashboard
tags: [dashboard, fastapi, jsx, validate, api]

# Dependency graph
requires:
  - phase: 01-validate-phase/01-01
    provides: Alembic migration adding 'validate' to scrape_phase enum
  - phase: 01-validate-phase/01-02
    provides: ValidateSpider entrypoint (scrapy crawl validate -a shop=X)
provides:
  - POST /api/runs accepts phase='validate', rejects invalid phases, blocks concurrent validate runs
  - HFNewRunDialog shows Validate as a third phase option alongside Scan and Discover
  - Integration smoke tests: happy path, unknown phase rejection, concurrent run rejection
affects:
  - Dashboard New Run modal UI
  - api_create_run endpoint phase allowlist

# Tech tracking
tech-stack:
  added: []
  patterns:
    - validate phase has no strategy/mode args — _spawn_scrapy_in_container existing branching already handles this

key-files:
  created: []
  modified:
    - book_scraper/dashboard/routes/api.py
    - book_scraper/dashboard/static/hifi/hf-overlays.jsx
    - book_scraper/db/models.py
    - tests/integration/test_dashboard_routes.py

key-decisions:
  - "_spawn_scrapy_in_container required no edits — existing discover/scan branches skip for validate, producing scrapy crawl validate -a shop=<shop> exactly"
  - "scrape_phase_enum in models.py updated to include 'validate' so Base.metadata.create_all (used by test conftest) creates the enum correctly"

patterns-established: []

requirements-completed: [VAL-12]

# Metrics
duration: 15min
completed: 2026-05-10
---

# Phase 1 Plan 04: Dashboard Integration Summary

**Validate phase wired into the dashboard: POST /api/runs accepts phase='validate', New Run modal exposes Validate as a segmented control option alongside Scan and Discover**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-05-10
- **Completed:** 2026-05-10
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- api_create_run allowlist extended from ("scan", "discover", "match") to ("scan", "discover", "match", "validate")
- HFNewRunDialog segmented control gains a third option: `{ value:'validate', label:'Validate (DB checks)' }`
- Phase hint updated: validate shows 'Run DB-only data quality checks (no HTTP)'
- Mode and Strategy pickers remain hidden for validate — no code change needed, the existing `phase === 'scan'` and `phase === 'discover'` conditionals auto-handle this
- `_spawn_scrapy_in_container` was NOT modified — verified that the existing logic produces the correct command (`scrapy crawl validate -a shop=<shop>`) since neither the discover-strategy branch nor the scan-mode branch fires for validate
- Three new integration tests added (all passing): `test_api_create_run_accepts_validate_phase`, `test_api_create_run_rejects_unknown_phase`, `test_api_create_run_rejects_concurrent_validate`
- Live dashboard container confirmed serving updated JSX (`curl http://localhost:8000/static/hifi/hf-overlays.jsx | grep -c "value:'validate'" == 1`)

## Task Commits

1. **Task 1: Add 'validate' to API allowlist + smoke tests** - `fdd6415`
2. **Task 2: Add 'Validate' option to New Run modal segmented control** - `e7529e4`

## Files Created/Modified

- `book_scraper/dashboard/routes/api.py` — phase allowlist extended to include 'validate'
- `book_scraper/dashboard/static/hifi/hf-overlays.jsx` — Validate option in HFNewRunDialog only (HFNewScheduleDialog unchanged)
- `book_scraper/db/models.py` — scrape_phase_enum updated with 'validate' so test conftest create_all includes it
- `tests/integration/test_dashboard_routes.py` — three new integration tests for validate phase path

## Decisions Made

- `_spawn_scrapy_in_container` required no edits: existing logic already correct for validate
- `scrape_phase_enum` in models.py updated with 'validate' to fix test DB create_all (Rule 2: missing correctness)
- Submit body in HFNewRunDialog required no change: `strategy` will be '' for validate, `mode` is ignored backend-side

## Operator Note

After deploying, to manually exercise the full path:
1. Open `http://localhost:8000`
2. Click `New run`
3. Select `Validate (DB checks)` in the Phase picker
4. Confirm Mode and Strategy pickers are hidden
5. Select shop=vaga, click `Start run`
6. The validate run will appear in the Runs list; any findings land in the Issues tab under the validate run_id

If the run fails, the failure mode appears in `scrape_runs.close_reason` and as a `scrape_run_failed` issue in `validation_issues`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Added 'validate' to scrape_phase_enum in models.py**
- **Found during:** Task 1 verification (test run)
- **Issue:** `Base.metadata.create_all(engine)` used by `tests/conftest.py` creates the `scrape_phase` PostgreSQL enum from the `scrape_phase_enum` definition in models.py. Since the plan's Alembic migration (plan 01) added 'validate' to the DB enum but the models.py definition was not updated, fresh test DB sessions created the enum without 'validate', causing `InvalidTextRepresentation` errors on both query and insert.
- **Fix:** Added `"validate"` to `scrape_phase_enum` values in `book_scraper/db/models.py`
- **Files modified:** `book_scraper/db/models.py`
- **Commit:** fdd6415

---

**Total deviations:** 1 auto-fixed (Rule 2)
**Impact on plan:** Essential correctness fix. Test suite would not pass without it.

## Known Stubs

None — all changes connect real endpoints to real spider invocations.

## Self-Check

- [x] `grep -c '"scan", "discover", "match", "validate"' book_scraper/dashboard/routes/api.py` == 1
- [x] `grep -c "value:'validate'" book_scraper/dashboard/static/hifi/hf-overlays.jsx` == 1
- [x] `grep -c "Validate (DB checks)" book_scraper/dashboard/static/hifi/hf-overlays.jsx` == 1
- [x] `grep -c "test_api_create_run_accepts_validate_phase" tests/integration/test_dashboard_routes.py` == 1
- [x] `grep -c "test_api_create_run_rejects_unknown_phase" tests/integration/test_dashboard_routes.py` == 1
- [x] `grep -c "test_api_create_run_rejects_concurrent_validate" tests/integration/test_dashboard_routes.py` == 1
- [x] All 59 integration tests pass
- [x] mypy exits 0 on api.py and models.py
- [x] ruff exits 0 on all modified files
- [x] curl live container returns 1 for `value:'validate'`
- [x] fdd6415 exists in git log
- [x] e7529e4 exists in git log

## Self-Check: PASSED
