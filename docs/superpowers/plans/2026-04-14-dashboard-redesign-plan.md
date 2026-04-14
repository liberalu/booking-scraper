# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the dashboard with a "Clean & Airy" minimal aesthetic, add dark/light theme toggle, replace Inventory page with new Discovered URLs page, and merge Inventory stats into Overview.

**Architecture:** Keep FastAPI + Jinja2 + Pico CSS. Add a custom `dashboard.css` with CSS custom properties for theming. Theme toggle uses `data-theme` attribute on `<html>` with localStorage persistence. New Discovered URLs page follows the existing route/query/template pattern.

**Tech Stack:** FastAPI, Jinja2, Pico CSS 2, HTMX, Chart.js, SQLAlchemy

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `book_scraper/dashboard/static/dashboard.css` | All custom styles, CSS custom properties for theming |
| Create | `book_scraper/dashboard/routes/urls.py` | Discovered URLs route handler |
| Create | `book_scraper/dashboard/templates/discovered_urls.html` | Discovered URLs page template |
| Create | `tests/unit/test_dashboard_queries.py` | Unit tests for new query functions |
| Modify | `book_scraper/dashboard/app.py` | Add urls router, remove inventory router, mount static files |
| Modify | `book_scraper/dashboard/deps.py` | No changes needed (templates dir stays same) |
| Modify | `book_scraper/dashboard/queries.py` | Add discovered URL queries, modify overview to include completeness |
| Modify | `book_scraper/dashboard/templates/base.html` | New CSS link, theme script, updated nav, toggle button |
| Modify | `book_scraper/dashboard/templates/macros.html` | Add badge macros |
| Modify | `book_scraper/dashboard/templates/overview.html` | Add data completeness section |
| Modify | `book_scraper/dashboard/templates/listings.html` | Restyle with CSS classes |
| Modify | `book_scraper/dashboard/templates/listing_detail.html` | Restyle with CSS classes |
| Modify | `book_scraper/dashboard/templates/shops.html` | Restyle with CSS classes |
| Modify | `book_scraper/dashboard/templates/shop_detail.html` | Restyle with CSS classes, move inline styles to CSS |
| Modify | `book_scraper/dashboard/templates/runs.html` | Restyle with CSS classes, move inline styles to CSS |
| Modify | `book_scraper/dashboard/templates/run_detail.html` | Restyle with CSS classes, move inline styles to CSS |
| Modify | `book_scraper/dashboard/templates/validation.html` | Restyle with CSS classes |
| Modify | `book_scraper/dashboard/templates/validation_detail.html` | Restyle with CSS classes |
| Modify | `book_scraper/dashboard/templates/prices.html` | Restyle with CSS classes |
| Modify | `book_scraper/dashboard/routes/overview.py` | Pass completeness data to template |
| Delete | `book_scraper/dashboard/routes/inventory.py` | Replaced by Overview absorbing its data |
| Delete | `book_scraper/dashboard/templates/inventory.html` | Replaced by Overview |

---

### Task 1: Create the CSS design system

**Files:**
- Create: `book_scraper/dashboard/static/dashboard.css`
- Modify: `book_scraper/dashboard/app.py`
- Modify: `book_scraper/dashboard/templates/base.html`

- [ ] **Step 1: Create the static directory**

Run: `mkdir -p book_scraper/dashboard/static`

- [ ] **Step 2: Create dashboard.css with theme tokens and component styles**

Create `book_scraper/dashboard/static/dashboard.css`:

```css
/* ===== Theme Tokens ===== */
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

  /* Badge backgrounds */
  --badge-success-bg: #d3f9d8;
  --badge-success-text: #2b8a3e;
  --badge-error-bg: #ffe3e3;
  --badge-error-text: #c92a2a;
  --badge-running-bg: #d0ebff;
  --badge-running-text: #1971c2;
  --badge-warning-bg: #fff3e0;
  --badge-warning-text: #e67700;
  --badge-neutral-bg: #e9ecef;
  --badge-neutral-text: #495057;

  /* Health indicators */
  --health-healthy: #2b8a3e;
  --health-stale: #e67700;
  --health-dead: #c92a2a;

  /* Chart colors */
  --chart-price: #1971c2;
  --chart-original: #868e96;
  --chart-bar: #1a1a2e;

  /* Price change */
  --price-decrease: #2b8a3e;
  --price-increase: #c92a2a;
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

  --badge-success-bg: #1a3a2a;
  --badge-success-text: #4ade80;
  --badge-error-bg: #3a1a1a;
  --badge-error-text: #f87171;
  --badge-running-bg: #1a2a3a;
  --badge-running-text: #60a5fa;
  --badge-warning-bg: #3a2a1a;
  --badge-warning-text: #fbbf24;
  --badge-neutral-bg: #2a2d35;
  --badge-neutral-text: #9ca3af;

  --health-healthy: #4ade80;
  --health-stale: #fbbf24;
  --health-dead: #f87171;

  --chart-price: #5ca4e8;
  --chart-original: #6b7280;
  --chart-bar: #c9cdd3;

  --price-decrease: #4ade80;
  --price-increase: #f87171;
}

/* ===== Base Overrides ===== */
body {
  background: var(--bg-page);
  color: var(--text-primary);
  font-family: -apple-system, system-ui, 'Segoe UI', sans-serif;
}

h1, h2, h3, h4 {
  color: var(--text-heading);
}

a {
  color: var(--link);
}

/* ===== Navigation ===== */
nav.top-nav {
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  padding: 0.75rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0;
}

nav.top-nav .nav-brand {
  font-weight: 700;
  font-size: 0.9rem;
  color: var(--text-heading);
  text-decoration: none;
  margin-right: 1.5rem;
}

nav.top-nav .nav-links {
  display: flex;
  align-items: center;
  gap: 1rem;
  list-style: none;
  margin: 0;
  padding: 0;
}

nav.top-nav .nav-links a {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.8rem;
  padding-bottom: 2px;
}

nav.top-nav .nav-links a:hover {
  color: var(--text-heading);
}

nav.top-nav .nav-links a.active {
  color: var(--text-heading);
  font-weight: 600;
  border-bottom: 2px solid var(--text-heading);
}

.theme-toggle {
  background: none;
  border: 1px solid var(--border);
  border-radius: 50%;
  width: 32px;
  height: 32px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.85rem;
  color: var(--text-secondary);
  padding: 0;
}

.theme-toggle:hover {
  background: var(--bg-page);
  color: var(--text-heading);
}

/* ===== Page Layout ===== */
.page-title {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0 0 1.25rem 0;
}

/* ===== Stat Cards ===== */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1.25rem;
}

.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
  text-decoration: none;
  color: inherit;
  display: block;
}

.stat-card:hover {
  border-color: var(--text-secondary);
}

.stat-card .stat-label {
  font-size: 0.625rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 500;
}

.stat-card .stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-heading);
  margin-top: 0.25rem;
}

.stat-card .stat-sub {
  font-size: 0.625rem;
  color: var(--text-secondary);
  margin-top: 0.125rem;
}

.stat-value--warning { color: var(--badge-warning-text) !important; }
.stat-value--error { color: var(--badge-error-text) !important; }

/* ===== Cards ===== */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 0.75rem;
}

.card-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-heading);
  margin: 0 0 0.75rem 0;
}

/* ===== Tables ===== */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.7rem;
}

.data-table thead th {
  text-align: left;
  padding: 0.5rem 0.625rem;
  color: var(--text-secondary);
  font-weight: 500;
  font-size: 0.625rem;
  border-bottom: 1px solid var(--border);
  background: var(--bg-table-header);
}

.data-table thead th.text-right {
  text-align: right;
}

.data-table tbody td {
  padding: 0.5rem 0.625rem;
  border-bottom: 1px solid var(--border-subtle);
}

.data-table tbody td.text-right {
  text-align: right;
}

.data-table tbody td.text-muted {
  color: var(--text-secondary);
}

.data-table tbody tr:last-child td {
  border-bottom: none;
}

.data-table th a {
  text-decoration: none;
  color: inherit;
  white-space: nowrap;
}

.data-table th a:hover {
  text-decoration: underline;
}

.sort-arrow {
  font-size: 0.55rem;
  margin-left: 0.15rem;
}

/* Truncated cell */
.cell-truncate {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== Badges ===== */
.badge {
  padding: 0.1rem 0.5rem;
  border-radius: 10px;
  font-size: 0.6rem;
  font-weight: 600;
  display: inline-block;
}

.badge-completed { background: var(--badge-success-bg); color: var(--badge-success-text); }
.badge-failed { background: var(--badge-error-bg); color: var(--badge-error-text); }
.badge-running { background: var(--badge-running-bg); color: var(--badge-running-text); }
.badge-warning { background: var(--badge-warning-bg); color: var(--badge-warning-text); }
.badge-neutral { background: var(--badge-neutral-bg); color: var(--badge-neutral-text); }
.badge-product { background: var(--badge-success-bg); color: var(--badge-success-text); }
.badge-non_product { background: var(--badge-error-bg); color: var(--badge-error-text); }
.badge-unknown { background: var(--badge-neutral-bg); color: var(--badge-neutral-text); }

/* ===== Health Indicators ===== */
.health-healthy { color: var(--health-healthy); }
.health-stale { color: var(--health-stale); }
.health-dead { color: var(--health-dead); }

/* ===== Filter Bar ===== */
.filter-bar {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  margin-bottom: 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.filter-label {
  font-size: 0.625rem;
  color: var(--text-secondary);
  font-weight: 500;
}

.filter-bar select,
.filter-bar input[type="search"] {
  font-size: 0.7rem;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-card);
  color: var(--text-primary);
}

.filter-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  background: var(--badge-warning-bg);
  border: 1px solid var(--badge-warning-text);
  color: var(--badge-warning-text);
  padding: 0.125rem 0.625rem;
  border-radius: 12px;
  font-size: 0.625rem;
  font-weight: 500;
}

.filter-badge a {
  color: inherit;
  opacity: 0.6;
  text-decoration: none;
}

.filter-badge a:hover {
  opacity: 1;
}

.results-count {
  font-size: 0.7rem;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
}

/* ===== Progress Bars ===== */
.progress-item {
  margin-bottom: 0.5rem;
}

.progress-label {
  display: flex;
  justify-content: space-between;
  font-size: 0.625rem;
  margin-bottom: 0.2rem;
}

.progress-label-name {
  color: var(--text-primary);
}

.progress-label-value {
  color: var(--text-secondary);
}

.progress-track {
  background: var(--progress-track);
  border-radius: 4px;
  height: 4px;
}

.progress-fill {
  background: var(--progress-bar);
  border-radius: 4px;
  height: 4px;
}

/* ===== Two Column Layout ===== */
.grid-2col {
  display: grid;
  grid-template-columns: 1fr 1.5fr;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

/* ===== Pagination ===== */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
  font-size: 0.7rem;
}

.pagination .page-current {
  background: var(--text-heading);
  color: var(--bg-card);
  padding: 0.125rem 0.5rem;
  border-radius: 4px;
}

.pagination .page-link {
  color: var(--text-primary);
  padding: 0.125rem 0.5rem;
  text-decoration: none;
}

.pagination .page-disabled {
  color: var(--border);
}

.pagination .page-nav {
  color: var(--link);
  text-decoration: none;
}

/* ===== Price Change Colors ===== */
.price-decrease { color: var(--price-decrease); }
.price-increase { color: var(--price-increase); }

/* ===== Actions ===== */
.actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

/* ===== Live Status ===== */
#live-status {
  font-family: monospace;
  font-size: 0.55rem;
  padding: 0.75rem;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
}

#live-status dt { font-weight: bold; display: inline; }
#live-status dd { display: inline; margin-left: 0.5rem; margin-right: 1.5rem; }

/* ===== Validation inline summary ===== */
.validation-inline {
  display: flex;
  gap: 1rem;
  font-size: 0.7rem;
}

.validation-inline-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

/* ===== Misc ===== */
.text-muted { color: var(--text-secondary); }
.http-error { color: var(--badge-error-text); }
.mb-0 { margin-bottom: 0; }
.mt-1 { margin-top: 0.75rem; }
```

