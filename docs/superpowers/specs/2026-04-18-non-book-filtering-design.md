# Non-Book Filtering Design

**Status:** Implemented
**Date:** 2026-04-18

## Problem

The scan spider stores items in `shop_books` even when the parser's `classify_book_product()` classifier determines they are not books (e.g. board games, toys). The spider only uses title absence as the non-product gate, so anything with a title — regardless of its book score — gets persisted as a `ShopBook` with `type = 'non_book'`. These rows pollute the table with data that has no value to the price tracker.

## Goal

Ensure `shop_books` contains only genuine book products. Non-books are excluded at scrape time and existing non-book rows are removed.

## Design

### Part 1 — Scan spider gate

In `book_scraper/spiders/scan.py`, replace the title-only check with the `is_book_product` flag that `parse_product_page()` already computes:

**Before:**
```python
if not data.get("title"):
    self._queue_url_status_update(
        discovered_url_id, http_status=200, url_type="non_product"
    )
    return
```

**After:**
```python
if not data.get("is_book_product"):
    self._queue_url_status_update(
        discovered_url_id, http_status=200, url_type="non_product"
    )
    return
```

`classify_book_product()` already returns `is_book_product = False` when there is no title, so the title check is fully subsumed. The URL is marked `non_product` in `discovered_urls`, which excludes it from all future scan queues.

### Part 2 — Alembic migration: delete existing `non_book` rows

A new migration cleans up rows already in the database. Steps execute in order to satisfy FK constraints:

1. **Mark discovered URLs as non-product** — for all `discovered_urls` whose `shop_book_id` points to a `non_book` shop_book, set `url_type = 'non_product'`. This prevents re-scraping and re-creation after the rows are deleted.

2. **Delete dependent rows** — delete from `prices`, `shop_book_changes`, and `validation_issues` where `shop_book_id` is in the `non_book` set. Tables with `ondelete="CASCADE"` at the DB level (`shop_book_attributes`, `shop_book_authors`, `shop_book_field_updates`) are handled automatically.

3. **Delete non-book shop_books** — `DELETE FROM shop_books WHERE type = 'non_book'`.

### Part 3 — No validation issue

Non-product URLs are silently excluded — the same behaviour as pages with no title. There is nothing actionable to surface in the issues dashboard.

## Scope

- Changes: `book_scraper/spiders/scan.py` (one-line change), one new Alembic migration
- No model changes, no dashboard changes, no parser changes
- The `classify_book_product()` scorer and `is_book_product` field in parser output are unchanged

## Testing

- Unit test in `tests/unit/test_spiders.py`: scan spider yields nothing and queues `non_product` status when `parse_product_page()` returns `is_book_product = False` with a non-empty title
- Existing unit test `assert spider._url_status_updates[-1]["url_type"] == "product"` for a valid book remains green
- Migration is tested implicitly by the integration test suite (real DB on port 5433)
