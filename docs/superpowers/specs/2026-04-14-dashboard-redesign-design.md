# Dashboard Redesign — Design Spec

## Goal

Restyle the existing FastAPI + Jinja2 dashboard with a "Clean & Airy" minimal aesthetic, add dark/light theme toggle, reorganize navigation (replace Inventory with new Discovered URLs page), and merge Inventory stats into Overview.

## Scope

- Visual restyling only — no framework change, no new JS dependencies
- Keep Pico CSS, add custom CSS layer on top
- Keep HTMX and Chart.js as-is
- All existing functionality preserved

## Non-Goals

- No switch to React/Vue/Svelte
- No UX workflow changes (filtering, sorting, pagination stay the same)
- No backend/API changes beyond what the new Discovered URLs page requires

---

## Page Structure

Seven pages total. Inventory is removed; Discovered URLs is added.

| Page | URL | Purpose |
|------|-----|---------|
| Overview | `/` | Stats, data completeness (from Inventory), recent runs, validation summary |
| Listings | `/listings` | Browsable table with filters, sorting, pagination |
| Discovered URLs | `/urls` | All discovered URLs, filter for "not in listings" |
| Shops | `/shops` | Per-shop stats, shop detail with run controls |
| Runs | `/runs` | Scrape run log, run detail with live status |
| Prices | `/prices` | Recent price changes, search, charts |
| Validation | `/validation` | Issues by type, drill into details |

**Navigation:** Horizontal top nav bar with links to all 7 pages. Active page indicated by bold text + bottom border. Dark/light toggle icon (sun/moon) on the right side of the nav bar.

---

## Visual Design System

### Style: Clean & Airy

- White cards on light gray background (light theme)
- Near-black cards on dark background (dark theme)
- Thin 1px borders, 8px border-radius on cards
- Generous spacing (14-16px card padding, 10-12px grid gaps)
- System font stack (`-apple-system, system-ui, sans-serif`)
- Status indicators as colored pill badges (border-radius: 10px)

### Color Tokens

```css
[data-theme="light"] {
  --bg-page: #f8f9fa;
  --bg-card: #ffffff;
  --bg-table-header: #f8f9fa;
  --border: #e9ecef;
  --border-subtle: #f1f3f5;
  --text-primary: #1a1a2e;
  --text-secondary: #868e96;
  --text-heading: #1a1a2e;
  --link: #1971c2;
  --progress-bar: #1a1a2e;
  --progress-track: #f1f3f5;
}

[data-theme="dark"] {
  --bg-page: #111318;
  --bg-card: #16181d;
  --bg-table-header: #16181d;
  --border: #2a2d35;
  --border-subtle: #1e2028;
  --text-primary: #c9cdd3;
  --text-secondary: #6b7280;
  --text-heading: #e4e6ea;
  --link: #5ca4e8;
  --progress-bar: #c9cdd3;
  --progress-track: #2a2d35;
}
```

### Status Badge Colors (both themes)

| Status | Light | Dark |
|--------|-------|------|
| Completed / Success / Product | bg `#d3f9d8`, text `#2b8a3e` | bg `#1a3a2a`, text `#4ade80` |
| Failed / Error / Non-product | bg `#ffe3e3`, text `#c92a2a` | bg `#3a1a1a`, text `#f87171` |
| Running | bg `#d0ebff`, text `#1971c2` | bg `#1a2a3a`, text `#60a5fa` |
| Warning / Validation | bg `#fff3e0`, text `#e67700` | bg `#3a2a1a`, text `#fbbf24` |
| Neutral / Unknown | bg `#e9ecef`, text `#495057` | bg `#2a2d35`, text `#9ca3af` |

### Typography

- Page titles: 18px, font-weight 600
- Section headings: 12px, font-weight 600
- Stat card labels: 10px, uppercase, letter-spacing 0.5px, font-weight 500, secondary color
- Stat card values: 24px, font-weight 700
- Table headers: 10px, font-weight 500, secondary color
- Table body: 11px
- Filter labels: 10px, secondary color, font-weight 500

### Components

**Stat cards:** White/dark card with border, rounded corners. Label on top (small, uppercase, secondary), value below (large, bold). Optional percentage or sub-text below value.

**Tables:** Inside cards. Header row with subtle background. Thin bottom borders between rows. Right-aligned numeric columns. Sortable columns have `▲▼` arrows via the existing `sort_header` macro.

**Filter bar:** Card with horizontal flex layout. Label + select pairs. Active filters shown as pill badges with `×` dismiss button. Results count below.

**Progress bars:** Thin (4px height), rounded, track color + fill color from CSS custom properties. Used for data completeness on Overview.

**Pagination:** Centered row. Current page as dark pill, other pages as plain text. Previous/Next links.

---

## Dark/Light Theme Toggle

### Implementation

