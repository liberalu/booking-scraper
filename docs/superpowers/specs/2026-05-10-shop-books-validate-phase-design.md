# Shop Books Validate Phase — Design Spec

**Date:** 2026-05-10  
**Status:** Draft — not yet planned or implemented

---

## Background

The current scraping pipeline has three phases per shop:

```
discover → scan → match
```

During the humanitas onboarding a new class of issue was found: silent data
quality failures that are invisible in the dashboard because they are caught by
`SQLAlchemyError` in the pipeline and rolled back before any DB trace is written.
Root cause in that case: a shop assigned a product the wrong URL slug, we scraped
it under the wrong slug, the shop later fixed the slug and recycled the old one
for a different product, which created a stale row whose SKU blocked future writes.

A fourth phase — **validate** — gives these structural issues a first-class home
instead of leaving them undetected until a manual postmortem.

---

## What Validate Does

Validate is a **read-mostly, DB-only** pass over the shop's `shop_books` rows.
It runs after scan (or independently on demand). It produces `validation_issues`
rows that surface on the dashboard's Issues tab per shop book.

It does **not** auto-fix anything. It flags; the operator resolves.

---

## Pipeline Position

```
discover → scan → match → validate
```

Validate runs per-shop, the same as the other three phases. It gets its own
`scrape_runs` row (`phase = 'validate'`) so the dashboard shows it in the run
history timeline.

---

## Checks

### Structural duplicates (cross-row)

