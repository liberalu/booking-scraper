# Requirements: Lithuanian Book Price Scraper

**Defined:** 2026-05-10
**Core Value:** Accurate, up-to-date book pricing and metadata across all three shops, surfaced through a dashboard that exposes data quality issues before they become hard-to-diagnose problems.

## v1 Requirements

### Validate Phase

- [x] **VAL-01**: Validate phase runs DB-only checks over shop_books rows and writes validation_issues per shop
- [x] **VAL-02**: Validate phase gets its own scrape_runs row (phase='validate') so it appears in dashboard run history
- [x] **VAL-03**: Structural duplicate checks: isbn_duplicate, title_author_duplicate, sku_duplicate
- [x] **VAL-04**: Slug-title mismatch check using zero-token-overlap threshold
- [ ] **VAL-05**: Data completeness checks: active_no_price, in_stock_no_price, book_no_metadata, no_price_history
- [ ] **VAL-06**: Data correctness checks: year_out_of_range, price_zero, format_is_dimensions
- [ ] **VAL-07**: Classification consistency checks: book_no_signals, non_book_has_isbn, non_product_active
- [ ] **VAL-08**: Staleness/lifecycle checks: stale_active, unreachable_active, orphan_no_url
- [ ] **VAL-09**: Match phase readiness checks: unmatched_has_isbn, match_isbn_drift
- [ ] **VAL-10**: Relationship integrity checks: url_aliases, product_url_non_book
- [x] **VAL-11**: Each check deduplicates by (shop_book_id, field) to avoid duplicate rows on re-run
- [ ] **VAL-12**: Operator can trigger validate run from dashboard shop detail page
- [x] **VAL-13**: scrape_phase enum extended with 'validate' value
- [x] **VAL-14**: Alembic migration adds validation_issues table (if not already exists)

## v2 Requirements

### Validate Phase Automation

- **VAL-AUTO-01**: Validate triggered automatically after each scan completes (cron integration)
- **VAL-AUTO-02**: Per-shop discover cadence field in shops table for stale_active threshold
- **VAL-AUTO-03**: Validate results surfaced in email/Slack alerts for critical issues

## Out of Scope

| Feature | Reason |
|---------|--------|
| Auto-fix of validation issues | Validate only flags; operator decides remediation — by design |
| Match phase implementation | Separate future milestone |
| Cross-shop duplicate detection | Different shops may legitimately carry same books |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| VAL-01 | Phase 1 | Complete |
| VAL-02 | Phase 1 | Complete |
| VAL-03 | Phase 1 | Complete |
| VAL-04 | Phase 1 | Complete |
| VAL-05 | Phase 1 | Pending |
| VAL-06 | Phase 1 | Pending |
| VAL-07 | Phase 1 | Pending |
| VAL-08 | Phase 1 | Pending |
| VAL-09 | Phase 1 | Pending |
| VAL-10 | Phase 1 | Pending |
| VAL-11 | Phase 1 | Complete |
| VAL-12 | Phase 1 | Pending |
| VAL-13 | Phase 1 | Complete |
| VAL-14 | Phase 1 | Complete |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 14
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-10*
*Last updated: 2026-05-10 after initial definition from validate phase spec*
