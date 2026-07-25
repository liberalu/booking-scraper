# Dashboard Links, Sorting & UI Improvements

**Status:** Implemented
**Date:** 2026-04-14

## Overview

Adds clickable links to all stat values and table cells across the dashboard, introduces server-side column sorting for all tables, reorganizes the shop detail page with tabs, fixes the price changes duplicate bug, and removes the logs page.

---

## 1. Overview Page (`/`)

### Stat Card Links

Each stat card becomes a clickable link:

| Stat | Links To |
|------|----------|
| Total Listings | `/listings` |
| Active Listings | `/listings?active=true` |
| With ISBN | `/listings?has_isbn=true` |
| Total Prices | `/prices` |

### Recent Runs Table

- **Add "Updated" column** displaying `items_updated` (between Added and Errors).
- **Added, Updated, Errors** values become links to `/runs/{run_id}` (the run detail page, which already shows created/updated listings and validation issues).

---

## 2. Listings Page (`/listings`)

### New Filters

**Active filter** (`active` query param):
- Values: empty (all), `true` (active only), `false` (not active only)
- UI: dropdown with "All" / "Active" / "Not Active"
- Query: filters on `Listing.is_active`

**Has ISBN filter** (`has_isbn` query param):
- Values: empty (all), `true` (with ISBN only)
- Query: filters on `Listing.isbn IS NOT NULL`
- No UI dropdown needed — used only as a link target from the overview stat card. If present, show a dismissible filter badge or note.

---

## 3. Shop Detail Page (`/shops/{name}`)

### Stat Block Links

| Stat | Links To |
|------|----------|
| Discovered URLs | No link (no dedicated page) |
| Listings | `/listings?shop={name}` |
| Active | `/listings?shop={name}&active=true` |
| Prices | `/prices?shop={name}` |
| Not Listed | `/shops/{name}/not-listed` |

### "Not Listed" Stat and Page

**New stat:** Count of discovered URLs that have no matching listing (these are non-book pages like blogs, info pages).

**Query:** Count `discovered_urls` where the URL does not match any `listing.url` for the shop.

**New route:** `GET /shops/{name}/not-listed` — shows a paginated table of these discovered URLs with columns: URL, First Discovered, Last Seen. Each URL is an external link.

### Tab Layout

Two tabs on the shop detail page (JS-based, same URL):

**Tab 1: "Runs"** (default)
- Run Commands section at top (Discover Sitemap, Discover Categories, Scan, Rescrape All buttons)
- Recent Runs table below

**Tab 2: "Data"**
- Data Completeness table
- Any scan-related statistics

### Runs Table Changes

- **Added, Updated, Errors** values become links to `/runs/{run_id}`

### Removed

- "Scrape Single URL" form — removed from the page entirely.

---

## 4. Shops List Page (`/shops`)

### Stat Block Links

Each stat in the shop cards becomes a link:

| Stat | Links To |
|------|----------|
| Discovered URLs | No link |
| Listings | `/listings?shop={name}` |
| Active | `/listings?shop={name}&active=true` |
| Prices | `/prices?shop={name}` |

---

## 5. Runs Page (`/runs`)

### Run Commands

Add the same run command buttons (Discover Sitemap, Discover Categories, Scan, Rescrape All) above the runs table.

### Table Changes

- **Added, Updated, Errors** values become links to `/runs/{run_id}`

---

## 6. Prices Page (`/prices`)

### Bug Fix: Duplicate Price Change Entries

**Problem:** The `get_price_changes()` query uses `LAG()` over all price records within the cutoff window. When a listing has multiple price records that produce the same change (e.g., scraped by both discover and scan in the same period), the same price difference appears multiple times.

**Fix:** After computing changes, deduplicate by keeping only the most recent row per `(listing_id, prev_price, new_price)` group. Add a `ROW_NUMBER()` window partitioned by `(listing_id, prev_price, new_price)` ordered by `scraped_at DESC`, then filter to `row_num = 1`.

### Shop Filter

Add optional `shop` query param to filter price changes by shop. Used when linking from shop detail page.

---

## 6b. Shop Detail Runs List Bug