- [ ] **Step 3: Mount static files in app.py**

Replace `book_scraper/dashboard/app.py` with:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from book_scraper.dashboard.routes import (
    listings,
    overview,
    prices,
    runs,
    shops,
    validation,
)

app = FastAPI(title="Book Scraper Dashboard")

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(overview.router)
app.include_router(shops.router)
app.include_router(listings.router)
app.include_router(runs.router)
app.include_router(validation.router)
app.include_router(prices.router)
```

Note: inventory router is removed. The urls router will be added in Task 4.

- [ ] **Step 4: Rewrite base.html with new nav, theme toggle, and CSS link**

Replace `book_scraper/dashboard/templates/base.html` with:

```html
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Dashboard{% endblock %} - Book Scraper</title>
    <script>
        (function() {
            var theme = localStorage.getItem('theme') || 'light';
            document.documentElement.setAttribute('data-theme', theme);
        })();
    </script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    <link rel="stylesheet" href="/static/dashboard.css">
    <script src="https://unpkg.com/htmx.org@1.9.12"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
</head>
<body>
    <nav class="top-nav">
        <div style="display: flex; align-items: center;">
            <a href="/" class="nav-brand">BookScraper</a>
            <ul class="nav-links">
                <li><a href="/" class="{{ 'active' if active_page == 'overview' else '' }}">Overview</a></li>
                <li><a href="/listings" class="{{ 'active' if active_page == 'listings' else '' }}">Listings</a></li>
                <li><a href="/urls" class="{{ 'active' if active_page == 'urls' else '' }}">URLs</a></li>
                <li><a href="/shops" class="{{ 'active' if active_page == 'shops' else '' }}">Shops</a></li>
                <li><a href="/runs" class="{{ 'active' if active_page == 'runs' else '' }}">Runs</a></li>
                <li><a href="/prices" class="{{ 'active' if active_page == 'prices' else '' }}">Prices</a></li>
                <li><a href="/validation" class="{{ 'active' if active_page == 'validation' else '' }}">Validation</a></li>
            </ul>
        </div>
        <button class="theme-toggle" onclick="toggleTheme()" title="Toggle dark/light theme" id="theme-toggle">
            ☀
        </button>
    </nav>
    <main class="container" style="margin-top: 1.5rem;">
        {% block content %}{% endblock %}
    </main>
    <script>
        function toggleTheme() {
            var html = document.documentElement;
            var current = html.getAttribute('data-theme');
            var next = current === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
            document.getElementById('theme-toggle').textContent = next === 'dark' ? '🌙' : '☀';
        }
        // Set icon on load
        (function() {
            var theme = document.documentElement.getAttribute('data-theme');
            document.getElementById('theme-toggle').textContent = theme === 'dark' ? '🌙' : '☀';
        })();
    </script>
</body>
</html>
```

- [ ] **Step 5: Delete inventory files**

Run:
```bash
rm book_scraper/dashboard/routes/inventory.py
rm book_scraper/dashboard/templates/inventory.html
```

- [ ] **Step 6: Verify the app starts**

Run: `cd /Users/evaldas/Projects/book-scraper/.claude/worktrees/strange-mayer && uv run python -c "from book_scraper.dashboard.app import app; print('OK')"` 
Expected: `OK` (no import errors)

- [ ] **Step 7: Commit**

```bash
git add book_scraper/dashboard/static/dashboard.css book_scraper/dashboard/app.py book_scraper/dashboard/templates/base.html
git add -u book_scraper/dashboard/routes/inventory.py book_scraper/dashboard/templates/inventory.html
git commit -m "feat: add CSS design system with dark/light theme, remove inventory page"
```

---

### Task 2: Restyle Overview page with data completeness

**Files:**
- Modify: `book_scraper/dashboard/routes/overview.py`
- Modify: `book_scraper/dashboard/queries.py`
- Modify: `book_scraper/dashboard/templates/overview.html`

- [ ] **Step 1: Add `get_data_completeness` query to queries.py**

Add to the end of `book_scraper/dashboard/queries.py`:

```python
def get_data_completeness(session: Session) -> list[dict]:
    """Get field completeness percentages for the overview page."""
    total = session.query(func.count(Listing.id)).scalar() or 0
    if total == 0:
        return []
    fields = ["author", "isbn", "publisher", "year", "format"]
    result = []
    for field_name in fields:
        col = getattr(Listing, field_name)
        present = (
            session.query(func.count(Listing.id))
            .filter(col.isnot(None))
            .scalar()
            or 0
        )
        pct = round(present / total * 100, 1) if total > 0 else 0
        result.append({"field": field_name, "present": present, "total": total, "pct": pct})
    return result
```

- [ ] **Step 2: Update overview route to pass completeness data**

Replace `book_scraper/dashboard/routes/overview.py` with:

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_data_completeness,
    get_overview_stats,
    get_recent_runs,
    get_validation_summary,
)

router = APIRouter()


@router.get("/")
def overview(request: Request, session: Session = Depends(get_db)):
    stats = get_overview_stats(session)
    recent_runs = get_recent_runs(session, limit=5)
    validation = get_validation_summary(session)
    completeness = get_data_completeness(session)
    return templates.TemplateResponse(
        request,
        "overview.html",
        {
            "active_page": "overview",
            "stats": stats,
            "recent_runs": recent_runs,
            "validation": validation,
            "completeness": completeness,
        },
    )
```

- [ ] **Step 3: Rewrite overview.html template**

Replace `book_scraper/dashboard/templates/overview.html` with:

