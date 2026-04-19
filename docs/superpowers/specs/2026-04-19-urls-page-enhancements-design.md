# URLs Page Enhancements — Design Spec

**Date:** 2026-04-19
**Status:** Approved

## Overview

Three related improvements to the Discovered URLs dashboard page:

1. Replace the current mixed "status" filter with a clean **type** dropdown (url_type only); remove derived-state filters
2. Add a **book score column** to the list (sortable, filterable) backed by a new `url_classifications` table
3. Add a **URL detail page** at `/urls/<id>` showing metadata, linked shop book, and full score breakdown

---

## 1. Filter Bar — Replace Status with Type

### Problem

The current "status" dropdown conflates two unrelated concepts:
- URL classification (`unknown`, `product`, `non_product`) — what the URL *is*, stored in `DiscoveredUrl.url_type`
- Derived state (`not_in_shop_books`, `failed`) — computed conditions with no dedicated DB column

This makes the filter confusing and couples unrelated concerns.

### Solution

Remove the `status` param entirely. Replace the dropdown with a **Type** filter:

**Type** (`type` query param) — filters `DiscoveredUrl.url_type`:
- All types *(default)*
- `unknown`
- `product`
- `non_product`

### Stat Cards and Compatibility

All three derived-state stat cards ("In Shop Books", "Not in Shop Books", "Failed 3+") become **display-only**. None of them mapped to a real DB column and "In Shop Books" was already a no-op filter in the current query implementation.

Old `?status=...` query params are **silently ignored** — the route drops the `status` param and treats any stale bookmarks or links as showing all results. No redirect or translation layer is added.

### Changes Required

- `book_scraper/dashboard/routes/urls.py`: remove `status: str = ""` param; add `type: str = ""` param
- `book_scraper/dashboard/queries.py`: remove `status` filter branches entirely; add `type` filter on `DiscoveredUrl.url_type`
- `book_scraper/dashboard/templates/discovered_urls.html`: replace `<select name="status">` with `<select name="type">`; make "Not in Shop Books" and "Failed 3+" stat cards non-clickable; update filter badges and `filter_params`

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

One row per discovered URL, upserted on each scan.

**Indexes:**
- `UNIQUE (discovered_url_id)` — covers the LEFT JOIN from the list query
- `(book_score)` — supports range filter (`score_min`) and ORDER BY score
- `(is_book_product)` — supports exact filter on book/not-book

### Data Flow

The scan spider (`book_scraper/spiders/scan.py`) currently returns early for non-book pages at line 270, before yielding any item. This means the Scrapy pipeline never sees non-book results. To guarantee the classification is written for **both book and non-book pages**, the write must happen in the **scan spider**, not the pipeline.

Concretely:

1. After `parse_product_page()` returns (line 260), the scan spider calls `repo.upsert_url_classification(session, discovered_url_id, data)` unconditionally — before the `is_book_product` check and early return.
2. `upsert_url_classification` lives in `book_scraper/db/repo.py` and issues a PostgreSQL `INSERT ... ON CONFLICT (discovered_url_id) DO UPDATE SET ...`.
3. The existing early-return path for non-book pages is unchanged — it still skips creating a `ShopBookItem`. Only the classification upsert is added before it.
4. **Re-scan**: same upsert overwrites the existing row.
5. **Discover phase**: no write to `url_classifications`. Discovered-but-unscanned URLs show `—` in the list.

The `vaga` parser already computes all three fields (`book_score`, `book_score_reasons`, `is_book_product`) in `parse_product_page()`. No parser changes needed.

### Backfill

Already-scanned URLs have no `url_classifications` row and will show `—` until re-scanned. This is accepted — no backfill step is planned. Score-based filtering will naturally exclude these rows, which is the correct behaviour (they have no verified classification). A full re-scan will populate them.

### List Page Enhancements

**New column** added between "Type" and "Fails": **Score**

- Shows integer score + colored badge: `book` (green, score ≥ 3 + primary signal) or `not book` (orange)
- `—` when no `url_classifications` row exists (URL not yet scanned)
- Sortable via `DISCOVERED_URL_SORT_COLUMNS`: add `"score": UrlClassification.book_score`
- Query: LEFT JOIN `url_classifications` on `discovered_url_id`
- **Null ordering**: when sorting by score with no score filter active, unclassified rows (NULL score) appear **last** (`NULLS LAST`). This applies to both ascending and descending sort directions.

**New filters** in the filter bar:

- `score_min` (integer, optional) — small number input "Score ≥ __", filters `book_score >= score_min`
- `is_book` (string, optional) — dropdown with `all` / `book` / `not book`, filters on `UrlClassification.is_book_product`; useful for quickly isolating misclassified pages

Both filters apply only to URLs that have a `url_classifications` row; URLs without a classification are excluded when either filter is active.

**New filter badges**: "Score ≥ N" and "Book: yes/no" dismissible chips, consistent with existing badge style.

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