| Check | Signal | Issue key |
|---|---|---|
| Same ISBN, same shop, two rows | `shop_books.isbn` | `isbn_duplicate` |
| Same title + author, same shop, two rows | `shop_books.title + author` | `title_author_duplicate` |
| Same SKU, same shop, two rows | `shop_books.sku` | `sku_duplicate` (shouldn't exist due to constraint, but stale nulled SKUs can leave orphans) |

For duplicate pairs, a `validation_issue` is raised on **both** rows so the
operator can see both sides from either detail page.

### Slug-title mismatch (single-row)

After a product has been scanned (title is populated), tokenize the URL slug and
the stored title, normalise both (strip diacritics, lowercase, split on `-`/` `).
If the intersection of tokens is empty, flag as `slug_title_mismatch`.

Example: slug `vyresnio-amziaus-zmoniu-sveika` vs title `Ką šunys galvoja?` →
zero common tokens → flag.

Threshold: **0 common tokens**. Low token overlap (1–2 shared short words) is
common in Lithuanian due to case inflection, so only zero overlap is flagged.

### Data completeness (single-row)

| Check | Condition | Issue key |
|---|---|---|
| Active with no price | `is_active AND price IS NULL` | `active_no_price` |
| Active in-stock with no price | `is_active AND in_stock AND price IS NULL` | `in_stock_no_price` |
| Book type with no metadata | `type='book' AND isbn IS NULL AND author IS NULL AND year IS NULL` | `book_no_metadata` |
| No price history | `is_active AND no rows in prices` | `no_price_history` |

### Data correctness (single-row)

| Check | Condition | Issue key |
|---|---|---|
| Year out of range | `year < 1800 OR year > current_year + 2` | `year_out_of_range` |
| Price is zero | `price = 0` | `price_zero` |
| Format looks like dimensions | `format ~ '^\d+.*[xX×].*\d+'` | `format_is_dimensions` |

### Classification consistency (single-row)

| Check | Condition | Issue key |
|---|---|---|
| Book type, no book signals | `type='book' AND isbn IS NULL AND author IS NULL AND year IS NULL AND format IS NULL` | `book_no_signals` |
| Non-book type with valid ISBN | `type='non_book' AND isbn IS NOT NULL` | `non_book_has_isbn` |
| url_type=non_product but shop_book is active | `discovered_urls.url_type = 'non_product' AND shop_books.is_active` | `non_product_active` |

### Staleness / lifecycle (single-row)

| Check | Condition | Issue key |
|---|---|---|
| Active but not seen recently | `is_active AND last_seen_at < now() - 2 × shop discover cadence` | `stale_active` |
| Unreachable URL but still active | `discovered_urls.url_type = 'unreachable' AND shop_books.is_active` | `unreachable_active` |
| Orphan shop_book | No linked `discovered_urls` row | `orphan_no_url` |

### Match phase readiness (single-row)

| Check | Condition | Issue key |
|---|---|---|
| Unmatched with valid ISBN | `match_status = 'unmatched' AND isbn IS NOT NULL` | `unmatched_has_isbn` |
| Matched but ISBN drifted | `match_status = 'matched' AND books.isbn != shop_books.isbn` (both non-null) | `match_isbn_drift` |

### Relationship integrity (cross-row)

| Check | Condition | Issue key |
|---|---|---|
| Multiple URLs → same shop_book | `COUNT(discovered_urls) > 1 per shop_book_id` | `url_aliases` |
| discovered_url type=product → non-book shop_book | `url_type='product' AND shop_books.type='non_book'` | `product_url_non_book` |

---

## Severity

Each check is assigned a fixed severity:

- **critical**: `isbn_duplicate`, `in_stock_no_price`, `non_product_active`, `unreachable_active`
- **warning**: `slug_title_mismatch`, `active_no_price`, `stale_active`, `non_book_has_isbn`, `unmatched_has_isbn`, `match_isbn_drift`, `sku_duplicate`
- **info**: `book_no_metadata`, `no_price_history`, `year_out_of_range`, `price_zero`, `format_is_dimensions`, `book_no_signals`, `orphan_no_url`, `url_aliases`, `product_url_non_book`, `title_author_duplicate`

---

## Output

Each finding writes a `validation_issues` row:

```
shop_book_id  — the affected row (or both rows for duplicate pairs)
field         — issue key (e.g. 'isbn_duplicate')
issue         — human-readable summary
raw_value     — the offending value(s) (e.g. the conflicting ISBN)
scrape_run_id — the validate run that found it
lifecycle_state = 'new'
```

Existing lifecycle states (`new` → `already_seen` → acknowledged) apply
unchanged. Re-running validate on the same data does not create duplicate rows
— each check deduplicates by `(shop_book_id, field)` before inserting.

---

## Implementation Outline

**New artifacts:**
- `book_scraper/services/validate.py` — `ValidateService` with one method per
  check group, called from the spider/CLI
- `book_scraper/spiders/validate.py` — thin Scrapy spider (or plain CLI
  entrypoint) that creates the `scrape_runs` row, calls `ValidateService`, and
  marks the run complete. No HTTP requests; uses asyncio reactor or a plain sync
  call.
- `scrape_phase` enum: add `'validate'`
- Dashboard: "Run validate" button on the shop detail page alongside existing
  phase buttons

**Not needed:**
- New DB tables (reuses `validation_issues` and `scrape_runs`)
- New parser/middleware (no HTTP)
- Changes to discovery or scan logic

---

## Relationship to SKU Conflict Fix

The SKU stale-row issue (2026-05-10) is fixed at write time in `upsert_shop_book`
(detach stale SKU, fall through to URL-matched row). The validate phase provides
the detection layer: `slug_title_mismatch` and `isbn_duplicate` would have caught
the humanitas case on the next validate pass even without the write-time fix.
The two are complementary — fix prevents the IntegrityError; validate surfaces
residual data quality issues that survived earlier runs.

---

## Open Questions

- Should validate be triggered automatically after each scan completes, or only
  on demand from the dashboard? (Lean: on-demand for now, cron later.)
- Discover cadence per shop is currently implicit (TOML cron schedule). The
  `stale_active` check needs this — either read from the cron schedule or add a
  `discover_cadence_days` field to `shops`.
- Should `title_author_duplicate` flag pairs where the year also matches
  (stronger signal) vs. any title+author match (more false positives)?