```html
{% extends "base.html" %}
{% from "macros.html" import sort_header %}
{% block title %}Overview{% endblock %}
{% block content %}
<h1 class="page-title">Overview</h1>

<div class="stat-grid">
    <a href="/listings" class="stat-card">
        <div class="stat-label">Total Listings</div>
        <div class="stat-value">{{ "{:,}".format(stats.total_listings) }}</div>
    </a>
    <a href="/listings?active=true" class="stat-card">
        <div class="stat-label">Active</div>
        <div class="stat-value">{{ "{:,}".format(stats.active_listings) }}</div>
        {% if stats.total_listings > 0 %}
        <div class="stat-sub">{{ "%.1f%%"|format(stats.active_listings / stats.total_listings * 100) }}</div>
        {% endif %}
    </a>
    <a href="/listings?has_isbn=true" class="stat-card">
        <div class="stat-label">With ISBN</div>
        <div class="stat-value">{{ "{:,}".format(stats.with_isbn) }}</div>
        {% if stats.total_listings > 0 %}
        <div class="stat-sub">{{ "%.1f%%"|format(stats.with_isbn / stats.total_listings * 100) }}</div>
        {% endif %}
    </a>
    <a href="/prices" class="stat-card">
        <div class="stat-label">Price Records</div>
        <div class="stat-value">{{ "{:,}".format(stats.total_prices) }}</div>
    </a>
</div>

<div class="grid-2col">
    <div class="card">
        <div class="card-title">Data Completeness</div>
        {% for item in completeness %}
        <div class="progress-item">
            <div class="progress-label">
                <span class="progress-label-name">{{ item.field|capitalize }}</span>
                <span class="progress-label-value">{{ item.pct }}%</span>
            </div>
            <div class="progress-track">
                <div class="progress-fill" style="width: {{ item.pct }}%"></div>
            </div>
        </div>
        {% endfor %}
    </div>

    <div class="card">
        <div class="card-title">Recent Runs</div>
        <table class="data-table">
            <thead>
                <tr>
                    <th>Shop</th>
                    <th>Phase</th>
                    <th>Status</th>
                    <th class="text-right">Added</th>
                    <th class="text-right">Updated</th>
                    <th class="text-right">Time</th>
                </tr>
            </thead>
            <tbody>
                {% for run in recent_runs %}
                <tr>
                    <td><a href="/runs/{{ run.id }}">{{ run.shop.name if run.shop else '-' }}</a></td>
                    <td>{{ run.phase }}</td>
                    <td><span class="badge badge-{{ run.status }}">{{ run.status }}</span></td>
                    <td class="text-right">{{ run.items_added }}</td>
                    <td class="text-right">{{ run.items_updated }}</td>
                    <td class="text-right text-muted">
                        {% if run.finished_at and run.started_at %}
                            {% set delta = (run.finished_at - run.started_at).total_seconds() %}
                            {{ "%dm"|format(delta // 60) if delta >= 60 else "%ds"|format(delta|int) }}
                        {% elif run.status == 'running' %}
                            ...
                        {% else %}
                            -
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<div class="card">
    <div class="card-title">Validation Issues</div>
    {% if validation %}
    <div class="validation-inline">
        {% for v in validation %}
        <a href="/validation/{{ v.issue_type }}" class="validation-inline-item" style="text-decoration: none; color: inherit;">
            <span class="badge badge-warning">{{ v.count }}</span>
            <span>{{ v.issue_type }}</span>
        </a>
        {% endfor %}
    </div>
    {% else %}
    <span class="text-muted" style="font-size: 0.7rem;">No issues</span>
    {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 4: Verify overview renders**

Run: `cd /Users/evaldas/Projects/book-scraper/.claude/worktrees/strange-mayer && uv run python -c "from book_scraper.dashboard.app import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/routes/overview.py book_scraper/dashboard/queries.py book_scraper/dashboard/templates/overview.html
git commit -m "feat: restyle overview page with data completeness bars"
```

---

### Task 3: Restyle Listings, Listing Detail, and macros

**Files:**
- Modify: `book_scraper/dashboard/templates/listings.html`
- Modify: `book_scraper/dashboard/templates/listing_detail.html`
- Modify: `book_scraper/dashboard/templates/macros.html`

- [ ] **Step 1: Update macros.html — keep sort_header as-is**

The existing `sort_header` macro works fine with the new CSS since `.data-table th a` and `.sort-arrow` are styled in dashboard.css. No changes needed to macros.html.

- [ ] **Step 2: Restyle listings.html**

Replace `book_scraper/dashboard/templates/listings.html` with:

```html
{% extends "base.html" %}
{% from "macros.html" import sort_header %}
{% block title %}Listings{% endblock %}
{% block content %}
<h1 class="page-title">Listings</h1>

<form method="get" action="/listings" class="filter-bar" style="display: block;">
    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.5rem; margin-bottom: 0.5rem;">
        <input type="search" name="q" placeholder="Search by title..." value="{{ query }}" style="font-size: 0.7rem; padding: 0.375rem 0.5rem;">
        <input type="search" name="author" placeholder="Filter by author..." value="{{ author_filter }}" style="font-size: 0.7rem; padding: 0.375rem 0.5rem;">
        <input type="search" name="publisher" placeholder="Filter by publisher..." value="{{ publisher_filter }}" style="font-size: 0.7rem; padding: 0.375rem 0.5rem;">
    </div>
    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 0.5rem; margin-bottom: 0.5rem;">
        <select name="category" style="font-size: 0.7rem; padding: 0.375rem 0.5rem;">
            <option value="">All categories</option>
            {% for cat in categories %}
            <option value="{{ cat }}" {{ 'selected' if category == cat else '' }}>{{ cat }}</option>
            {% endfor %}
        </select>
        <select name="format" style="font-size: 0.7rem; padding: 0.375rem 0.5rem;">
            <option value="">All formats</option>
            <option value="none" {{ 'selected' if format_filter == 'none' else '' }}>Missing format</option>
            {% for fmt in formats %}
            <option value="{{ fmt }}" {{ 'selected' if format_filter == fmt else '' }}>{{ fmt }}</option>
            {% endfor %}
        </select>
        <select name="missing" style="font-size: 0.7rem; padding: 0.375rem 0.5rem;">
            <option value="">No missing filter</option>
            <option value="any" {{ 'selected' if missing == 'any' else '' }}>Any field missing</option>
            <option value="author" {{ 'selected' if missing == 'author' else '' }}>Missing author</option>
            <option value="isbn" {{ 'selected' if missing == 'isbn' else '' }}>Missing ISBN</option>
            <option value="year" {{ 'selected' if missing == 'year' else '' }}>Missing year</option>
            <option value="publisher" {{ 'selected' if missing == 'publisher' else '' }}>Missing publisher</option>
            <option value="format" {{ 'selected' if missing == 'format' else '' }}>Missing format</option>
        </select>
        <select name="active" style="font-size: 0.7rem; padding: 0.375rem 0.5rem;">
            <option value="">All statuses</option>
            <option value="true" {{ 'selected' if active_filter == 'true' else '' }}>Active</option>
            <option value="false" {{ 'selected' if active_filter == 'false' else '' }}>Not Active</option>
        </select>
    </div>
    {% if shop_filter %}<input type="hidden" name="shop" value="{{ shop_filter }}">{% endif %}
    {% if has_isbn %}<input type="hidden" name="has_isbn" value="true">{% endif %}
    <button type="submit" style="font-size: 0.7rem; padding: 0.375rem 1rem;">Filter</button>
</form>

{% set filter_params = "q=" ~ query|urlencode ~ "&author=" ~ author_filter|urlencode ~ "&publisher=" ~ publisher_filter|urlencode ~ "&category=" ~ category|urlencode ~ "&format=" ~ format_filter|urlencode ~ "&missing=" ~ missing|urlencode ~ "&active=" ~ active_filter|urlencode ~ "&shop=" ~ shop_filter|urlencode ~ ("&has_isbn=true" if has_isbn else "") %}

{% if shop_filter or has_isbn or active_filter %}
<div style="margin-bottom: 0.75rem;">
    {% if shop_filter %}
    <span class="filter-badge">Shop: {{ shop_filter }} <a href="/listings?{{ filter_params|replace('&shop=' ~ shop_filter|urlencode, '') }}">✕</a></span>
    {% endif %}
    {% if has_isbn %}
    <span class="filter-badge">Has ISBN <a href="/listings?{{ filter_params|replace('&has_isbn=true', '') }}">✕</a></span>
    {% endif %}
    {% if active_filter %}
    <span class="filter-badge">{{ 'Active' if active_filter == 'true' else 'Not Active' }} <a href="/listings?{{ filter_params|replace('&active=' ~ active_filter|urlencode, '') }}">✕</a></span>
    {% endif %}
</div>
{% endif %}

<div class="results-count"><strong>{{ "{:,}".format(total) }}</strong> results{% if author_filter %} for author "{{ author_filter }}"{% endif %}{% if publisher_filter %} for publisher "{{ publisher_filter }}"{% endif %}</div>

