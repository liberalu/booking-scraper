# URLs Page Enhancements — Design Spec

**Date:** 2026-04-19
**Status:** Approved

## Overview

Three related improvements to the Discovered URLs dashboard page:

1. Split the current mixed "status" filter into separate **type** and **status** dropdowns
2. Add a **book score column** to the list (sortable, filterable) backed by a new `url_classifications` table
3. Add a **URL detail page** at `/urls/<id>` showing metadata, linked shop book, and full score breakdown

---

## 1. Filter Bar — Split Type and Status

### Problem

The current "status" dropdown conflates two unrelated concepts:
- URL classification (`unknown`, `product`, `non_product`) — what the URL *is*
- Scrape state (`not_in_shop_books`, `failed`) — what happened to the URL

### Solution

Replace the single dropdown with two:

**Type** (`type` query param) — filters `DiscoveredUrl.url_type`:
- All types *(default)*
- `unknown`
- `product`
- `non_product`

**Status** (`status` query param) — filters derived state:
- All statuses *(default)*
- `not_in_shop_books` — `shop_book_id IS NULL`
- `failed` — `fail_count >= 3`

### Changes Required

- `book_scraper/dashboard/routes/urls.py`: add `type: str = ""` query param
- `book_scraper/dashboard/queries.py`: add `type` filter branch in `get_discovered_urls_page()`; remove `unknown`/`product`/`non_product` from the `status` filter branches
- `book_scraper/dashboard/templates/discovered_urls.html`: replace single `<select name="status">` with two selects; add `type_filter` to filter badges and `filter_params`

---

## 2. Book Score — `url_classifications` Table

### New Table

```
url_classifications
  id                 INTEGER PK
  discovered_url_id  INTEGER FK → discovered_urls.id (UNIQUE)
  book_score         INTEGER NOT NULL
  is_book_product    BOOLEAN NOT NULL
  reasons            JSONB NOT NULL   -- list of reason strings
  classified_at      DATETIME NOT NULL
```

One row per discovered URL, upserted on each scan. Index on `discovered_url_id`.

### Data Flow

1. **Scan phase**: after `parse_product_page()` returns, the pipeline reads `book_score`, `is_book_product`, and `book_score_reasons` from the parsed data dict and upserts a `url_classifications` row.
2. **Re-scan**: upserts the existing row — score and reasons update if page content changed.
3. **Discover phase**: no write to `url_classifications` (URLs not yet scraped show `—`).

The `vaga` parser already computes all three fields (`book_score`, `book_score_reasons`, `is_book_product`) in `parse_product_page()`. No parser changes needed.

### List Page Enhancements

**New column** added between "Type" and "Fails": **Score**

- Shows integer score + colored badge: `book` (green, score ≥ 3 + primary signal) or `not book` (orange)
- `—` when no `url_classifications` row exists (URL not yet scanned)
- Sortable via `DISCOVERED_URL_SORT_COLUMNS`: add `"score": UrlClassification.book_score`
- Query: LEFT JOIN `url_classifications` on `discovered_url_id`

**New filter**: `score_min` query param (integer, optional) — filters `book_score >= score_min`. Exposed as a small number input in the filter bar (e.g. "Score ≥ __").

**New filter badge**: "Score ≥ N" dismissible chip, consistent with existing filter badge style.

---

## 3. URL Detail Page `/urls/<id>`

### Route

`GET /urls/{url_id}` — returns 404 if the `DiscoveredUrl` doesn't exist.

### Template Sections

**URL metadata**
- Full URL (monospace, word-break)
- Badges: url_type, source
- Grid: Discovered, Last checked, HTTP status, Fail count

**Linked Shop Book** *(shown only when `shop_book_id` is not null)*
- Title, Author, Type (book/non_book/audio/ebook), Active, Price
- Link to `/shop-books/<id>`

**Book Score** *(shown always; "Not yet classified" when no `url_classifications` row)*
- Large score number, colored `✓ Classified as book` / `✗ Not a book` badge
- Reasons list: flat colored list from `reasons` JSONB — each string already embeds the points (e.g. `"+3 valid ISBN"`, `"-4 non-book categories"`). Strings starting with `+` are green, `-` are red, others neutral.

### Linking from List

The URL cell in the list table becomes a link to `/urls/<id>` instead of (or in addition to) a direct link to the external URL. The external URL link moves to a small icon or stays as a secondary link.

---

## Architecture Notes

- `UrlClassification` SQLAlchemy model mirrors the table above; lives in `book_scraper/db/models.py` alongside `DiscoveredUrl`
- Alembic migration creates the table and index
- New query function `get_url_classification(session, url_id)` in `queries.py` for the detail page
- Pipeline change in `book_scraper/pipelines.py`: upsert `url_classifications` after scan item is processed
- No changes to spider classes — generic `scan` spider passes data through

---

## Out of Scope

- Storing classifications for the discover phase (only scan produces scores)
- Showing score history across multiple scrapes (only latest classification stored)
- Adding score to the shop_books list/detail pages (separate concern)