1. **Pico CSS**: Already supports `data-theme="light"` and `data-theme="dark"` on `<html>`. Currently hardcoded to `data-theme="light"`.

2. **Custom CSS file**: New `book_scraper/dashboard/static/dashboard.css` containing all CSS custom property definitions and component styles. Loaded after Pico CSS in `base.html`.

3. **Toggle button**: Sun/moon icon button in the nav bar (right-aligned). Clicking it:
   - Swaps `data-theme` attribute on `<html>` between `light` and `dark`
   - Updates the icon (sun ↔ moon)
   - Saves choice to `localStorage.setItem('theme', 'light'|'dark')`

4. **No flash on load**: Inline `<script>` in `<head>` (before CSS loads) reads `localStorage.getItem('theme')` and sets `data-theme` immediately. Defaults to `light` if no saved preference.

5. **Chart.js theming**: Charts read colors from CSS custom properties via `getComputedStyle()` so they update when the theme changes. Existing chart initialization code will be updated to use theme-aware colors.

---

## New Page: Discovered URLs

### Route

- List: `GET /urls` → `discovered_urls.html`
- No detail page (URLs link externally to the shop site)

### Stat Cards

| Card | Value | Notes |
|------|-------|-------|
| Total URLs | Count of all discovered_urls | Plain number |
| In Listings | Count where matching listing exists | Show percentage |
| Not in Listings | Count where no matching listing | Amber highlight, show percentage |
| Failed (3+) | Count where fail_count >= 3 | Red highlight |

### Filters

| Filter | Options | Default |
|--------|---------|---------|
| Shop | All shops / each shop by name | All |
| Source | All / sitemap / category / full_crawl | All |
| Status | All / Not in listings / Failed / By url_type (unknown, product, non_product) | All |
| Search | Text search on URL | Empty |

### Table Columns

| Column | Sortable | Notes |
|--------|----------|-------|
| URL | Yes | Truncated with ellipsis, links to external URL |
| Shop | No | Shop name |
| Source | No | sitemap / category / full_crawl as plain text |
| Type | No | unknown / product / non_product as colored pill badge |
| Fails | Yes | Numeric fail count |
| HTTP | No | Last HTTP status code, red if 4xx/5xx |
| Discovered | Yes (default, desc) | Date of discovery |

### Query Logic

"Not in listings" detection uses a LEFT JOIN:

```sql
SELECT du.*
FROM discovered_urls du
LEFT JOIN listings l ON l.shop_id = du.shop_id AND l.url = du.url
WHERE l.id IS NULL  -- not in listings filter
```

Pagination: 50 per page, matching the Listings page.

---

## Changes to Existing Pages

### Overview (modified)

Absorbs Inventory content:
- **Data Completeness** section: horizontal progress bars showing percentage for author, ISBN, publisher, year, format fields. Replaces the Inventory page's bar chart.
- **Format Breakdown**: Removed. The pie chart from Inventory does not add value alongside the progress bars. Format data is already visible as a column/filter on the Listings page.
- Existing stat cards, recent runs table, and validation summary remain.

Layout: stat cards row → two-column grid (data completeness left, recent runs right) → validation summary row.

### Inventory (removed)

Route removed. All useful content (data completeness, format breakdown) moved to Overview.

### All Existing Pages (restyled)

Every page gets the new design system applied:
- Cards use `--bg-card` and `--border` custom properties
- Page background uses `--bg-page`
- Text uses `--text-primary` and `--text-secondary`
- Status badges use the defined badge color pairs
- Tables use the defined table styles
- The `sort_header` macro arrow styling updated to use custom properties

### base.html (modified)

- Add `<link>` to new `dashboard.css` static file (after Pico CSS CDN)
- Add inline `<script>` in `<head>` for theme initialization from localStorage
- Add theme toggle button to nav
- Remove inline `<style>` blocks — move all custom styles to `dashboard.css`
- Update nav links: replace "Inventory" with "URLs"

---

## File Changes Summary

| Action | File |
|--------|------|
| Create | `book_scraper/dashboard/static/dashboard.css` |
| Create | `book_scraper/dashboard/routes/urls.py` |
| Create | `book_scraper/dashboard/templates/discovered_urls.html` |
| Modify | `book_scraper/dashboard/app.py` (add urls router, remove inventory router, serve static files) |
| Modify | `book_scraper/dashboard/queries.py` (add discovered URL queries) |
| Modify | `book_scraper/dashboard/templates/base.html` (CSS link, theme script, nav, toggle) |
| Modify | `book_scraper/dashboard/templates/overview.html` (add data completeness, format breakdown) |
| Modify | All other templates (restyle with CSS classes instead of inline styles) |
| Delete | `book_scraper/dashboard/routes/inventory.py` |
| Delete | `book_scraper/dashboard/templates/inventory.html` |
