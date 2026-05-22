# Specs Index

Single source of truth for every design spec under `docs/superpowers/specs/`,
grouped by `**Status:**` header. Use this to see what's queued, in progress, and shipped.

**Adding a new feature idea?** Create a new `YYYY-MM-DD-name-design.md` here with a `**Status:** Draft` header. It'll show up in the `Draft — unbuilt` bucket on the next regenerate.

**Shipped a spec?** Change its `**Status:**` line to `Implemented` (and optionally cite the commits).

**Regenerate this index:**

```bash
python3 docs/superpowers/scripts/build-spec-index.py
```

**Total specs:** 25

## Draft — unbuilt (2)

- **[Shop Books Validate Phase — Design Spec](2026-05-10-shop-books-validate-phase-design.md)**
  - Status: _Draft — not yet planned or implemented_

- **[Data Quality Rules — Design](2026-05-18-data-quality-rules-design.md)**
  - Status: _Draft — not yet planned or implemented_
  - After a session of triaging real validator issues across pegasas, patogupirkti, vaga, and humanitas, a recurring pattern emerged: most "broken" entries are not bugs in the data itself but limits of our current validation and matching logic.

## Approved — awaiting build (6)

- **[URLs Page Enhancements — Design Spec](2026-04-19-urls-page-enhancements-design.md)**
  - Status: _Approved_
  - Three related improvements to the Discovered URLs dashboard page:.

- **[Live Scrape Observability — Design](2026-04-26-live-scrape-observability-design.md)**
  - Status: _Ready for implementation_
  - The scan pipeline runs as one Scrapy process per shop, throttled to 1 request/sec by design (vaga.lt silently blocks bursts).

- **[Run Detail Page Redesign](2026-04-27-run-detail-redesign-design.md)**
  - Status: _Approved for implementation_
  - Replace the current `HFRunDetail` layout with the new design from `_download 3/hifi/hf-runs.jsx` (~April 27 mockup), wired to live APIs.

- **[Canonical Books Layer](2026-05-08-canonical-books-layer-design.md)**
  - Status: _Design approved, awaiting implementation plan_

- **[Single-Row Restarts + Auto-Retry Failed URLs](2026-05-09-restart-and-retry-design.md)**
  - Status: _Approved (brainstorming → spec)_
  - Today, every time a scrape run stalls and re-spawns, a new `scrape_runs` row is created via `inherit_pending_items`.

- **[Canonical Issue Registry Design](2026-05-11-canonical-issue-registry-design.md)**
  - Status: _Approved_
  - `validation_issues` is an append-only log: every validation run inserts fresh rows for every.

## Design — pre-approval (1)

- **[Issues page redesign — flat list](2026-04-17-issues-page-redesign-design.md)**
  - Status: _Design_

## In progress / Partial (1)

- **[Chain Trigger Type Design](2026-05-08-chain-trigger-type-design.md)**
  - Status: _Partially implemented — chain wiring in place via `chain_to_job_id`; `triggered_by` column on `scrape_runs` and UI trigger badge not yet added_
  - Enforce exclusive triggers (cron OR chain, not both) and surface trigger type in the Schedules UI and per-run history.

## Implemented (14)

- **[Book Price Scraper — Design Spec](2026-04-05-book-scraper-design.md)**
  - Status: _Implemented_
  - Build a multi-shop book price comparison system for Lithuanian e-shops.

- **[Fault Tolerance & Resumable Scraping — Design Spec](2026-04-06-fault-tolerance-design.md)**
  - Status: _Implemented_
  - Make scraping resumable after crashes, track discovered URLs in PostgreSQL, and refactor spiders into generic per-phase classes that work across all shops.

- **[Docker + Monitoring Dashboard Design](2026-04-10-docker-dashboard-design.md)**
  - Status: _Implemented_
  - Containerize the book scraper and add a web-based monitoring dashboard.

- **[Dashboard Links, Sorting & UI Improvements](2026-04-14-dashboard-links-sorting-design.md)**
  - Status: _Implemented_
  - Adds clickable links to all stat values and table cells across the dashboard, introduces server-side column sorting for all tables, reorganizes the shop detail page with tabs, fixes the price changes duplicate bug, and removes the logs page.

- **[Dashboard Redesign — Design Spec](2026-04-14-dashboard-redesign-design.md)**
  - Status: _Implemented_
  - Restyle the existing FastAPI + Jinja2 dashboard with a "Clean & Airy" minimal aesthetic, add dark/light theme toggle, reorganize navigation (replace Inventory with new Discovered URLs page), and merge Inventory stats into Overview.

- **[Dashboard Modern Redesign — Design Spec](2026-04-18-modern-redesign-design.md)**
  - Status: _Implemented_
  - Refine the existing dark/glass admin dashboard without changing its layout structure or adding new features.

- **[Non-Book Filtering Design](2026-04-18-non-book-filtering-design.md)**
  - Status: _Implemented_
  - The scan spider stores items in `shop_books` even when the parser's `classify_book_product()` classifier determines they are not books (e.g.

- **[Per-URL Run History via `scrape_url_items`](2026-04-26-scrape-url-items-history-design.md)**
  - Status: _Implemented — commits `b4386c8` (migration `7c441ea07eb2`) +_
  - `scrape_url_items` was designed as a transient work queue for the scan.

- **[Books + Schedules Polish — Design Spec](2026-05-09-books-schedules-polish-design.md)**
  - Status: _Implemented_
  - Close the small but visible gaps in the existing Books and Schedules surfaces of the hifi dashboard, and adopt the newer canonical Book detail page.

- **[Book Detail Tabs — Design Spec](2026-05-14-book-detail-tabs-design.md)**
  - Status: _Implemented_
  - Upgrade `HFBook` from a single-card layout to a tabbed detail page.

- **[Book Prices Tab — Design Spec](2026-05-14-book-prices-tab-design.md)**
  - Status: _Implemented_
  - Replace the `HFBookPricesStub` placeholder in the Book detail page with a real Prices tab showing a 30-day multi-line price chart (one line per shop) plus three KPI cards.

- **[Manual Book Creation — Design Spec](2026-05-14-manual-book-creation-design.md)**
  - Status: _Implemented_
  - Wire the existing `HFAddBookDialog` stub to a new `POST /api/books` endpoint so operators can manually add canonical books with `data_source=manual`.

- **[Metadata Tab Cross-Shop Comparison — Design Spec](2026-05-14-metadata-tab-cross-shop-design.md)**
  - Status: _Implemented_
  - Upgrade the Metadata tab on the canonical Book detail page from showing only canonical field values to showing a full cross-shop comparison matrix: per-shop Contributors table (Author row uses raw `ShopBook.author`; other roles use canonical data with `—` for shops) and per-field per-shop metadata matrix with conflict detection.

- **[Schedules Chain Visualization — Design Spec](2026-05-14-schedules-chain-visualization-design.md)**
  - Status: _Implemented_
  - Make chained cron jobs visually obvious in `HFCron`.

## Active reference (not a feature) (1)

- **[Scan strategy (vaga.lt)](2026-04-26-scan-strategy.md)**
  - Status: _Active — current behaviour as of 2026-04-26._
  - For every URL in `discovered_urls` for the shop, fetch the page once.
