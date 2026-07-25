# Fault Tolerance & Resumable Scraping — Design Spec

**Status:** Implemented
**Date:** 2026-04-06
**Goal:** Make scraping resumable after crashes, track discovered URLs in PostgreSQL, and refactor spiders into generic per-phase classes that work across all shops.

---

## Problem

The current system has three issues:

1. **No resume.** If a scan crashes on page 150 of 200, the next run re-scrapes pages 1–149 (safe due to upserts, but slow).
2. **Discovered URLs are lost.** `vaga_discover` yields `DiscoveredUrlItem` but nothing persists it. `vaga_scan` independently re-crawls categories.
3. **Per-shop spider classes.** Adding a shop requires creating 3 spider classes (`discover`, `scan`, `prices`). With N shops this becomes repetitive — the spiders are identical except for which config/parsers they load.

## Solution Overview

Two new database tables (`discovered_urls`, `scrape_runs`), two generic spider classes (`discover`, `scan`), and removal of the separate `prices` spider. Category crawling extracts prices as a side effect of discovery, eliminating duplicate page fetches.

---

## New Database Tables

### `discovered_urls`

Accumulate-only URL inventory per shop. URLs are never deleted — only marked by type.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| shop_id | FK → shops | |
| url | text | |
| source | enum | `sitemap`, `category`, `full_crawl` |
| url_type | enum | `unknown`, `product`, `non_product` — default `unknown` |
| fail_count | int | default 0, reset to 0 on successful scrape |
| last_http_status | int, nullable | 200, 404, 500, etc. |
| last_checked_at | timestamptz, nullable | last time scan attempted this URL |
| discovered_at | timestamptz | when first discovered |

**Constraints:**
- Unique on `(shop_id, url)` — re-discovering an existing URL is a no-op
- Index on `(shop_id, url_type, fail_count)` for scan filtering queries

### `scrape_runs`

Thin log of scraping activity. One row per run per phase.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| shop_id | FK → shops | |
| phase | enum | `discover_sitemap`, `discover_categories`, `discover_full_crawl`, `scan` |
| status | enum | `running`, `completed`, `failed` |
| started_at | timestamptz | |
| finished_at | timestamptz, nullable | null if still running or crashed |
| urls_total | int, nullable | set at start of run |
| urls_processed | int | default 0, incremented periodically |

**Crash detection:** A previous run with `status=running` and `finished_at=null` is a crashed run. The next run marks it `failed` before starting.

**Migration:** Both tables in a single Alembic migration.

---

## Spider Architecture

### Generic spiders replace per-shop spiders

Three generic spider classes, shop passed as argument:

```bash
scrapy crawl discover -a shop=vaga -a strategy=sitemap
scrapy crawl discover -a shop=vaga -a strategy=categories
scrapy crawl discover -a shop=vaga -a strategy=full_crawl
scrapy crawl scan -a shop=vaga
```

Each spider loads config from `config/shops/{shop}.toml` and delegates parsing to `spiders/{shop}/parsers.py`. Adding a new shop requires only a TOML config file and a parsers module — no new spider classes.

The existing per-shop spiders (`vaga_discover`, `vaga_scan`, `vaga_prices`) are removed.

### Parser registry

Spiders look up parsers dynamically by shop name:

```python
# e.g. importlib: book_scraper.spiders.{shop}.parsers
parsers = load_parsers(shop_name)
parsers.parse_sitemap_urls(content)
parsers.parse_category_page(html)
parsers.parse_product_page(html)
```

Each shop's `parsers.py` exports the same interface. The spider doesn't know shop-specific details.

---

## Discovery Phase

### Three strategies

| Strategy | Source | Speed | Extracts prices? | Auto-trigger |
|----------|--------|-------|-------------------|-------------|
| `sitemap` | Sitemap XML | Fast (1 request) | No | Yes, via `max_age_hours` |
| `categories` | Category pagination | Medium | Yes | Yes, via `max_age_hours` |
| `full_crawl` | All internal links from start URL | Slow | No | No (manual only) |