{% if listings %}
<div class="card" style="padding: 0; overflow: hidden;">
<table class="data-table">
    <thead>
        <tr>
            <th>{{ sort_header('id', 'ID', sort, order, filter_params) }}</th>
            <th>{{ sort_header('title', 'Title', sort, order, filter_params) }}</th>
            <th>{{ sort_header('author', 'Author', sort, order, filter_params) }}</th>
            <th>{{ sort_header('isbn', 'ISBN', sort, order, filter_params) }}</th>
            <th>Format</th>
            <th>{{ sort_header('price', 'Price', sort, order, filter_params) }}</th>
            <th>Original</th>
            <th>{{ sort_header('year', 'Year', sort, order, filter_params) }}</th>
            <th>{{ sort_header('is_active', 'Active', sort, order, filter_params) }}</th>
        </tr>
    </thead>
    <tbody>
        {% for l in listings %}
        <tr>
            <td>{{ l.id }}</td>
            <td class="cell-truncate"><a href="/listings/{{ l.id }}">{{ l.title[:60] }}{{ '...' if l.title|length > 60 else '' }}</a></td>
            <td>
                {% if l.author %}
                <a href="/listings?author={{ l.author|urlencode }}">{{ l.author[:30] }}{{ '...' if l.author|length > 30 else '' }}</a>
                {% else %}<span class="text-muted">-</span>{% endif %}
            </td>
            <td>
                {% if l.isbn %}
                <a href="/listings?has_isbn=true&q={{ l.isbn|urlencode }}">{{ l.isbn }}</a>
                {% else %}<span class="text-muted">-</span>{% endif %}
            </td>
            <td>{{ l.format or '-' }}</td>
            <td class="text-right">{{ l.price or '-' }}</td>
            <td class="text-right">{{ l.price_original or '-' }}</td>
            <td>{{ l.year or '-' }}</td>
            <td>{{ 'Yes' if l.is_active else 'No' }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>

{% if total_pages > 1 %}
<div class="pagination">
    {% if page > 1 %}
    <a href="/listings?page={{ page - 1 }}&{{ filter_params }}&sort={{ sort }}&order={{ order }}" class="page-nav">← Previous</a>
    {% else %}
    <span class="page-disabled">← Previous</span>
    {% endif %}
    <span class="page-current">{{ page }}</span>
    <span class="text-muted">of {{ total_pages }}</span>
    {% if page < total_pages %}
    <a href="/listings?page={{ page + 1 }}&{{ filter_params }}&sort={{ sort }}&order={{ order }}" class="page-nav">Next →</a>
    {% else %}
    <span class="page-disabled">Next →</span>
    {% endif %}
</div>
{% endif %}

{% else %}
<p class="text-muted">No listings found.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Restyle listing_detail.html**

Replace `book_scraper/dashboard/templates/listing_detail.html` with:

```html
{% extends "base.html" %}
{% block title %}{{ listing.title }}{% endblock %}
{% block content %}
<h1 class="page-title">
    {{ listing.title }}
    {% if listing.is_active %}
    <span class="badge badge-completed">Active</span>
    {% else %}
    <span class="badge badge-failed">Inactive</span>
    {% endif %}
    {% if listing.in_stock %}
    <span class="badge badge-completed">In Stock</span>
    {% elif listing.in_stock is not none %}
    <span class="badge badge-failed">Out of Stock</span>
    {% endif %}
</h1>

<div style="margin: 0.75rem 0;">
    <button hx-post="/shops/{{ listing.shop.name }}/scrape-url?url={{ listing.url }}" hx-target="#scrape-result" hx-swap="innerHTML" style="font-size: 0.7rem;">Re-scrape this listing</button>
    <span id="scrape-result"></span>
</div>

<div class="card">
    <table class="data-table">
        <tbody>
            <tr><td><strong>Author</strong></td><td>
                {% if listing.author %}<a href="/listings?author={{ listing.author|urlencode }}">{{ listing.author }}</a>
                {% else %}<a href="/listings?missing=author" class="text-muted">-</a>{% endif %}
            </td></tr>
            <tr><td><strong>Publisher</strong></td><td>
                {% if listing.publisher %}<a href="/listings?publisher={{ listing.publisher|urlencode }}">{{ listing.publisher }}</a>
                {% else %}<a href="/listings?missing=publisher" class="text-muted">-</a>{% endif %}
            </td></tr>
            <tr><td><strong>ISBN</strong></td><td>
                {% if listing.isbn %}{{ listing.isbn }}
                {% else %}<a href="/listings?missing=isbn" class="text-muted">-</a>{% endif %}
            </td></tr>
            <tr><td><strong>Year</strong></td><td>
                {% if listing.year %}{{ listing.year }}
                {% else %}<a href="/listings?missing=year" class="text-muted">-</a>{% endif %}
            </td></tr>
            <tr><td><strong>Format</strong></td><td>
                {% if listing.format %}<a href="/listings?format={{ listing.format|urlencode }}">{{ listing.format }}</a>
                {% else %}<a href="/listings?missing=format" class="text-muted">-</a>{% endif %}
            </td></tr>
            <tr><td><strong>Price</strong></td><td>{{ listing.price or '-' }}</td></tr>
            <tr><td><strong>Original Price</strong></td><td>{{ listing.price_original or '-' }}</td></tr>
            <tr><td><strong>URL</strong></td><td><a href="{{ listing.url }}" target="_blank" rel="noopener">{{ listing.url[:80] }}{{ '...' if listing.url|length > 80 else '' }}</a></td></tr>
            <tr><td><strong>First Seen</strong></td><td>{{ listing.first_seen_at.strftime('%Y-%m-%d %H:%M') if listing.first_seen_at else '-' }}</td></tr>
            <tr><td><strong>Last Seen</strong></td><td>{{ listing.last_seen_at.strftime('%Y-%m-%d %H:%M') if listing.last_seen_at else '-' }}</td></tr>
        </tbody>
    </table>
</div>

{% if listing.description %}
<div class="card">
    <div class="card-title">Description</div>
    <p style="font-size: 0.75rem;">{{ listing.description }}</p>
</div>
{% endif %}

{% if listing.categories %}
<div class="card">
    <div class="card-title">Categories</div>
    <ul style="font-size: 0.75rem; margin: 0; padding-left: 1.25rem;">
        {% for cat in listing.categories[:-1] %}
        <li><a href="/listings?category={{ cat|urlencode }}">{{ cat }}</a></li>
        {% endfor %}
    </ul>
</div>
{% endif %}

{% if listing.properties %}
<div class="card">
    <div class="card-title">Properties</div>
    <table class="data-table">
        <thead><tr><th>Key</th><th>Value</th></tr></thead>
        <tbody>
            {% for key, value in listing.properties.items() %}
            <tr><td>{{ key }}</td><td>{{ value }}</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

<div class="card">
    <div class="card-title">Price History</div>
    <canvas id="priceChart" height="80"></canvas>
</div>

{% if prices %}
<div class="card" style="padding: 0; overflow: hidden;">
    <table class="data-table">
        <thead>
            <tr><th>Date</th><th class="text-right">Price</th><th class="text-right">Original</th><th class="text-right">Discount</th></tr>
        </thead>
        <tbody>
            {% for p in prices %}
            <tr>
                <td class="text-muted">{{ p.scraped_at.strftime('%Y-%m-%d %H:%M') if p.scraped_at else '-' }}</td>
                <td class="text-right">{{ p.price or '-' }}</td>
                <td class="text-right">{{ p.price_original or '-' }}</td>
                <td class="text-right">{{ '%.0f%%'|format(p.discount_pct|float) if p.discount_pct else '-' }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% else %}
<p class="text-muted" style="font-size: 0.75rem;">No price history recorded.</p>
{% endif %}

{% if changes %}
<div class="card" style="padding: 0; overflow: hidden;">
    <div class="card-title" style="padding: 1rem 1rem 0;">Change History</div>
    <table class="data-table">
        <thead>
            <tr><th>Date</th><th>Field</th><th>Old Value</th><th>New Value</th><th>Run</th></tr>
        </thead>
        <tbody>
            {% for c in changes %}
            <tr>
                <td class="text-muted">{{ c.changed_at.strftime('%Y-%m-%d %H:%M') }}</td>
                <td>{{ c.field }}</td>
                <td style="color: var(--price-increase);">{{ c.old_value or '-' }}</td>
                <td style="color: var(--price-decrease);">{{ c.new_value or '-' }}</td>
                <td>{% if c.scrape_run_id %}<a href="/runs/{{ c.scrape_run_id }}">Run #{{ c.scrape_run_id }}</a>{% else %}-{% endif %}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% else %}
<p class="text-muted" style="font-size: 0.75rem;">No changes recorded yet.</p>
{% endif %}

<script>
fetch('/api/prices/{{ listing.id }}/chart')
    .then(r => r.json())
    .then(data => {
        const style = getComputedStyle(document.documentElement);
        const priceColor = style.getPropertyValue('--chart-price').trim();
        const originalColor = style.getPropertyValue('--chart-original').trim();
        const ctx = document.getElementById('priceChart').getContext('2d');
        const datasets = [{
            label: 'Price',
            data: data.prices,
            borderColor: priceColor,
            tension: 0.1,
            fill: false
        }];
        if (data.original_prices.some(p => p !== null)) {
            datasets.push({
                label: 'Original Price',
                data: data.original_prices,
                borderColor: originalColor,
                borderDash: [5, 5],
                tension: 0.1,
                fill: false
            });
        }
        new Chart(ctx, {
            type: 'line',
            data: { labels: data.labels.map(l => l.split('T')[0]), datasets: datasets },
            options: { responsive: true, scales: { y: { beginAtZero: false } } }
        });
    });
</script>
{% endblock %}
```

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/templates/listings.html book_scraper/dashboard/templates/listing_detail.html
git commit -m "feat: restyle listings and listing detail pages"
```

---

### Task 4: Add Discovered URLs page

**Files:**
- Create: `book_scraper/dashboard/routes/urls.py`
- Create: `book_scraper/dashboard/templates/discovered_urls.html`
- Modify: `book_scraper/dashboard/queries.py`
- Modify: `book_scraper/dashboard/app.py`

- [ ] **Step 1: Add discovered URL queries to queries.py**

Add to the end of `book_scraper/dashboard/queries.py`:

```python
DISCOVERED_URL_SORT_COLUMNS = {
    "url": DiscoveredUrl.url,
    "fails": DiscoveredUrl.fail_count,
    "discovered": DiscoveredUrl.discovered_at,
}


def get_discovered_urls_stats(session: Session, shop_id: int | None = None) -> dict:
    """Get stats for discovered URLs page."""
    base = session.query(DiscoveredUrl)
    if shop_id:
        base = base.filter(DiscoveredUrl.shop_id == shop_id)

    total = base.count()

    # Count URLs that have a matching listing
    in_listings = (
        base.join(Listing, (Listing.shop_id == DiscoveredUrl.shop_id) & (Listing.url == DiscoveredUrl.url))
        .count()
    )
    not_in_listings = total - in_listings

    failed = base.filter(DiscoveredUrl.fail_count >= 3).count()

    return {
        "total": total,
        "in_listings": in_listings,
        "not_in_listings": not_in_listings,
        "failed": failed,
    }


def get_discovered_urls_page(
    session: Session,
    page: int = 1,
    per_page: int = 50,
    shop_id: int | None = None,
    source: str = "",
    status: str = "",
    search: str = "",
    sort_by: str = "discovered",
    sort_order: str = "desc",
) -> tuple[list, int]:
    """Return paginated discovered URLs with filters."""
    query = session.query(DiscoveredUrl).options(joinedload(DiscoveredUrl.shop))

    if shop_id:
        query = query.filter(DiscoveredUrl.shop_id == shop_id)
    if source:
        query = query.filter(DiscoveredUrl.source == source)
    if search:
        query = query.filter(DiscoveredUrl.url.ilike(f"%{search}%"))

    # Status filters
    if status == "not_in_listings":
        # LEFT JOIN with listings, keep only unmatched
        query = query.outerjoin(
            Listing,
            (Listing.shop_id == DiscoveredUrl.shop_id) & (Listing.url == DiscoveredUrl.url),
        ).filter(Listing.id.is_(None))
    elif status == "failed":
        query = query.filter(DiscoveredUrl.fail_count >= 3)
    elif status in ("unknown", "product", "non_product"):
        query = query.filter(DiscoveredUrl.url_type == status)

    total = query.count()

    order_col = DISCOVERED_URL_SORT_COLUMNS.get(sort_by, DiscoveredUrl.discovered_at)
    if sort_order == "asc":
        query = query.order_by(order_col.asc().nulls_last())
    else:
        query = query.order_by(order_col.desc().nulls_last())

    urls = query.offset((page - 1) * per_page).limit(per_page).all()
    return urls, total
```

- [ ] **Step 2: Verify DiscoveredUrl has a shop relationship**

Check `book_scraper/db/models.py` for the DiscoveredUrl model. If it lacks a `shop` relationship, we need to add one. The `joinedload(DiscoveredUrl.shop)` in the query above requires it.

Run: `grep -A 5 "class DiscoveredUrl" book_scraper/db/models.py`

If no `shop` relationship exists, add to the DiscoveredUrl model:
```python
    shop = relationship("Shop")
```

- [ ] **Step 3: Create the urls route**

Create `book_scraper/dashboard/routes/urls.py`:

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_all_shops,
    get_discovered_urls_page,
    get_discovered_urls_stats,
    get_shop_by_name,
)

router = APIRouter()


@router.get("/urls")
def discovered_urls_page(
    request: Request,
    page: int = 1,
    q: str = "",
    shop: str = "",
    source: str = "",
    status: str = "",
    sort: str = "discovered",
    order: str = "desc",
    session: Session = Depends(get_db),
):
    shop_obj = get_shop_by_name(session, shop) if shop else None
    shop_id = shop_obj.id if shop_obj else None

    stats = get_discovered_urls_stats(session, shop_id=shop_id)
    urls, total = get_discovered_urls_page(
        session,
        page=page,
        shop_id=shop_id,
        source=source,
        status=status,
        search=q,
        sort_by=sort,
        sort_order=order,
    )
    shops = get_all_shops(session)
    total_pages = (total + 49) // 50

    return templates.TemplateResponse(
        request,
        "discovered_urls.html",
        {
            "active_page": "urls",
            "urls": urls,
            "stats": stats,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "query": q,
            "shop_filter": shop,
            "source_filter": source,
            "status_filter": status,
            "sort": sort,
            "order": order,
            "shops": shops,
        },
    )
```

- [ ] **Step 4: Create discovered_urls.html template**

Create `book_scraper/dashboard/templates/discovered_urls.html`:

```html
{% extends "base.html" %}
{% from "macros.html" import sort_header %}
{% block title %}Discovered URLs{% endblock %}
{% block content %}
<h1 class="page-title">Discovered URLs</h1>

<div class="stat-grid">
    <a href="/urls" class="stat-card">
        <div class="stat-label">Total URLs</div>
        <div class="stat-value">{{ "{:,}".format(stats.total) }}</div>
    </a>
    <a href="/urls" class="stat-card">
        <div class="stat-label">In Listings</div>
        <div class="stat-value">{{ "{:,}".format(stats.in_listings) }}</div>
        {% if stats.total > 0 %}
        <div class="stat-sub">{{ "%.1f%%"|format(stats.in_listings / stats.total * 100) }}</div>
        {% endif %}
    </a>
    <a href="/urls?status=not_in_listings" class="stat-card">
        <div class="stat-label">Not in Listings</div>
        <div class="stat-value stat-value--warning">{{ "{:,}".format(stats.not_in_listings) }}</div>
        {% if stats.total > 0 %}
        <div class="stat-sub">{{ "%.1f%%"|format(stats.not_in_listings / stats.total * 100) }}</div>
        {% endif %}
    </a>
    <a href="/urls?status=failed" class="stat-card">
        <div class="stat-label">Failed (3+)</div>
        <div class="stat-value stat-value--error">{{ "{:,}".format(stats.failed) }}</div>
    </a>
</div>

{% set filter_params = "q=" ~ query|urlencode ~ "&shop=" ~ shop_filter|urlencode ~ "&source=" ~ source_filter|urlencode ~ "&status=" ~ status_filter|urlencode %}

<div class="filter-bar">
    <form method="get" action="/urls" style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; width: 100%; margin: 0;">
        <div class="filter-group">
            <span class="filter-label">Shop:</span>
            <select name="shop" style="font-size: 0.7rem; padding: 0.25rem 0.5rem;">
                <option value="">All shops</option>
                {% for s in shops %}
                <option value="{{ s.name }}" {{ 'selected' if shop_filter == s.name else '' }}>{{ s.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="filter-group">
            <span class="filter-label">Source:</span>
            <select name="source" style="font-size: 0.7rem; padding: 0.25rem 0.5rem;">
                <option value="">All sources</option>
                <option value="sitemap" {{ 'selected' if source_filter == 'sitemap' else '' }}>sitemap</option>
                <option value="category" {{ 'selected' if source_filter == 'category' else '' }}>category</option>
                <option value="full_crawl" {{ 'selected' if source_filter == 'full_crawl' else '' }}>full_crawl</option>
            </select>
        </div>
        <div class="filter-group">
            <span class="filter-label">Status:</span>
            <select name="status" style="font-size: 0.7rem; padding: 0.25rem 0.5rem;">
                <option value="">All</option>
                <option value="not_in_listings" {{ 'selected' if status_filter == 'not_in_listings' else '' }}>Not in listings</option>
                <option value="failed" {{ 'selected' if status_filter == 'failed' else '' }}>Failed</option>
                <option value="unknown" {{ 'selected' if status_filter == 'unknown' else '' }}>Type: unknown</option>
                <option value="product" {{ 'selected' if status_filter == 'product' else '' }}>Type: product</option>
                <option value="non_product" {{ 'selected' if status_filter == 'non_product' else '' }}>Type: non_product</option>
            </select>
        </div>
        <div class="filter-group">
            <input type="search" name="q" placeholder="Search URL..." value="{{ query }}" style="font-size: 0.7rem; padding: 0.25rem 0.5rem; width: 200px;">
        </div>
        <button type="submit" style="font-size: 0.65rem; padding: 0.3rem 0.75rem;">Filter</button>
    </form>
</div>

{% if status_filter %}
<div style="margin-bottom: 0.75rem;">
    <span class="filter-badge">{{ status_filter|replace('_', ' ')|capitalize }} <a href="/urls?q={{ query|urlencode }}&shop={{ shop_filter|urlencode }}&source={{ source_filter|urlencode }}">✕</a></span>
</div>
{% endif %}

<div class="results-count">Showing {{ "{:,}".format(total) }} URLs</div>

{% if urls %}
<div class="card" style="padding: 0; overflow: hidden;">
<table class="data-table">
    <thead>
        <tr>
            <th>{{ sort_header('url', 'URL', sort, order, filter_params) }}</th>
            <th>Shop</th>
            <th>Source</th>
            <th>Type</th>
            <th class="text-right">{{ sort_header('fails', 'Fails', sort, order, filter_params) }}</th>
            <th>HTTP</th>
            <th>{{ sort_header('discovered', 'Discovered', sort, order, filter_params) }}</th>
        </tr>
    </thead>
    <tbody>
        {% for u in urls %}
        <tr>
            <td class="cell-truncate"><a href="{{ u.url }}" target="_blank" rel="noopener">{{ u.url|replace('https://', '') }}</a></td>
            <td>{{ u.shop.name if u.shop else '-' }}</td>
            <td class="text-muted">{{ u.source or '-' }}</td>
            <td><span class="badge badge-{{ u.url_type or 'unknown' }}">{{ u.url_type or 'unknown' }}</span></td>
            <td class="text-right">{{ u.fail_count }}</td>
            <td>{% if u.last_http_status and u.last_http_status >= 400 %}<span class="http-error">{{ u.last_http_status }}</span>{% elif u.last_http_status %}{{ u.last_http_status }}{% else %}<span class="text-muted">—</span>{% endif %}</td>
            <td class="text-muted">{{ u.discovered_at.strftime('%b %d') if u.discovered_at else '-' }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>

{% if total_pages > 1 %}
<div class="pagination">
    {% if page > 1 %}
    <a href="/urls?page={{ page - 1 }}&{{ filter_params }}&sort={{ sort }}&order={{ order }}" class="page-nav">← Previous</a>
    {% else %}
    <span class="page-disabled">← Previous</span>
    {% endif %}
    <span class="page-current">{{ page }}</span>
    <span class="text-muted">of {{ total_pages }}</span>
    {% if page < total_pages %}
    <a href="/urls?page={{ page + 1 }}&{{ filter_params }}&sort={{ sort }}&order={{ order }}" class="page-nav">Next →</a>
    {% else %}
    <span class="page-disabled">Next →</span>
    {% endif %}
</div>
{% endif %}

{% else %}
<p class="text-muted" style="font-size: 0.75rem;">No discovered URLs found.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Register the urls router in app.py**

Add to the imports in `book_scraper/dashboard/app.py`:

```python
from book_scraper.dashboard.routes import (
    listings,
    overview,
    prices,
    runs,
    shops,
    urls,
    validation,
)
```

And add after the other `include_router` calls:

```python
app.include_router(urls.router)
```

- [ ] **Step 6: Verify the app starts**

Run: `cd /Users/evaldas/Projects/book-scraper/.claude/worktrees/strange-mayer && uv run python -c "from book_scraper.dashboard.app import app; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add book_scraper/dashboard/routes/urls.py book_scraper/dashboard/templates/discovered_urls.html book_scraper/dashboard/queries.py book_scraper/dashboard/app.py
git commit -m "feat: add discovered URLs page with not-in-listings filter"
```

---

### Task 5: Restyle Shops pages

**Files:**
- Modify: `book_scraper/dashboard/templates/shops.html`
- Modify: `book_scraper/dashboard/templates/shop_detail.html`

- [ ] **Step 1: Restyle shops.html**

Replace `book_scraper/dashboard/templates/shops.html` with:

```html
{% extends "base.html" %}
{% block title %}Shops{% endblock %}
{% block content %}
<h1 class="page-title">Shops</h1>

{% for item in shop_data %}
<div class="card">
    <div class="card-title"><a href="/shops/{{ item.shop.name }}">{{ item.shop.name }}</a> <span class="text-muted" style="font-weight: normal;">{{ item.shop.base_url }}</span></div>
    <div class="stat-grid">
        <a href="/urls?shop={{ item.shop.name }}" class="stat-card">
            <div class="stat-label">Discovered URLs</div>
            <div class="stat-value">{{ "{:,}".format(item.stats.discovered_urls) }}</div>
        </a>
        <a href="/listings?shop={{ item.shop.name }}" class="stat-card">
            <div class="stat-label">Listings</div>
            <div class="stat-value">{{ "{:,}".format(item.stats.listings) }}</div>
        </a>
        <a href="/listings?shop={{ item.shop.name }}&active=true" class="stat-card">
            <div class="stat-label">Active</div>
            <div class="stat-value">{{ "{:,}".format(item.stats.active) }}</div>
        </a>
        <a href="/prices?shop={{ item.shop.name }}" class="stat-card">
            <div class="stat-label">Price Records</div>
            <div class="stat-value">{{ "{:,}".format(item.stats.prices) }}</div>
        </a>
    </div>
</div>
{% endfor %}

{% if not shop_data %}
<p class="text-muted">No shops configured yet. Run a discover command to register a shop.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Restyle shop_detail.html**

Replace `book_scraper/dashboard/templates/shop_detail.html` with:

```html
{% extends "base.html" %}
{% block title %}{{ shop.name }}{% endblock %}
{% block content %}
<h1 class="page-title">{{ shop.name }} <span class="text-muted" style="font-weight: normal; font-size: 0.8rem;">{{ shop.base_url }}</span></h1>

<div class="stat-grid">
    <a href="/urls?shop={{ shop.name }}" class="stat-card">
        <div class="stat-label">Discovered URLs</div>
        <div class="stat-value">{{ "{:,}".format(stats.discovered_urls) }}</div>
    </a>
    <a href="/listings?shop={{ shop.name }}" class="stat-card">
        <div class="stat-label">Listings</div>
        <div class="stat-value">{{ "{:,}".format(stats.listings) }}</div>
    </a>
    <a href="/listings?shop={{ shop.name }}&active=true" class="stat-card">
        <div class="stat-label">Active</div>
        <div class="stat-value">{{ "{:,}".format(stats.active) }}</div>
    </a>
    <div class="stat-card">
        <div class="stat-label">Price Records</div>
        <div class="stat-value">{{ "{:,}".format(stats.prices) }}</div>
    </div>
</div>

{% if field_stats and field_stats.total > 0 %}
<div class="card">
    <div class="card-title">Data Completeness</div>
    <table class="data-table">
        <thead>
            <tr>
                <th>Field</th>
                <th class="text-right">Present</th>
                <th class="text-right">Missing</th>
                <th class="text-right">% Complete</th>
            </tr>
        </thead>
        <tbody>
            {% for field_name, counts in field_stats.fields.items() %}
            <tr>
                <td>{{ field_name }}</td>
                <td class="text-right">{{ counts.present }}</td>
                <td class="text-right">
                    {% if counts.missing > 0 %}
                    <a href="/listings?shop={{ shop.name }}&missing={{ field_name }}">{{ counts.missing }}</a>
                    {% else %}0{% endif %}
                </td>
                <td class="text-right">{{ '%.1f%%'|format(counts.present / field_stats.total * 100) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

<div class="card">
    <div class="card-title">Run Commands</div>
    <div class="actions">
        <button hx-post="/shops/{{ shop.name }}/run?phase=discover_sitemap" hx-target="#run-result" hx-swap="innerHTML" style="font-size: 0.7rem;">Discover (Sitemap)</button>
        <button hx-post="/shops/{{ shop.name }}/run?phase=discover_categories" hx-target="#run-result" hx-swap="innerHTML" style="font-size: 0.7rem;">Discover (Categories)</button>
        <button hx-post="/shops/{{ shop.name }}/run?phase=scan" hx-target="#run-result" hx-swap="innerHTML" style="font-size: 0.7rem;">Scan</button>
        <button class="secondary" hx-post="/shops/{{ shop.name }}/run?phase=rescrape" hx-target="#run-result" hx-swap="innerHTML" style="font-size: 0.7rem;">Rescrape All</button>
    </div>
    <div id="run-result" style="margin-top: 0.5rem;"></div>
    <hr>
    <div class="card-title" style="margin-top: 0.5rem;">Scrape Single URL</div>
    <form hx-post="/shops/{{ shop.name }}/scrape-url" hx-target="#run-result" hx-swap="innerHTML" style="display: flex; gap: 0.5rem;">
        <input type="text" name="url" placeholder="https://{{ shop.base_url|replace('https://', '') }}/product-url" style="flex: 1; font-size: 0.7rem;">
        <button type="submit" style="font-size: 0.7rem;">Scrape</button>
    </form>
</div>

<div class="card-title" style="margin-bottom: 0.5rem;">Recent Runs</div>
<div class="card" style="padding: 0; overflow: hidden;" hx-get="/shops/{{ shop.name }}" hx-trigger="every 10s" hx-select=".runs-table" hx-target=".runs-table" hx-swap="outerHTML">
<table class="data-table runs-table">
    <thead>
        <tr>
            <th>ID</th>
            <th>Phase</th>
            <th>Status</th>
            <th>Health</th>
            <th>Started</th>
            <th>Duration</th>
            <th>Progress</th>
            <th class="text-right">Added</th>
            <th class="text-right">Updated</th>
            <th class="text-right">Errors</th>
        </tr>
    </thead>
    <tbody>
        {% for run in runs %}
        <tr>
            <td><a href="/runs/{{ run.id }}">{{ run.id }}</a></td>
            <td>{{ run.phase }}</td>
            <td><span class="badge badge-{{ run.status }}">{{ run.status }}</span></td>
            <td>
                {% set health = run_health.get(run.id, '') %}
                {% if health == 'healthy' %}<span class="health-healthy">&#9679; active</span>
                {% elif health == 'stale' %}<span class="health-stale">&#9679; stale</span>
                {% elif health == 'dead' %}<span class="health-dead">&#9679; dead</span>
                {% endif %}
            </td>
            <td class="text-muted">{{ run.started_at.strftime('%Y-%m-%d %H:%M') if run.started_at else '-' }}</td>
            <td class="text-muted">
                {% if run.finished_at and run.started_at %}{{ (run.finished_at - run.started_at) }}
                {% elif run.status == 'running' %}running...
                {% else %}-{% endif %}
            </td>
            <td>
                {% if run.urls_total %}{{ run.urls_processed }}/{{ run.urls_total }}
                {% elif run.urls_processed %}{{ run.urls_processed }}
                {% else %}-{% endif %}
            </td>
            <td class="text-right">{{ run.items_added }}</td>
            <td class="text-right">{{ run.items_updated }}</td>
            <td class="text-right">{{ run.error_count }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/templates/shops.html book_scraper/dashboard/templates/shop_detail.html
git commit -m "feat: restyle shops and shop detail pages"
```

---

### Task 6: Restyle Runs pages

**Files:**
- Modify: `book_scraper/dashboard/templates/runs.html`
- Modify: `book_scraper/dashboard/templates/run_detail.html`

- [ ] **Step 1: Restyle runs.html**

Replace `book_scraper/dashboard/templates/runs.html` with:

```html
{% extends "base.html" %}
{% block title %}Runs{% endblock %}
{% block content %}
<h1 class="page-title">Scrape Runs</h1>

<p class="text-muted" style="font-size: 0.75rem;">To start a scrape, go to <a href="/shops">Shops</a> and use the run commands there.</p>

<div class="card" style="padding: 0; overflow: hidden;" hx-get="/runs" hx-trigger="every 10s" hx-select=".runs-table" hx-target=".runs-table" hx-swap="outerHTML">
<table class="data-table runs-table">
    <thead>
        <tr>
            <th>ID</th>
            <th>Shop</th>
            <th>Phase</th>
            <th>Status</th>
            <th>Health</th>
            <th>Started</th>
            <th>Duration</th>
            <th>Progress</th>
            <th class="text-right">Added</th>
            <th class="text-right">Updated</th>
            <th class="text-right">Errors</th>
        </tr>
    </thead>
    <tbody>
        {% for run in runs %}
        <tr>
            <td><a href="/runs/{{ run.id }}">{{ run.id }}</a></td>
            <td><a href="/shops/{{ run.shop.name }}">{{ run.shop.name }}</a></td>
            <td>{{ run.phase }}</td>
            <td><span class="badge badge-{{ run.status }}">{{ run.status }}</span></td>
            <td>
                {% set health = run_health.get(run.id, '') %}
                {% if health == 'healthy' %}<span class="health-healthy" title="Heartbeat active">&#9679; active</span>
                {% elif health == 'stale' %}<span class="health-stale" title="No heartbeat for >5 min">&#9679; stale</span>
                {% elif health == 'dead' %}<span class="health-dead" title="No heartbeat for >2 hours">&#9679; dead</span>
                {% endif %}
            </td>
            <td class="text-muted">{{ run.started_at.strftime('%Y-%m-%d %H:%M') if run.started_at else '-' }}</td>
            <td class="text-muted">
                {% if run.finished_at and run.started_at %}{{ (run.finished_at - run.started_at) }}
                {% elif run.status == 'running' %}running...
                {% else %}-{% endif %}
            </td>
            <td>
                {% if run.urls_total %}{{ run.urls_processed }}/{{ run.urls_total }}
                {% elif run.urls_processed %}{{ run.urls_processed }}
                {% else %}-{% endif %}
            </td>
            <td class="text-right">{{ run.items_added }}</td>
            <td class="text-right">{{ run.items_updated }}</td>
            <td class="text-right">{{ run.error_count }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>
{% endblock %}
```

- [ ] **Step 2: Restyle run_detail.html**

Replace `book_scraper/dashboard/templates/run_detail.html` with:

```html
{% extends "base.html" %}
{% block title %}Run #{{ run.id }}{% endblock %}
{% block content %}
<h1 class="page-title">Run #{{ run.id }} <span class="badge badge-{{ run.status }}">{{ run.status }}</span></h1>

{% if run.status == 'running' %}
<div class="card">
    <div class="card-title">Live Status <span class="text-muted" style="font-weight: normal;">(refreshes every 3s)</span></div>
    <div id="live-status" hx-get="/api/runs/{{ run.id }}/status" hx-trigger="load, every 3s" hx-swap="innerHTML">
        Loading...
    </div>
    <div class="actions mt-1" id="action-result">
        <button class="secondary outline" hx-post="/runs/{{ run.id }}/kill" hx-target="#action-result" hx-swap="innerHTML" hx-confirm="Send SIGTERM to PID {{ run.pid }}?" style="font-size: 0.7rem;">Stop Scraping</button>
    </div>
</div>
{% endif %}

<div class="card">
    <div class="card-title">Run Details</div>
    <table class="data-table">
        <tbody>
            <tr><td><strong>Phase</strong></td><td>{{ run.phase }}</td></tr>
            <tr><td><strong>Status</strong></td><td><span class="badge badge-{{ run.status }}">{{ run.status }}</span></td></tr>
            <tr><td><strong>Health</strong></td><td>
                {% if health == 'healthy' %}<span class="health-healthy">&#9679; active</span>
                {% elif health == 'stale' %}<span class="health-stale">&#9679; stale</span>
                {% elif health == 'dead' %}<span class="health-dead">&#9679; dead</span>
                {% else %}-{% endif %}
            </td></tr>
            <tr><td><strong>PID</strong></td><td>{{ run.pid or '-' }}</td></tr>
            <tr><td><strong>Started</strong></td><td>{{ run.started_at.strftime('%Y-%m-%d %H:%M:%S') if run.started_at else '-' }}</td></tr>
            <tr><td><strong>Finished</strong></td><td>{{ run.finished_at.strftime('%Y-%m-%d %H:%M:%S') if run.finished_at else '-' }}</td></tr>
            <tr><td><strong>Duration</strong></td><td>
                {% if run.finished_at and run.started_at %}{{ (run.finished_at - run.started_at) }}
                {% elif run.status == 'running' %}running...
                {% else %}-{% endif %}
            </td></tr>
            <tr><td><strong>Last Heartbeat</strong></td><td>{{ run.last_heartbeat.strftime('%Y-%m-%d %H:%M:%S') if run.last_heartbeat else '-' }}</td></tr>
            <tr><td><strong>URLs</strong></td><td>{{ run.urls_processed }}{% if run.urls_total %} / {{ run.urls_total }}{% endif %}</td></tr>
            <tr><td><strong>Items Added</strong></td><td>{{ run.items_added }}</td></tr>
            <tr><td><strong>Items Updated</strong></td><td>{{ run.items_updated }}</td></tr>
            <tr><td><strong>Errors</strong></td><td>{{ run.error_count }}</td></tr>
        </tbody>
    </table>
</div>

<p class="text-muted" style="font-size: 0.75rem;">Run commands available on the <a href="/shops/{{ run.shop.name }}">{{ run.shop.name }} shop page</a>.</p>

{% if issues %}
<div class="card" style="padding: 0; overflow: hidden;">
    <div class="card-title" style="padding: 1rem 1rem 0;">Validation Issues ({{ issues|length }})</div>
    <table class="data-table">
        <thead>
            <tr><th>URL</th><th>Field</th><th>Issue</th><th>Raw Value</th></tr>
        </thead>
        <tbody>
            {% for issue in issues %}
            <tr>
                <td class="cell-truncate"><a href="{{ issue.url }}" target="_blank">{{ issue.url }}</a></td>
                <td>{{ issue.field }}</td>
                <td>{{ issue.issue }}</td>
                <td>{{ issue.raw_value or '-' }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% else %}
<p class="text-muted" style="font-size: 0.75rem;">No validation issues for this run.</p>
{% endif %}

{% if created %}
<div class="card" style="padding: 0; overflow: hidden;">
    <div class="card-title" style="padding: 1rem 1rem 0;">Created ({{ created|length }})</div>
    <table class="data-table">
        <thead><tr><th>Title</th><th>Author</th><th>ISBN</th><th class="text-right">Price</th></tr></thead>
        <tbody>
            {% for l in created %}
            <tr>
                <td><a href="/listings/{{ l.id }}">{{ l.title[:60] }}{{ '...' if l.title|length > 60 else '' }}</a></td>
                <td>{{ l.author or '-' }}</td>
                <td>{{ l.isbn or '-' }}</td>
                <td class="text-right">{{ l.price or '-' }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

{% if updated %}
<div class="card" style="padding: 0; overflow: hidden;">
    <div class="card-title" style="padding: 1rem 1rem 0;">Updated ({{ updated|length }})</div>
    <table class="data-table">
        <thead><tr><th>Title</th><th>Author</th><th>ISBN</th><th class="text-right">Price</th></tr></thead>
        <tbody>
            {% for l in updated %}
            <tr>
                <td><a href="/listings/{{ l.id }}">{{ l.title[:60] }}{{ '...' if l.title|length > 60 else '' }}</a></td>
                <td>{{ l.author or '-' }}</td>
                <td>{{ l.isbn or '-' }}</td>
                <td class="text-right">{{ l.price or '-' }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

<script>
document.body.addEventListener('htmx:beforeSwap', function(evt) {
    if (evt.detail.target.id === 'live-status' && evt.detail.xhr.status === 200) {
        try {
            const data = JSON.parse(evt.detail.xhr.responseText);
            const healthClass = data.health ? 'health-' + data.health : '';
            const healthLabel = data.health || '-';
            const hbAgo = data.heartbeat_seconds_ago !== null ? data.heartbeat_seconds_ago + 's ago' : 'never';
            const progress = data.urls_total ? `${data.urls_processed}/${data.urls_total}` : `${data.urls_processed}`;
            const elapsed = data.elapsed_seconds ? `${Math.floor(data.elapsed_seconds/60)}m ${data.elapsed_seconds%60}s` : '-';

            evt.detail.serverResponse = `
                <dl>
                    <dt>Health:</dt><dd><span class="${healthClass}">&#9679; ${healthLabel}</span></dd>
                    <dt>PID:</dt><dd>${data.pid || '-'}</dd>
                    <dt>Heartbeat:</dt><dd>${hbAgo}</dd>
                    <dt>Progress:</dt><dd>${progress}</dd>
                    <dt>Items:</dt><dd>+${data.items_added} ~${data.items_updated}</dd>
                    <dt>Errors:</dt><dd>${data.error_count}</dd>
                    <dt>Elapsed:</dt><dd>${elapsed}</dd>
                </dl>
            `;

            if (data.status !== 'running') {
                setTimeout(() => location.reload(), 1000);
            }
        } catch(e) {}
    }
});
</script>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/templates/runs.html book_scraper/dashboard/templates/run_detail.html
git commit -m "feat: restyle runs and run detail pages"
```

---

### Task 7: Restyle Prices and Validation pages

**Files:**
- Modify: `book_scraper/dashboard/templates/prices.html`
- Modify: `book_scraper/dashboard/templates/validation.html`
- Modify: `book_scraper/dashboard/templates/validation_detail.html`

- [ ] **Step 1: Restyle prices.html**

Replace `book_scraper/dashboard/templates/prices.html` with:

```html
{% extends "base.html" %}
{% block title %}Prices{% endblock %}
{% block content %}
<h1 class="page-title">Prices</h1>

<div class="filter-bar">
    <form method="get" action="/prices" role="search" style="display: flex; gap: 0.5rem; align-items: center; width: 100%; margin: 0;">
        <input type="search" name="q" placeholder="Search listings by title..." value="{{ query }}" style="flex: 1; font-size: 0.7rem; padding: 0.375rem 0.5rem;">
        <button type="submit" style="font-size: 0.7rem; padding: 0.375rem 0.75rem;">Search</button>
    </form>
</div>

{% if listings %}
<div class="card" style="padding: 0; overflow: hidden;">
    <div class="card-title" style="padding: 1rem 1rem 0;">Search Results</div>
    <table class="data-table">
        <thead>
            <tr><th>Title</th><th>Author</th><th class="text-right">Price</th><th class="text-right">Original</th><th>Chart</th></tr>
        </thead>
        <tbody>
            {% for l in listings %}
            <tr>
                <td><a href="/listings/{{ l.id }}">{{ l.title[:60] }}{{ '...' if l.title|length > 60 }}</a></td>
                <td>{{ l.author or '-' }}</td>
                <td class="text-right">{{ l.price or '-' }}</td>
                <td class="text-right">{{ l.price_original or '-' }}</td>
                <td><button class="outline" onclick="loadChart({{ l.id }}, '{{ l.title|e }}')" style="font-size: 0.6rem; padding: 0.2rem 0.5rem;">Show chart</button></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% elif query %}
<p class="text-muted" style="font-size: 0.75rem;">No listings found for "{{ query }}".</p>
{% endif %}

<div id="chart-container" class="card" style="display:none;">
    <div class="card-title" id="chart-title"></div>
    <canvas id="priceChart" height="80"></canvas>
</div>

<div class="card" style="padding: 0; overflow: hidden;">
    <div class="card-title" style="padding: 1rem 1rem 0;">Recent Price Changes (7 days)</div>
    {% if changes %}
    <table class="data-table">
        <thead>
            <tr><th>Title</th><th class="text-right">Previous</th><th class="text-right">New</th><th class="text-right">Change</th><th>Date</th></tr>
        </thead>
        <tbody>
            {% for c in changes %}
            <tr>
                <td><a href="/listings/{{ c.listing_id }}">{{ c.title[:60] }}{{ '...' if c.title|length > 60 }}</a></td>
                <td class="text-right">{{ c.prev_price }}</td>
                <td class="text-right">{{ c.new_price }}</td>
                <td class="text-right {{ 'price-decrease' if c.change < 0 else 'price-increase' }}">{{ '%+.2f'|format(c.change|float) }}</td>
                <td class="text-muted">{{ c.scraped_at.strftime('%Y-%m-%d %H:%M') if c.scraped_at else '-' }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p class="text-muted" style="padding: 0 1rem 1rem; font-size: 0.75rem;">No price changes in the last 7 days.</p>
    {% endif %}
</div>

<script>
let chartInstance = null;
function loadChart(listingId, title) {
    const style = getComputedStyle(document.documentElement);
    const priceColor = style.getPropertyValue('--chart-price').trim();
    const originalColor = style.getPropertyValue('--chart-original').trim();
    fetch('/api/prices/' + listingId + '/chart')
        .then(r => r.json())
        .then(data => {
            document.getElementById('chart-container').style.display = 'block';
            document.getElementById('chart-title').textContent = title;
            const ctx = document.getElementById('priceChart').getContext('2d');
            if (chartInstance) chartInstance.destroy();
            const datasets = [{
                label: 'Price',
                data: data.prices,
                borderColor: priceColor,
                tension: 0.1,
                fill: false
            }];
            if (data.original_prices.some(p => p !== null)) {
                datasets.push({
                    label: 'Original Price',
                    data: data.original_prices,
                    borderColor: originalColor,
                    borderDash: [5, 5],
                    tension: 0.1,
                    fill: false
                });
            }
            chartInstance = new Chart(ctx, {
                type: 'line',
                data: { labels: data.labels.map(l => l.split('T')[0]), datasets: datasets },
                options: { responsive: true, scales: { y: { beginAtZero: false } } }
            });
        });
}
</script>
{% endblock %}
```

- [ ] **Step 2: Restyle validation.html**

Replace `book_scraper/dashboard/templates/validation.html` with:

```html
{% extends "base.html" %}
{% block title %}Validation{% endblock %}
{% block content %}
<h1 class="page-title">Validation Issues</h1>

{% if summary %}
<div class="card" style="padding: 0; overflow: hidden;">
<table class="data-table">
    <thead>
        <tr><th>Issue Type</th><th class="text-right">Count</th></tr>
    </thead>
    <tbody>
        {% for s in summary %}
        <tr>
            <td><a href="/validation/{{ s.issue_type }}">{{ s.issue_type }}</a></td>
            <td class="text-right"><span class="badge badge-warning">{{ s.count }}</span></td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>
{% else %}
<p class="text-muted" style="font-size: 0.75rem;">No validation issues found.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Restyle validation_detail.html**

Replace `book_scraper/dashboard/templates/validation_detail.html` with:

```html
{% extends "base.html" %}
{% block title %}Validation: {{ issue_type }}{% endblock %}
{% block content %}
<h1 class="page-title">Validation: {{ issue_type }} <span class="badge badge-warning">{{ issues|length }}</span></h1>
<p style="font-size: 0.75rem;"><a href="/validation">← Back to summary</a></p>

{% if issues %}
<div class="card" style="padding: 0; overflow: hidden;">
<table class="data-table">
    <thead>
        <tr><th>ID</th><th>Listing</th><th>Field</th><th>Raw Value</th><th>Run</th></tr>
    </thead>
    <tbody>
        {% for issue in issues %}
        <tr>
            <td>{{ issue.id }}</td>
            <td>
                {% if issue.listing_id %}
                <a href="/listings/{{ issue.listing_id }}">{{ issue.listing_title[:50] }}{{ '...' if issue.listing_title|length > 50 }}</a>
                {% else %}
                <a href="{{ issue.url }}" target="_blank" class="cell-truncate" style="display: inline-block; max-width: 250px;">{{ issue.url }}</a>
                {% endif %}
            </td>
            <td>{{ issue.field }}</td>
            <td>{{ issue.raw_value or '-' }}</td>
            <td><a href="/runs/{{ issue.scrape_run_id }}">Run #{{ issue.scrape_run_id }}</a></td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>
{% else %}
<p class="text-muted" style="font-size: 0.75rem;">No issues of this type found.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/templates/prices.html book_scraper/dashboard/templates/validation.html book_scraper/dashboard/templates/validation_detail.html
git commit -m "feat: restyle prices and validation pages"
```

---

### Task 8: Run tests and verify

**Files:**
- No new files

- [ ] **Step 1: Run the full test suite**

Run: `cd /Users/evaldas/Projects/book-scraper/.claude/worktrees/strange-mayer && uv run pytest -v`

Expected: All existing tests pass. Fix any import errors from the removed inventory module.

- [ ] **Step 2: Run linting**

Run: `cd /Users/evaldas/Projects/book-scraper/.claude/worktrees/strange-mayer && uv run ruff check book_scraper/ tests/`

Fix any issues.

- [ ] **Step 3: Run type checking**

Run: `cd /Users/evaldas/Projects/book-scraper/.claude/worktrees/strange-mayer && uv run mypy book_scraper/`

Fix any type errors.

- [ ] **Step 4: Start the dashboard and visually verify**

Run: `cd /Users/evaldas/Projects/book-scraper/.claude/worktrees/strange-mayer && uv run uvicorn book_scraper.dashboard.app:app --reload --port 8000`

Check in browser:
- All 7 pages load without errors
- Theme toggle works (light ↔ dark)
- Theme persists across page reloads
- Stat cards, tables, badges, filters render correctly
- Discovered URLs page shows data with filters working
- Charts use theme-aware colors

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve test and lint issues from dashboard redesign"
```