**Problem:** Run 41 (a scan with one update) appears at `/runs/41` but does not show in the shop detail runs list. Likely caused by the `LIMIT 20` in `get_shop_runs()` or a filter issue. Investigation needed during implementation — fix the query so all recent runs appear (increase limit or add pagination).

---

## 7. Logs Page — Removed

Delete:
- `book_scraper/dashboard/routes/logs.py`
- `book_scraper/dashboard/templates/logs.html`
- Nav link in `base.html`
- Router inclusion in `app.py`

---

## 8. Server-Side Column Sorting (All Tables)

### Mechanism

Every table supports sorting via query params:
- `sort` — column name (e.g., `started_at`, `title`, `price`)
- `order` — `asc` or `desc`

### UI

Column headers become clickable links. Clicking a column:
- If not currently sorted by that column → sorts ASC
- If currently sorted ASC → toggles to DESC
- If currently sorted DESC → toggles to ASC

Arrow indicators: `▲` for ASC, `▼` for DESC, shown next to the active sort column.

### Implementation

**Jinja macro:** A reusable `sort_header(column, label, current_sort, current_order, base_url)` macro that generates the `<a>` tag with correct params and arrow indicator. All existing query params are preserved.

**Query layer:** Sorting functions accept `sort_by` and `sort_order` params. Use an allowlist of sortable columns per table to prevent SQL injection. Fall back to default sort if the requested column is not in the allowlist.

### Tables and Their Sortable Columns

| Page | Table | Sortable Columns | Default Sort |
|------|-------|-----------------|--------------|
| Overview | Recent Runs | id, phase, status, started_at, items_added, items_updated, error_count | started_at DESC |
| Shops | Shop cards | name, listings, active, prices | name ASC |
| Shop Detail | Recent Runs | id, phase, status, started_at, duration, items_added, items_updated, error_count | started_at DESC |
| Shop Detail | Data Completeness | field, present, missing, pct | pct DESC |
| Listings | Listings | id, title, author, isbn, price, year, is_active | id DESC |
| Runs | Recent Runs | id, shop, phase, status, started_at, duration, items_added, items_updated, error_count | started_at DESC |
| Prices | Recent Price Changes | title, prev_price, new_price, change, scraped_at | change DESC (absolute) |
| Not Listed | URLs | url, first_discovered | first_discovered DESC |

### Param Preservation

Sort params must coexist with existing filters. The sort header macro appends `sort` and `order` to the current URL's query string, preserving all other params (page, q, author, active, etc.).

---

## 9. Listings `shop` Filter

The listings page needs a `shop` query param so shop detail pages can link to filtered listings. This is an implicit filter (no dropdown needed) — when present, show a note like "Filtered by shop: vaga" with a clear link.

---

## Files Changed

### Modified
- `book_scraper/dashboard/queries.py` — add sorting params to all query functions, new filters, fix price dedup, not-listed query
- `book_scraper/dashboard/routes/overview.py` — pass sort params
- `book_scraper/dashboard/routes/shops.py` — add not-listed route, pass sort params, add shop filter to prices link
- `book_scraper/dashboard/routes/runs.py` — pass sort params
- `book_scraper/dashboard/routes/prices.py` — add shop filter, pass sort params
- `book_scraper/dashboard/routes/listings.py` — add active, has_isbn, shop filters, pass sort params
- `book_scraper/dashboard/templates/base.html` — remove logs nav link, add sort_header macro
- `book_scraper/dashboard/templates/overview.html` — stat links, updated column, cell links
- `book_scraper/dashboard/templates/shops.html` — stat links
- `book_scraper/dashboard/templates/shop_detail.html` — tabs, stat links, run commands, remove scrape-single-url
- `book_scraper/dashboard/templates/runs.html` — run commands, cell links, sorting
- `book_scraper/dashboard/templates/prices.html` — sorting, shop filter
- `book_scraper/dashboard/templates/listings.html` — active dropdown, sorting, shop/isbn filter badges
- `book_scraper/dashboard/app.py` — remove logs router

### New
- `book_scraper/dashboard/templates/not_listed.html` — not-listed page template

### Deleted
- `book_scraper/dashboard/routes/logs.py`
- `book_scraper/dashboard/templates/logs.html`