### Configuration

Per-shop TOML config specifies available strategies and their schedules:

```toml
[shop]
name = "vaga"
base_url = "https://vaga.lt"

[scraping]
download_delay = 0.5
concurrent_requests_per_domain = 3

[discover.sitemap]
url = "https://vaga.lt/sitemap.xml"
max_age_hours = 168              # weekly auto-trigger

[discover.categories]
url = "https://vaga.lt/knygos?limit=100&page={page}"
max_age_hours = 672              # ~monthly auto-trigger

[discover.full_crawl]
start_url = "https://vaga.lt"
# no max_age_hours = manual only
```

### URL filtering at discovery time

Each shop can define URL patterns to filter out non-product URLs during discovery:

```toml
[discover]
url_include_pattern = "^https://vaga\\.lt/[a-z0-9-]+-\\d+$"   # product URL pattern
# or
url_exclude_patterns = ["/blog/", "/about/", "/contacts/"]
```

URLs that don't match are not inserted into `discovered_urls`. This reduces junk from sitemaps and full crawls. Additionally, the `url_type` column provides a second layer: scan marks URLs as `non_product` if the parser finds no product data, and future runs skip them.

### Category discovery extracts prices

When `strategy=categories`, the discover spider parses category pages and yields both:
- `DiscoveredUrlItem` → inserted into `discovered_urls`
- `PriceItem` → processed by existing pipeline (upsert listing price, append to prices table)

This eliminates the separate `vaga_prices` spider. Price tracking runs as `discover -a strategy=categories`.

### Accumulate-only semantics

Discovered URLs are never deleted. Re-discovering an existing URL is a no-op (upsert on `(shop_id, url)` unique constraint). The `source` column records how the URL was originally found.

---

## Scan Phase

### Flow

1. **Create `scrape_runs` entry** — status=running, started_at=now
2. **Detect crashed runs** — any previous run for this shop+scan with status=running and finished_at=null → mark as `failed`
3. **Auto-discover check** — query `discovered_urls` for this shop. If no URLs exist at all, error out with instructions to run discover first. If URLs exist but the last discover run is older than `max_age_hours`, log a warning but proceed with existing URLs
4. **Load work queue** — query `discovered_urls` for this shop where:
   - `url_type != 'non_product'`
   - `fail_count < 3` OR `last_checked_at` is older than 7 days (retry stale failures)
5. **Filter already-done** — exclude URLs where the corresponding listing has `last_seen_at >= current_run.started_at` (already scraped in this run) or `last_seen_at >= crashed_run.started_at` (scraped before crash)
6. **Scrape** — for each URL, request the product page, run parser:
   - **Success:** upsert listing, insert price, update `discovered_urls` (last_http_status=200, fail_count=0, last_checked_at=now, url_type=product)
   - **404/410:** update `discovered_urls` (last_http_status, fail_count++, last_checked_at=now)
   - **Parse failure (200 but no product data):** update `discovered_urls` (url_type=non_product, last_checked_at=now)
   - **Other error (500, timeout):** update `discovered_urls` (last_http_status, fail_count++, last_checked_at=now)
7. **Progress tracking** — increment `urls_processed` on `scrape_runs` every 100 items (piggyback on existing commit cycle)
8. **Completion** — set status=completed, finished_at=now

### Resume after crash

If scan crashes at item 5000 of 20000:
1. Next run detects the stale `running` entry → marks it `failed`
2. Loads all URLs from `discovered_urls`
3. Finds 5000 listings with `last_seen_at >= failed_run.started_at` → skips them
4. Scrapes the remaining ~15000 URLs

No data loss — the pipeline's existing upsert + 100-item commit batching ensures everything before the crash is safe.

---

## Pipeline Changes

### `DiscoveredUrlItem` processing

Currently `DiscoveredUrlItem` is not processed by any pipeline. Add handling in `PostgresPipeline`:

- Upsert into `discovered_urls` table (insert if new, no-op if exists)
- Set `source` from the item

### `scrape_runs` integration

The pipeline (or spider) manages `scrape_runs` lifecycle:
- Spider `open_spider` → create run entry
- Pipeline commit cycle → update `urls_processed`
- Spider `close_spider` → set status=completed/failed, finished_at=now

### Existing behavior preserved

- `ListingItem` processing unchanged (upsert_listing + insert_price)
- `PriceItem` processing unchanged (upsert_listing minimal + insert_price)
- 100-item commit batching unchanged
- `ValidationPipeline` unchanged

---

## Config Changes

### Shop TOML restructure

The `[discover]`, `[scan]`, and `[prices]` sections are replaced with strategy-specific discovery sections. The `[prices]` section is removed since category discovery handles price extraction.

**Before:**
```toml
[discover]
sitemap_url = "https://vaga.lt/sitemap.xml"

[scan]
category_url = "https://vaga.lt/knygos?limit=100&page={page}"

[prices]
category_url = "https://vaga.lt/knygos?limit=100&page={page}"
```

**After:**
```toml
[discover.sitemap]
url = "https://vaga.lt/sitemap.xml"
max_age_hours = 168

[discover.categories]
url = "https://vaga.lt/knygos?limit=100&page={page}"
max_age_hours = 672

[discover.full_crawl]
start_url = "https://vaga.lt"

[discover]
url_include_pattern = "^https://vaga\\.lt/[a-z0-9-]+-\\d+$"

[scan]
# no URL needed — reads from discovered_urls table
```

---

## What Gets Removed

- `book_scraper/spiders/vaga/discover.py` → replaced by generic `discover` spider
- `book_scraper/spiders/vaga/scan.py` → replaced by generic `scan` spider
- `book_scraper/spiders/vaga/prices.py` → eliminated (category discovery handles prices)
- Per-shop spider classes in general — no new spider classes per shop

What stays:
- `book_scraper/spiders/vaga/parsers.py` — shop-specific parsing logic, unchanged
- `book_scraper/spiders/vaga/__init__.py` — stays as parser package

---

## Operational Usage

### Daily/weekly price tracking
```bash
scrapy crawl discover -a shop=vaga -a strategy=categories
```
Discovers new URLs + extracts current prices from category pages.

### Weekly full scan of new products
```bash
scrapy crawl scan -a shop=vaga
```
Auto-discovers if needed, then scrapes full product pages for any URL not recently scanned.

### Initial setup for a new shop
```bash
scrapy crawl discover -a shop=newshop -a strategy=sitemap
scrapy crawl discover -a shop=newshop -a strategy=full_crawl
scrapy crawl scan -a shop=newshop
```

### Crash recovery
```bash
# Just re-run — it resumes automatically
scrapy crawl scan -a shop=vaga
```

### Recommended wrapper for long runs
```bash
tmux new -s scrape
caffeinate -i scrapy crawl scan -a shop=vaga
# Ctrl+B, D to detach
```

---

## Testing

- **New repo functions** (`upsert_discovered_url`, `get_pending_urls`, `create_scrape_run`, etc.) — tested against real PostgreSQL (existing pattern)
- **Generic spider wiring** — test that `discover` and `scan` spiders load correct parsers for a shop name
- **Resume logic** — test that scan skips URLs with recent `last_seen_at`
- **Crash detection** — test that stale `running` entries get marked `failed`
- **URL filtering** — test pattern matching against shop config
- **Parser tests** — unchanged, parsers are decoupled from spiders

---

## Out of Scope

- **Change detection** (marking delisted listings) — separate future work, will use `discovered_urls` + `mark_listings_inactive`
- **Book matching** — unrelated to fault tolerance
- **Scheduling/cron** — manual runs for now, scheduling is operational
- **Scrapy JOBDIR** — not needed, DB-based resume is more robust and portable
