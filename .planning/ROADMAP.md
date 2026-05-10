# Roadmap: Lithuanian Book Price Scraper

**Milestone:** v1.1 — Validate Phase
**Created:** 2026-05-10
**Status:** Phase 1 pending

---

## Phases

### Phase 1: Validate Phase

**Goal:** Add a fourth pipeline phase that runs DB-only checks over shop_books rows, writes validation_issues, and surfaces findings in the dashboard — closing the gap where silent data quality failures went undetected until manual postmortem.

**Requirements:** VAL-01, VAL-02, VAL-03, VAL-04, VAL-05, VAL-06, VAL-07, VAL-08, VAL-09, VAL-10, VAL-11, VAL-12, VAL-13, VAL-14

**Plans:** 4 plans

Plans:
**Wave 1**
- [x] 01-01-PLAN.md — Alembic migration: add 'validate' to scrape_phase enum (VAL-13, VAL-14)

**Wave 2** *(blocked on Wave 1 completion)*
- [ ] 01-02-PLAN.md — ValidateService skeleton (structural duplicates + slug-title) and ValidateSpider mirroring match.py (VAL-01, VAL-02, VAL-03, VAL-04, VAL-11)

**Wave 3** *(blocked on Wave 2 completion)*
- [ ] 01-03-PLAN.md — Extend ValidateService with completeness, correctness, classification, staleness, match-readiness, relationship integrity checks + integration tests (VAL-05, VAL-06, VAL-07, VAL-08, VAL-09, VAL-10, VAL-11)
- [ ] 01-04-PLAN.md — Dashboard integration: API allowlist + New Run modal validate option (VAL-12)

**Success Criteria:**
1. `scrapy crawl validate -a shop=vaga` runs without HTTP requests, creates a scrape_runs row with phase='validate', and writes validation_issues rows for any detected issues
2. Re-running validate on the same data does not create duplicate validation_issues rows (deduplication by shop_book_id + field)
3. Dashboard shop detail page shows a "Run validate" button alongside existing phase buttons
4. All 5 check groups (structural, completeness, correctness, classification, staleness) produce correct findings on synthetic test data
5. `uv run pytest tests/` passes with new validate tests

**Canonical refs:**
- `docs/superpowers/specs/2026-05-10-shop-books-validate-phase-design.md`

---

## Backlog

- Match phase — link shop_books to canonical books table (separate milestone)
- Auto-trigger validate after scan — cron integration (v2)
- Per-shop discover cadence field for stale_active threshold (v2)
