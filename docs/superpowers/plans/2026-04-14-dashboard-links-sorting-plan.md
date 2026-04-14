# Dashboard Links, Sorting & UI Improvements Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add clickable links to all stat values, server-side column sorting for all tables, tabs on shop detail, fix price duplicate bug, and remove the logs page.

**Architecture:** Incremental changes to existing FastAPI routes, Jinja2 templates, and SQLAlchemy queries. A reusable Jinja2 macro handles sort headers. All sorting is server-side via `sort`/`order` query params with column allowlists.

**Tech Stack:** FastAPI, Jinja2, SQLAlchemy 2.0, PostgreSQL, HTMX, PicoCSS

---

## File Map

**Modified:**
- `book_scraper/dashboard/queries.py` — new filters, sorting, price dedup, not-listed query
- `book_scraper/dashboard/routes/overview.py` — no changes needed (template-only)
- `book_scraper/dashboard/routes/listings.py` — add `active`, `has_isbn`, `shop` params
- `book_scraper/dashboard/routes/shops.py` — add not-listed route, remove scrape-single-url, add sort params
- `book_scraper/dashboard/routes/runs.py` — add sort params
- `book_scraper/dashboard/routes/prices.py` — add shop filter, sort params
- `book_scraper/dashboard/app.py` — remove logs router
- `book_scraper/dashboard/templates/base.html` — remove logs nav, add sort macro + styles
- `book_scraper/dashboard/templates/overview.html` — stat links, updated column, cell links, sort headers
- `book_scraper/dashboard/templates/shops.html` — stat links
- `book_scraper/dashboard/templates/shop_detail.html` — tabs, stat links, remove scrape-single-url, sort headers
- `book_scraper/dashboard/templates/runs.html` — run commands, cell links, sort headers
- `book_scraper/dashboard/templates/prices.html` — sort headers
- `book_scraper/dashboard/templates/listings.html` — active dropdown, sort headers, filter badges

**New:**
- `book_scraper/dashboard/templates/not_listed.html` — not-listed URLs page

**Deleted:**
- `book_scraper/dashboard/routes/logs.py`
- `book_scraper/dashboard/templates/logs.html`

---

### Task 1: Remove Logs Page

**Files:**
- Delete: `book_scraper/dashboard/routes/logs.py`
- Delete: `book_scraper/dashboard/templates/logs.html`
- Modify: `book_scraper/dashboard/app.py:1-24`
- Modify: `book_scraper/dashboard/templates/base.html:39`

- [ ] **Step 1: Delete logs route and template**

```bash
rm book_scraper/dashboard/routes/logs.py
rm book_scraper/dashboard/templates/logs.html
```

- [ ] **Step 2: Remove logs import and router from app.py**

In `book_scraper/dashboard/app.py`, remove the `logs` import and router inclusion. File becomes:

```python
from fastapi import FastAPI

from book_scraper.dashboard.routes import (
    inventory,
    listings,
    overview,
    prices,
    runs,
    shops,
    validation,
)

app = FastAPI(title="Book Scraper Dashboard")

app.include_router(overview.router)
app.include_router(shops.router)
app.include_router(listings.router)
app.include_router(runs.router)
app.include_router(validation.router)
app.include_router(prices.router)
app.include_router(inventory.router)
```

- [ ] **Step 3: Remove Logs nav link from base.html**

In `book_scraper/dashboard/templates/base.html`, remove line 39:
```html
            <li><a href="/logs" class="{{ 'active' if active_page == 'logs' else '' }}">Logs</a></li>
```

Also remove the `#log-output` CSS style block (line 23):
```css
        #log-output { background: #1a1a2e; color: #0f0; padding: 1rem; font-family: monospace; font-size: 0.85rem; height: 500px; overflow-y: auto; white-space: pre-wrap; border-radius: var(--pico-border-radius); }
```

- [ ] **Step 4: Verify the app still loads**

```bash
cd /Users/evaldas/Projects/book-scraper && uv run python -c "from book_scraper.dashboard.app import app; print('OK:', [r.path for r in app.routes])"
```

Expected: Prints list of routes without `/logs` or `/api/logs/stream`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "Remove logs page from dashboard"
```

---

### Task 2: Add Sort Header Macro and Styles to base.html

**Files:**
- Modify: `book_scraper/dashboard/templates/base.html`

- [ ] **Step 1: Add sort arrow styles and sort macro**

In `book_scraper/dashboard/templates/base.html`, add these CSS rules inside the existing `<style>` block (after the `.error` line):

```css
        th a { text-decoration: none; color: inherit; white-space: nowrap; }
        th a:hover { text-decoration: underline; }
        .sort-arrow { font-size: 0.7rem; margin-left: 0.2rem; }
```

Then add a Jinja2 macro block just before the `</head>` closing tag:

```html
{% macro sort_header(col, label, current_sort, current_order, base_params='') %}
<a href="?{{ base_params ~ '&' if base_params else '' }}sort={{ col }}&order={{ 'desc' if current_sort == col and current_order == 'asc' else 'asc' }}">
    {{ label }}
    {% if current_sort == col %}
    <span class="sort-arrow">{{ '▲' if current_order == 'asc' else '▼' }}</span>
    {% endif %}
</a>
{% endmacro %}
```

**Note:** Jinja2 macros defined in `base.html` aren't automatically available in child templates. Instead, we'll define the macro in a separate file and import it.

- [ ] **Step 2: Create macros file instead**

Create `book_scraper/dashboard/templates/macros.html`:

```html
{% macro sort_header(col, label, current_sort, current_order, base_params='') -%}
<a href="?{{ base_params ~ '&' if base_params else '' }}sort={{ col }}&order={{ 'desc' if current_sort == col and current_order == 'asc' else 'asc' }}">
    {{- label -}}
    {%- if current_sort == col %}<span class="sort-arrow">{{ '▲' if current_order == 'asc' else '▼' }}</span>{% endif -%}
</a>
{%- endmacro %}
```

- [ ] **Step 3: Add CSS only to base.html**

In `book_scraper/dashboard/templates/base.html`, add after line 22 (`.error { color: #e74c3c; }`):

```css
        th a { text-decoration: none; color: inherit; white-space: nowrap; }
        th a:hover { text-decoration: underline; }
        .sort-arrow { font-size: 0.7rem; margin-left: 0.2rem; }
        .tab-bar { display: flex; gap: 0; margin-bottom: 1.5rem; border-bottom: 2px solid var(--pico-muted-border-color); }
        .tab-bar button { background: none; border: none; padding: 0.5rem 1.2rem; cursor: pointer; font-size: 1rem; border-bottom: 2px solid transparent; margin-bottom: -2px; color: var(--pico-muted-color); }
        .tab-bar button.active { border-bottom-color: var(--pico-primary); color: var(--pico-color); font-weight: 600; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .filter-badge { display: inline-block; background: var(--pico-primary-background); padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.85rem; margin-right: 0.5rem; }
        .filter-badge a { margin-left: 0.3rem; text-decoration: none; }
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "Add sort header macro, tab styles, and filter badge styles"
```

---

### Task 3: Add Active, Has-ISBN, and Shop Filters to Listings

**Files:**
- Modify: `book_scraper/dashboard/queries.py:268-323` (`get_listings_page`)
- Modify: `book_scraper/dashboard/routes/listings.py:18-61`
- Modify: `book_scraper/dashboard/templates/listings.html`

- [ ] **Step 1: Add filter params to get_listings_page**

In `book_scraper/dashboard/queries.py`, update the `get_listings_page` function signature and body. Add `active_filter` and `has_isbn` params:

```python
def get_listings_page(
    session: Session,
    page: int = 1,
    per_page: int = 50,
    search: str = "",
    author: str = "",
    publisher: str = "",
    category: str = "",
    format_filter: str = "",
    missing_field: str = "",
    shop_id: int | None = None,
    active_filter: str = "",
    has_isbn: bool = False,
    sort_by: str = "",
    sort_order: str = "asc",
) -> tuple[list[Listing], int]:
```

Add these filter blocks after the existing `if shop_id:` block (before the `if search:` block):

```python
    if active_filter == "true":
        query = query.filter(Listing.is_active.is_(True))
    elif active_filter == "false":
        query = query.filter(Listing.is_active.is_(False))
    if has_isbn:
        query = query.filter(Listing.isbn.isnot(None))
```

Replace the existing `order_by` clause at the end of the function with sortable column support:

```python
    SORT_COLUMNS = {
        "id": Listing.id,
        "title": Listing.title,
        "author": Listing.author,
        "isbn": Listing.isbn,
        "price": Listing.price,
        "year": Listing.year,
        "is_active": Listing.is_active,
    }
    order_col = SORT_COLUMNS.get(sort_by, Listing.last_seen_at)
    if sort_order == "asc":
        query = query.order_by(order_col.asc().nulls_last())
    else:
        query = query.order_by(order_col.desc().nulls_last())
```

- [ ] **Step 2: Add params to listings route**

In `book_scraper/dashboard/routes/listings.py`, add new query params and pass them through:

```python
@router.get("/listings")
def listings_page(
    request: Request,
    page: int = 1,
    q: str = "",
    author: str = "",
    publisher: str = "",
    category: str = "",
    format: str = "",
    missing: str = "",
    active: str = "",
    has_isbn: bool = False,
    shop: str = "",
    sort: str = "",
    order: str = "desc",
    session: Session = Depends(get_db),
):
    shop_id = None
    shop_obj = None
    if shop:
        from book_scraper.dashboard.queries import get_shop_by_name
        shop_obj = get_shop_by_name(session, shop)
        if shop_obj:
            shop_id = shop_obj.id

    listings, total = get_listings_page(
        session,
        page=page,
        search=q,
        author=author,
        publisher=publisher,
        category=category,
        format_filter=format,
        missing_field=missing,
        shop_id=shop_id,
        active_filter=active,
        has_isbn=has_isbn,
        sort_by=sort,
        sort_order=order,
    )
    categories = get_all_categories(session)
    formats = get_all_formats(session)
    total_pages = (total + 49) // 50
    return templates.TemplateResponse(
        request,
        "listings.html",
        {
            "active_page": "listings",
            "listings": listings,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "query": q,
            "author_filter": author,
            "publisher_filter": publisher,
            "category": category,
            "format_filter": format,
            "missing": missing,
            "active_filter": active,
            "has_isbn": has_isbn,
            "shop_filter": shop,
            "sort": sort,
            "order": order,
            "categories": categories,
            "formats": formats,
        },
    )
```

Also add `get_shop_by_name` to the imports at the top of the file.

- [ ] **Step 3: Update listings.html template**

Replace the full `book_scraper/dashboard/templates/listings.html` with:

```html
{% extends "base.html" %}
{% from "macros.html" import sort_header %}
{% block title %}Listings{% endblock %}
{% block content %}
<h1>Listings</h1>

<form method="get" action="/listings">
    <div class="grid">
        <input type="search" name="q" placeholder="Search by title..." value="{{ query }}">
        <input type="search" name="author" placeholder="Filter by author..." value="{{ author_filter }}">
        <input type="search" name="publisher" placeholder="Filter by publisher..." value="{{ publisher_filter }}">
    </div>
    <div class="grid">
        <select name="category">
            <option value="">All categories</option>
            {% for cat in categories %}
            <option value="{{ cat }}" {{ 'selected' if category == cat else '' }}>{{ cat }}</option>
            {% endfor %}
        </select>
        <select name="format">
            <option value="">All formats</option>
            <option value="none" {{ 'selected' if format_filter == 'none' else '' }}>Missing format</option>
            {% for fmt in formats %}
            <option value="{{ fmt }}" {{ 'selected' if format_filter == fmt else '' }}>{{ fmt }}</option>
            {% endfor %}
        </select>
        <select name="missing">
            <option value="">No missing filter</option>
            <option value="any" {{ 'selected' if missing == 'any' else '' }}>Any field missing</option>
            <option value="author" {{ 'selected' if missing == 'author' else '' }}>Missing author</option>
            <option value="isbn" {{ 'selected' if missing == 'isbn' else '' }}>Missing ISBN</option>
            <option value="year" {{ 'selected' if missing == 'year' else '' }}>Missing year</option>
            <option value="publisher" {{ 'selected' if missing == 'publisher' else '' }}>Missing publisher</option>
            <option value="format" {{ 'selected' if missing == 'format' else '' }}>Missing format</option>
        </select>
    </div>
    <div class="grid">
        <select name="active">
            <option value="">All statuses</option>
            <option value="true" {{ 'selected' if active_filter == 'true' else '' }}>Active</option>
            <option value="false" {{ 'selected' if active_filter == 'false' else '' }}>Not Active</option>
        </select>
        <div></div>
        <div></div>
    </div>
    {% if shop_filter %}<input type="hidden" name="shop" value="{{ shop_filter }}">{% endif %}
    {% if has_isbn %}<input type="hidden" name="has_isbn" value="true">{% endif %}
    <button type="submit">Filter</button>
</form>

{% set filter_params = "q=" ~ query|urlencode ~ "&author=" ~ author_filter|urlencode ~ "&publisher=" ~ publisher_filter|urlencode ~ "&category=" ~ category|urlencode ~ "&format=" ~ format_filter|urlencode ~ "&missing=" ~ missing|urlencode ~ "&active=" ~ active_filter|urlencode ~ "&shop=" ~ shop_filter|urlencode ~ ("&has_isbn=true" if has_isbn else "") %}

{% if shop_filter or has_isbn or active_filter %}
<div style="margin-bottom: 1rem;">
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

<p><strong>{{ total }}</strong> results{% if author_filter %} for author "{{ author_filter }}"{% endif %}{% if publisher_filter %} for publisher "{{ publisher_filter }}"{% endif %}</p>

{% if listings %}
<table>
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
            <td><a href="/listings/{{ l.id }}">{{ l.title[:60] }}{{ '...' if l.title|length > 60 else '' }}</a></td>
            <td>
                {% if l.author %}
                <a href="/listings?author={{ l.author|urlencode }}">{{ l.author[:30] }}{{ '...' if l.author|length > 30 else '' }}</a>
                {% else %}-{% endif %}
            </td>
            <td>
                {% if l.isbn %}
                <a href="/listings?has_isbn=true&q={{ l.isbn|urlencode }}">{{ l.isbn }}</a>
                {% else %}-{% endif %}
            </td>
            <td>{{ l.format or '-' }}</td>
            <td>{{ l.price or '-' }}</td>
            <td>{{ l.price_original or '-' }}</td>
            <td>{{ l.year or '-' }}</td>
            <td>{{ 'Yes' if l.is_active else 'No' }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>

{% if total_pages > 1 %}
<nav>
    <ul>
        <li>
            {% if page > 1 %}
            <a href="/listings?page={{ page - 1 }}&{{ filter_params }}&sort={{ sort }}&order={{ order }}">Previous</a>
            {% else %}
            <span class="secondary">Previous</span>
            {% endif %}
        </li>
        <li>Page {{ page }} of {{ total_pages }}</li>
        <li>
            {% if page < total_pages %}
            <a href="/listings?page={{ page + 1 }}&{{ filter_params }}&sort={{ sort }}&order={{ order }}">Next</a>
            {% else %}
            <span class="secondary">Next</span>
            {% endif %}
        </li>
    </ul>
</nav>
{% endif %}

{% else %}
<p>No listings found.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Verify**

```bash
cd /Users/evaldas/Projects/book-scraper && uv run python -c "from book_scraper.dashboard.app import app; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "Add active, has_isbn, shop filters and sorting to listings page"
```

---

### Task 4: Update Overview Page — Stat Links, Updated Column, Cell Links

**Files:**
- Modify: `book_scraper/dashboard/templates/overview.html`

- [ ] **Step 1: Update overview.html**

Replace `book_scraper/dashboard/templates/overview.html` with:

```html
{% extends "base.html" %}
{% from "macros.html" import sort_header %}
{% block title %}Overview{% endblock %}
{% block content %}
<h1>Overview</h1>

<div class="stat-grid">
    <a href="/listings" class="stat-card" style="text-decoration:none; color:inherit;">
        <h2>{{ stats.total_listings }}</h2>
        <small>Total Listings</small>
    </a>
    <a href="/listings?active=true" class="stat-card" style="text-decoration:none; color:inherit;">
        <h2>{{ stats.active_listings }}</h2>
        <small>Active Listings</small>
    </a>
    <a href="/listings?has_isbn=true" class="stat-card" style="text-decoration:none; color:inherit;">
        <h2>{{ stats.with_isbn }}</h2>
        <small>With ISBN</small>
    </a>
    <a href="/prices" class="stat-card" style="text-decoration:none; color:inherit;">
        <h2>{{ stats.total_prices }}</h2>
        <small>Price Records</small>
    </a>
</div>

<h2>Recent Runs</h2>
<table>
    <thead>
        <tr>
            <th>ID</th>
            <th>Phase</th>
            <th>Status</th>
            <th>Started</th>
            <th>Items Added</th>
            <th>Updated</th>
            <th>Errors</th>
        </tr>
    </thead>
    <tbody>
        {% for run in recent_runs %}
        <tr>
            <td><a href="/runs/{{ run.id }}">{{ run.id }}</a></td>
            <td>{{ run.phase }}</td>
            <td><span class="badge badge-{{ run.status }}">{{ run.status }}</span></td>
            <td>{{ run.started_at.strftime('%Y-%m-%d %H:%M') if run.started_at else '-' }}</td>
            <td><a href="/runs/{{ run.id }}">{{ run.items_added }}</a></td>
            <td><a href="/runs/{{ run.id }}">{{ run.items_updated }}</a></td>
            <td><a href="/runs/{{ run.id }}">{{ run.error_count }}</a></td>
        </tr>
        {% endfor %}
    </tbody>
</table>

<h2>Validation Summary</h2>
<table>
    <thead>
        <tr>
            <th>Issue Type</th>
            <th>Count</th>
        </tr>
    </thead>
    <tbody>
        {% for v in validation %}
        <tr>
            <td><a href="/validation/{{ v.issue_type }}">{{ v.issue_type }}</a></td>
            <td>{{ v.count }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "Add stat links, Updated column, and cell links to overview page"
```

---

### Task 5: Update Shops List Page — Stat Links

**Files:**
- Modify: `book_scraper/dashboard/templates/shops.html`

- [ ] **Step 1: Update shops.html**

Replace `book_scraper/dashboard/templates/shops.html` with:

```html
{% extends "base.html" %}
{% block title %}Shops - Book Scraper{% endblock %}
{% block content %}
<h1>Shops</h1>

{% for item in shop_data %}
<article>
    <h3><a href="/shops/{{ item.shop.name }}">{{ item.shop.name }}</a> <small>{{ item.shop.base_url }}</small></h3>
    <div class="stat-grid">
        <div class="stat-card"><h2>{{ item.stats.discovered_urls }}</h2><small>Discovered URLs</small></div>
        <a href="/listings?shop={{ item.shop.name }}" class="stat-card" style="text-decoration:none; color:inherit;">
            <h2>{{ item.stats.listings }}</h2><small>Listings</small>
        </a>
        <a href="/listings?shop={{ item.shop.name }}&active=true" class="stat-card" style="text-decoration:none; color:inherit;">
            <h2>{{ item.stats.active }}</h2><small>Active</small>
        </a>
        <a href="/prices?shop={{ item.shop.name }}" class="stat-card" style="text-decoration:none; color:inherit;">
            <h2>{{ item.stats.prices }}</h2><small>Price Records</small>
        </a>
    </div>
</article>
{% endfor %}

{% if not shop_data %}
<p>No shops configured yet. Run a discover command to register a shop.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "Add stat links to shops list page"
```

---

### Task 6: Fix Price Changes Duplicate Bug

**Files:**
- Modify: `book_scraper/dashboard/queries.py:185-214` (`get_price_changes`)

- [ ] **Step 1: Fix the query**

In `book_scraper/dashboard/queries.py`, replace the `get_price_changes` function with:

```python
def get_price_changes(
    session: Session, days: int = 7, shop_id: int | None = None
) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    shop_filter = "AND l.shop_id = :shop_id" if shop_id else ""
    sql = text(f"""
        WITH ranked AS (
            SELECT
                p.listing_id,
                p.price,
                p.scraped_at,
                LAG(p.price) OVER (
                    PARTITION BY p.listing_id ORDER BY p.scraped_at
                ) AS prev_price
            FROM prices p
            JOIN listings l ON l.id = p.listing_id
            WHERE p.scraped_at >= :cutoff
            {shop_filter}
        ),
        changes AS (
            SELECT
                r.listing_id,
                l.title,
                r.prev_price,
                r.price AS new_price,
                r.price - r.prev_price AS change,
                r.scraped_at,
                ROW_NUMBER() OVER (
                    PARTITION BY r.listing_id, r.prev_price, r.price
                    ORDER BY r.scraped_at DESC
                ) AS rn
            FROM ranked r
            JOIN listings l ON l.id = r.listing_id
            WHERE r.prev_price IS NOT NULL
              AND r.price != r.prev_price
        )
        SELECT listing_id, title, prev_price, new_price, change, scraped_at
        FROM changes
        WHERE rn = 1
        ORDER BY ABS(change) DESC
        LIMIT 50
    """)
    params: dict = {"cutoff": cutoff}
    if shop_id:
        params["shop_id"] = shop_id
    rows = session.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]
```

This fixes two things:
1. **Deduplication**: `ROW_NUMBER()` partitioned by `(listing_id, prev_price, price)` keeps only the most recent occurrence of each unique price change per listing.
2. **Shop filter**: Optional `shop_id` param for filtering by shop.

- [ ] **Step 2: Verify**

```bash
cd /Users/evaldas/Projects/book-scraper && uv run python -c "
from book_scraper.dashboard.deps import _session_factory
from book_scraper.dashboard.queries import get_price_changes
with _session_factory() as s:
    changes = get_price_changes(s, days=7)
    print(f'{len(changes)} changes')
    # Check no duplicates per listing_id
    seen = set()
    for c in changes:
        key = (c['listing_id'], str(c['prev_price']), str(c['new_price']))
        assert key not in seen, f'Duplicate: {key}'
        seen.add(key)
    print('No duplicates found')
"
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "Fix price changes duplicate bug and add shop filter"
```

---

### Task 7: Update Prices Page — Shop Filter and Sorting

**Files:**
- Modify: `book_scraper/dashboard/routes/prices.py`
- Modify: `book_scraper/dashboard/templates/prices.html`

- [ ] **Step 1: Add shop filter to prices route**

Replace `book_scraper/dashboard/routes/prices.py` with:

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_price_changes,
    get_price_history,
    get_shop_by_name,
    search_listings,
)

router = APIRouter()


@router.get("/prices")
def prices_page(
    request: Request,
    q: str = "",
    shop: str = "",
    sort: str = "",
    order: str = "desc",
    session: Session = Depends(get_db),
):
    listings = search_listings(session, q) if q else []
    shop_id = None
    if shop:
        shop_obj = get_shop_by_name(session, shop)
        if shop_obj:
            shop_id = shop_obj.id
    changes = get_price_changes(session, days=7, shop_id=shop_id)

    # Sort changes in Python (they come from raw SQL)
    SORT_KEYS = {
        "title": lambda c: (c.get("title") or "").lower(),
        "prev_price": lambda c: float(c.get("prev_price") or 0),
        "new_price": lambda c: float(c.get("new_price") or 0),
        "change": lambda c: abs(float(c.get("change") or 0)),
        "scraped_at": lambda c: c.get("scraped_at") or "",
    }
    if sort in SORT_KEYS:
        reverse = order != "asc"
        changes = sorted(changes, key=SORT_KEYS[sort], reverse=reverse)

    return templates.TemplateResponse(
        request,
        "prices.html",
        {
            "active_page": "prices",
            "query": q,
            "shop_filter": shop,
            "listings": listings,
            "changes": changes,
            "sort": sort,
            "order": order,
        },
    )


@router.get("/api/prices/{listing_id}/chart")
def price_chart_data(listing_id: int, session: Session = Depends(get_db)):
    history = get_price_history(session, listing_id)
    labels = [p.scraped_at.isoformat() for p in history]
    prices = [float(p.price) for p in history]
    original = [float(p.price_original) if p.price_original else None for p in history]
    return JSONResponse(
        {
            "labels": labels,
            "prices": prices,
            "original_prices": original,
        }
    )
```

- [ ] **Step 2: Update prices.html with sort headers**

Replace `book_scraper/dashboard/templates/prices.html` with:

```html
{% extends "base.html" %}
{% from "macros.html" import sort_header %}
{% block title %}Prices{% endblock %}
{% block content %}
<h1>Prices</h1>

{% set base_params = "q=" ~ query|urlencode ~ "&shop=" ~ shop_filter|urlencode %}

{% if shop_filter %}
<div style="margin-bottom: 1rem;">
    <span class="filter-badge">Shop: {{ shop_filter }} <a href="/prices?q={{ query|urlencode }}">✕</a></span>
</div>
{% endif %}

<form method="get" action="/prices" role="search">
    {% if shop_filter %}<input type="hidden" name="shop" value="{{ shop_filter }}">{% endif %}
    <input type="search" name="q" placeholder="Search listings by title..." value="{{ query }}">
    <button type="submit">Search</button>
</form>

{% if listings %}
<h2>Search Results</h2>
<table>
    <thead>
        <tr>
            <th>Title</th>
            <th>Author</th>
            <th>Price</th>
            <th>Original</th>
            <th>Chart</th>
        </tr>
    </thead>
    <tbody>
        {% for l in listings %}
        <tr>
            <td><a href="/listings/{{ l.id }}">{{ l.title[:60] }}{{ '...' if l.title|length > 60 }}</a></td>
            <td>{{ l.author or '-' }}</td>
            <td>{{ l.price or '-' }}</td>
            <td>{{ l.price_original or '-' }}</td>
            <td><button class="outline" onclick="loadChart({{ l.id }}, '{{ l.title|e }}')">Show chart</button></td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% elif query %}
<p>No listings found for "{{ query }}".</p>
{% endif %}

<div id="chart-container" style="display:none; margin: 2rem 0;">
    <h3 id="chart-title"></h3>
    <canvas id="priceChart" height="100"></canvas>
</div>

<h2>Recent Price Changes (7 days)</h2>
{% if changes %}
<table>
    <thead>
        <tr>
            <th>{{ sort_header('title', 'Title', sort, order, base_params) }}</th>
            <th>{{ sort_header('prev_price', 'Previous', sort, order, base_params) }}</th>
            <th>{{ sort_header('new_price', 'New', sort, order, base_params) }}</th>
            <th>{{ sort_header('change', 'Change', sort, order, base_params) }}</th>
            <th>{{ sort_header('scraped_at', 'Date', sort, order, base_params) }}</th>
        </tr>
    </thead>
    <tbody>
        {% for c in changes %}
        <tr>
            <td><a href="/listings/{{ c.listing_id }}">{{ c.title[:60] }}{{ '...' if c.title|length > 60 }}</a></td>
            <td>{{ c.prev_price }}</td>
            <td>{{ c.new_price }}</td>
            <td style="color: {{ 'green' if c.change < 0 else 'red' }}">
                {{ '%+.2f'|format(c.change|float) }}
            </td>
            <td>{{ c.scraped_at.strftime('%Y-%m-%d %H:%M') if c.scraped_at else '-' }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p>No price changes in the last 7 days.</p>
{% endif %}

<script>
let chartInstance = null;
function loadChart(listingId, title) {
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
                borderColor: '#3498db',
                tension: 0.1,
                fill: false
            }];
            if (data.original_prices.some(p => p !== null)) {
                datasets.push({
                    label: 'Original Price',
                    data: data.original_prices,
                    borderColor: '#95a5a6',
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

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "Add shop filter and sorting to prices page"
```

---

### Task 8: Update Shop Detail Page — Tabs, Stat Links, Not-Listed

**Files:**
- Modify: `book_scraper/dashboard/queries.py` — add `get_not_listed_count` and `get_not_listed_urls`
- Modify: `book_scraper/dashboard/routes/shops.py` — add not-listed route, remove scrape-single-url, add sort params
- Modify: `book_scraper/dashboard/templates/shop_detail.html` — tabs, links
- Create: `book_scraper/dashboard/templates/not_listed.html`

- [ ] **Step 1: Add not-listed queries**

In `book_scraper/dashboard/queries.py`, add these functions at the end of the file:

```python
def get_not_listed_count(session: Session, shop_id: int) -> int:
    """Count discovered URLs that have no matching listing."""
    sql = text("""
        SELECT COUNT(*)
        FROM discovered_urls du
        WHERE du.shop_id = :shop_id
          AND NOT EXISTS (
              SELECT 1 FROM listings l
              WHERE l.shop_id = du.shop_id AND l.url = du.url
          )
    """)
    return session.execute(sql, {"shop_id": shop_id}).scalar() or 0


def get_not_listed_urls(
    session: Session,
    shop_id: int,
    page: int = 1,
    per_page: int = 50,
    sort_by: str = "",
    sort_order: str = "desc",
) -> tuple[list[dict], int]:
    """Get discovered URLs that have no matching listing, paginated."""
    count_sql = text("""
        SELECT COUNT(*)
        FROM discovered_urls du
        WHERE du.shop_id = :shop_id
          AND NOT EXISTS (
              SELECT 1 FROM listings l
              WHERE l.shop_id = du.shop_id AND l.url = du.url
          )
    """)
    total = session.execute(count_sql, {"shop_id": shop_id}).scalar() or 0

    sort_col = "du.discovered_at"
    if sort_by == "url":
        sort_col = "du.url"
    direction = "ASC" if sort_order == "asc" else "DESC"

    data_sql = text(f"""
        SELECT du.url, du.discovered_at, du.source, du.url_type
        FROM discovered_urls du
        WHERE du.shop_id = :shop_id
          AND NOT EXISTS (
              SELECT 1 FROM listings l
              WHERE l.shop_id = du.shop_id AND l.url = du.url
          )
        ORDER BY {sort_col} {direction}
        OFFSET :offset LIMIT :limit
    """)
    rows = session.execute(
        data_sql,
        {"shop_id": shop_id, "offset": (page - 1) * per_page, "limit": per_page},
    ).mappings().all()
    return [dict(r) for r in rows], total
```

- [ ] **Step 2: Add sorting to get_shop_runs**

In `book_scraper/dashboard/queries.py`, replace the `get_shop_runs` function:

```python
def get_shop_runs(
    session: Session,
    shop_id: int,
    limit: int = 50,
    sort_by: str = "",
    sort_order: str = "desc",
) -> list[ScrapeRun]:
    SORT_COLUMNS = {
        "id": ScrapeRun.id,
        "phase": ScrapeRun.phase,
        "status": ScrapeRun.status,
        "started_at": ScrapeRun.started_at,
        "items_added": ScrapeRun.items_added,
        "items_updated": ScrapeRun.items_updated,
        "error_count": ScrapeRun.error_count,
    }
    order_col = SORT_COLUMNS.get(sort_by, ScrapeRun.started_at)
    if sort_order == "asc":
        order_expr = order_col.asc()
    else:
        order_expr = order_col.desc()
    return (
        session.query(ScrapeRun)
        .filter(ScrapeRun.shop_id == shop_id)
        .order_by(order_expr)
        .limit(limit)
        .all()
    )
```

- [ ] **Step 3: Update shops route**

Replace `book_scraper/dashboard/routes/shops.py` with:

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, get_docker_client, templates
from book_scraper.dashboard.queries import (
    get_all_shops,
    get_not_listed_count,
    get_not_listed_urls,
    get_run_health,
    get_shop_by_name,
    get_shop_field_stats,
    get_shop_runs,
    get_shop_stats,
    mark_stale_runs,
)

router = APIRouter()

_SCRAPY = "/app/.venv/bin/scrapy"

SHOP_COMMANDS = {
    "discover_sitemap": [
        _SCRAPY, "crawl", "discover", "-a", "shop={shop}", "-a", "strategy=sitemap",
    ],
    "discover_categories": [
        _SCRAPY, "crawl", "discover", "-a", "shop={shop}", "-a", "strategy=categories",
    ],
    "scan": [
        _SCRAPY, "crawl", "scan", "-a", "shop={shop}",
    ],
    "rescrape": [
        _SCRAPY, "crawl", "scan", "-a", "shop={shop}", "-a", "rescrape=true",
    ],
}


@router.get("/shops")
def shops_list(request: Request, session: Session = Depends(get_db)):
    shops = get_all_shops(session)
    shop_data = []
    for shop in shops:
        stats = get_shop_stats(session, shop.id)
        shop_data.append({"shop": shop, "stats": stats})
    return templates.TemplateResponse(
        request,
        "shops.html",
        {"active_page": "shops", "shop_data": shop_data},
    )


@router.get("/shops/{shop_name}")
def shop_detail(
    shop_name: str,
    request: Request,
    sort: str = "",
    order: str = "desc",
    session: Session = Depends(get_db),
):
    shop = get_shop_by_name(session, shop_name)
    if shop is None:
        return HTMLResponse("Shop not found", status_code=404)
    mark_stale_runs(session)
    stats = get_shop_stats(session, shop.id)
    not_listed_count = get_not_listed_count(session, shop.id)
    field_stats = get_shop_field_stats(session, shop.id)
    runs = get_shop_runs(session, shop.id, sort_by=sort, sort_order=order)
    run_health = {run.id: get_run_health(run) for run in runs}
    return templates.TemplateResponse(
        request,
        "shop_detail.html",
        {
            "active_page": "shops",
            "shop": shop,
            "stats": stats,
            "not_listed_count": not_listed_count,
            "field_stats": field_stats,
            "runs": runs,
            "run_health": run_health,
            "sort": sort,
            "order": order,
        },
    )


@router.get("/shops/{shop_name}/not-listed")
def not_listed_page(
    shop_name: str,
    request: Request,
    page: int = 1,
    sort: str = "",
    order: str = "desc",
    session: Session = Depends(get_db),
):
    shop = get_shop_by_name(session, shop_name)
    if shop is None:
        return HTMLResponse("Shop not found", status_code=404)
    urls, total = get_not_listed_urls(
        session, shop.id, page=page, sort_by=sort, sort_order=order
    )
    total_pages = (total + 49) // 50
    return templates.TemplateResponse(
        request,
        "not_listed.html",
        {
            "active_page": "shops",
            "shop": shop,
            "urls": urls,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "sort": sort,
            "order": order,
        },
    )


@router.post("/shops/{shop_name}/run")
def trigger_shop_run(shop_name: str, phase: str = "scan"):
    cmd_template = SHOP_COMMANDS.get(phase)
    if not cmd_template:
        return HTMLResponse(
            f'<p class="error">Unknown phase: {phase}</p>',
            status_code=400,
        )

    cmd = [arg.replace("{shop}", shop_name) for arg in cmd_template]

    client = get_docker_client()
    if client is None:
        return HTMLResponse(
            '<p class="error">Docker not available</p>',
            status_code=503,
        )

    containers = client.containers.list(
        filters={"label": "com.docker.compose.service=scraper"}
    )
    if not containers:
        return HTMLResponse(
            '<p class="error">Scraper container not found</p>',
            status_code=503,
        )

    container = containers[0]
    container.exec_run(
        cmd,
        detach=True,
        workdir="/app",
        environment={
            "PYTHONPATH": "/app",
            "DATABASE_URL": "postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper",
        },
    )
    return HTMLResponse(
        f'<p class="success">Started {phase} for {shop_name}</p>',
        status_code=200,
    )
```

Note: `scrape_single_url` route is removed entirely.

- [ ] **Step 4: Create not_listed.html template**

Create `book_scraper/dashboard/templates/not_listed.html`:

```html
{% extends "base.html" %}
{% from "macros.html" import sort_header %}
{% block title %}Not Listed - {{ shop.name }}{% endblock %}
{% block content %}
<h1>Not Listed URLs <small>{{ shop.name }}</small></h1>
<p><a href="/shops/{{ shop.name }}">← Back to {{ shop.name }}</a></p>
<p><strong>{{ total }}</strong> discovered URLs with no matching listing (non-book pages).</p>

{% if urls %}
<table>
    <thead>
        <tr>
            <th>{{ sort_header('url', 'URL', sort, order) }}</th>
            <th>Source</th>
            <th>Type</th>
            <th>{{ sort_header('discovered_at', 'Discovered', sort, order) }}</th>
        </tr>
    </thead>
    <tbody>
        {% for u in urls %}
        <tr>
            <td><a href="{{ u.url }}" target="_blank" rel="noopener">{{ u.url[:80] }}{{ '...' if u.url|length > 80 }}</a></td>
            <td>{{ u.source }}</td>
            <td>{{ u.url_type }}</td>
            <td>{{ u.discovered_at.strftime('%Y-%m-%d %H:%M') if u.discovered_at else '-' }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>

{% if total_pages > 1 %}
<nav>
    <ul>
        <li>
            {% if page > 1 %}
            <a href="/shops/{{ shop.name }}/not-listed?page={{ page - 1 }}&sort={{ sort }}&order={{ order }}">Previous</a>
            {% else %}
            <span class="secondary">Previous</span>
            {% endif %}
        </li>
        <li>Page {{ page }} of {{ total_pages }}</li>
        <li>
            {% if page < total_pages %}
            <a href="/shops/{{ shop.name }}/not-listed?page={{ page + 1 }}&sort={{ sort }}&order={{ order }}">Next</a>
            {% else %}
            <span class="secondary">Next</span>
            {% endif %}
        </li>
    </ul>
</nav>
{% endif %}

{% else %}
<p>All discovered URLs have matching listings.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Update shop_detail.html with tabs, links, sorting**

Replace `book_scraper/dashboard/templates/shop_detail.html` with:

```html
{% extends "base.html" %}
{% from "macros.html" import sort_header %}
{% block title %}{{ shop.name }} - Book Scraper{% endblock %}
{% block content %}
<style>
    .health-healthy { color: #2ecc40; }
    .health-stale { color: #ffdc00; }
    .health-dead { color: #ff4136; }
    .actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
</style>

<h1>{{ shop.name }} <small>{{ shop.base_url }}</small></h1>

<div class="stat-grid">
    <article class="stat-card"><h2>{{ stats.discovered_urls }}</h2><small>Discovered URLs</small></article>
    <a href="/listings?shop={{ shop.name }}" class="stat-card" style="text-decoration:none; color:inherit;">
        <h2>{{ stats.listings }}</h2><small>Listings</small>
    </a>
    <a href="/listings?shop={{ shop.name }}&active=true" class="stat-card" style="text-decoration:none; color:inherit;">
        <h2>{{ stats.active }}</h2><small>Active</small>
    </a>
    <a href="/prices?shop={{ shop.name }}" class="stat-card" style="text-decoration:none; color:inherit;">
        <h2>{{ stats.prices }}</h2><small>Price Records</small>
    </a>
    <a href="/shops/{{ shop.name }}/not-listed" class="stat-card" style="text-decoration:none; color:inherit;">
        <h2>{{ not_listed_count }}</h2><small>Not Listed</small>
    </a>
</div>

<div class="tab-bar">
    <button class="active" onclick="switchTab('runs', this)">Runs</button>
    <button onclick="switchTab('data', this)">Data</button>
</div>

<div id="tab-runs" class="tab-content active">
    <article>
        <h3>Run Commands</h3>
        <div class="actions">
            <button hx-post="/shops/{{ shop.name }}/run?phase=discover_sitemap" hx-target="#run-result" hx-swap="innerHTML">Discover (Sitemap)</button>
            <button hx-post="/shops/{{ shop.name }}/run?phase=discover_categories" hx-target="#run-result" hx-swap="innerHTML">Discover (Categories)</button>
            <button hx-post="/shops/{{ shop.name }}/run?phase=scan" hx-target="#run-result" hx-swap="innerHTML">Scan</button>
            <button class="secondary" hx-post="/shops/{{ shop.name }}/run?phase=rescrape" hx-target="#run-result" hx-swap="innerHTML">Rescrape All</button>
        </div>
        <div id="run-result" style="margin-top: 0.5rem;"></div>
    </article>

    <h2>Recent Runs</h2>
    <div hx-get="/shops/{{ shop.name }}" hx-trigger="every 10s" hx-select="#runs-table" hx-target="#runs-table" hx-swap="outerHTML">
    <table id="runs-table">
        <thead>
            <tr>
                <th>{{ sort_header('id', 'ID', sort, order) }}</th>
                <th>Phase</th>
                <th>Status</th>
                <th>Health</th>
                <th>{{ sort_header('started_at', 'Started', sort, order) }}</th>
                <th>Duration</th>
                <th>Progress</th>
                <th>{{ sort_header('items_added', 'Added', sort, order) }}</th>
                <th>{{ sort_header('items_updated', 'Updated', sort, order) }}</th>
                <th>{{ sort_header('error_count', 'Errors', sort, order) }}</th>
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
                    {% if health == 'healthy' %}
                        <span class="health-healthy">&#9679; active</span>
                    {% elif health == 'stale' %}
                        <span class="health-stale">&#9679; stale</span>
                    {% elif health == 'dead' %}
                        <span class="health-dead">&#9679; dead</span>
                    {% endif %}
                </td>
                <td>{{ run.started_at.strftime('%Y-%m-%d %H:%M') if run.started_at else '-' }}</td>
                <td>
                    {% if run.finished_at and run.started_at %}
                        {{ (run.finished_at - run.started_at) }}
                    {% elif run.status == 'running' %}
                        running...
                    {% else %}
                        -
                    {% endif %}
                </td>
                <td>
                    {% if run.urls_total %}
                        {{ run.urls_processed }}/{{ run.urls_total }}
                    {% elif run.urls_processed %}
                        {{ run.urls_processed }}
                    {% else %}
                        -
                    {% endif %}
                </td>
                <td><a href="/runs/{{ run.id }}">{{ run.items_added }}</a></td>
                <td><a href="/runs/{{ run.id }}">{{ run.items_updated }}</a></td>
                <td><a href="/runs/{{ run.id }}">{{ run.error_count }}</a></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
</div>

<div id="tab-data" class="tab-content">
    {% if field_stats and field_stats.total > 0 %}
    <article>
        <h3>Data Completeness</h3>
        <table>
            <thead>
                <tr>
                    <th>Field</th>
                    <th>Present</th>
                    <th>Missing</th>
                    <th>% Complete</th>
                </tr>
            </thead>
            <tbody>
                {% for field_name, counts in field_stats.fields.items() %}
                <tr>
                    <td>{{ field_name }}</td>
                    <td>{{ counts.present }}</td>
                    <td>
                        {% if counts.missing > 0 %}
                        <a href="/listings?shop={{ shop.name }}&missing={{ field_name }}">{{ counts.missing }}</a>
                        {% else %}
                        0
                        {% endif %}
                    </td>
                    <td>{{ '%.1f%%'|format(counts.present / field_stats.total * 100) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </article>
    {% endif %}
</div>

<script>
function switchTab(tabId, btn) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-bar button').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-' + tabId).classList.add('active');
    btn.classList.add('active');
}
</script>
{% endblock %}
```

- [ ] **Step 6: Verify**

```bash
cd /Users/evaldas/Projects/book-scraper && uv run python -c "from book_scraper.dashboard.app import app; print('OK')"
```

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "Add tabs, stat links, not-listed page, and sorting to shop detail"
```

---

### Task 9: Update Runs Page — Run Commands, Cell Links, Sorting

**Files:**
- Modify: `book_scraper/dashboard/queries.py` — add sorting to `get_recent_runs`
- Modify: `book_scraper/dashboard/routes/runs.py`
- Modify: `book_scraper/dashboard/templates/runs.html`

- [ ] **Step 1: Add sorting to get_recent_runs**

In `book_scraper/dashboard/queries.py`, replace the `get_recent_runs` function:

```python
def get_recent_runs(
    session: Session,
    limit: int = 20,
    sort_by: str = "",
    sort_order: str = "desc",
) -> list[ScrapeRun]:
    SORT_COLUMNS = {
        "id": ScrapeRun.id,
        "phase": ScrapeRun.phase,
        "status": ScrapeRun.status,
        "started_at": ScrapeRun.started_at,
        "items_added": ScrapeRun.items_added,
        "items_updated": ScrapeRun.items_updated,
        "error_count": ScrapeRun.error_count,
    }
    order_col = SORT_COLUMNS.get(sort_by, ScrapeRun.started_at)
    if sort_order == "asc":
        order_expr = order_col.asc()
    else:
        order_expr = order_col.desc()
    return (
        session.query(ScrapeRun)
        .options(joinedload(ScrapeRun.shop))
        .order_by(order_expr)
        .limit(limit)
        .all()
    )
```

- [ ] **Step 2: Update runs route**

In `book_scraper/dashboard/routes/runs.py`, update the `runs_list` function:

```python
@router.get("/runs")
def runs_list(
    request: Request,
    sort: str = "",
    order: str = "desc",
    session: Session = Depends(get_db),
):
    mark_stale_runs(session)
    recent_runs = get_recent_runs(session, limit=50, sort_by=sort, sort_order=order)
    run_health = {run.id: get_run_health(run) for run in recent_runs}
    return templates.TemplateResponse(
        request,
        "runs.html",
        {
            "active_page": "runs",
            "runs": recent_runs,
            "run_health": run_health,
            "sort": sort,
            "order": order,
        },
    )
```

- [ ] **Step 3: Update runs.html**

Replace `book_scraper/dashboard/templates/runs.html` with:

```html
{% extends "base.html" %}
{% from "macros.html" import sort_header %}
{% block title %}Runs{% endblock %}
{% block content %}
<style>
    .health-healthy { color: #2ecc40; }
    .health-stale { color: #ffdc00; }
    .health-dead { color: #ff4136; }
    .actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
</style>
<h1>Scrape Runs</h1>

<article>
    <h3>Run Commands</h3>
    <div class="actions">
        <button hx-post="/runs/trigger?phase=discover_sitemap" hx-target="#run-result" hx-swap="innerHTML">Discover (Sitemap)</button>
        <button hx-post="/runs/trigger?phase=discover_categories" hx-target="#run-result" hx-swap="innerHTML">Discover (Categories)</button>
        <button hx-post="/runs/trigger?phase=scan" hx-target="#run-result" hx-swap="innerHTML">Scan</button>
        <button class="secondary" hx-post="/runs/trigger?phase=rescrape" hx-target="#run-result" hx-swap="innerHTML">Rescrape All</button>
    </div>
    <div id="run-result" style="margin-top: 0.5rem;"></div>
</article>

<div hx-get="/runs?sort={{ sort }}&order={{ order }}" hx-trigger="every 10s" hx-select="#runs-table" hx-target="#runs-table" hx-swap="outerHTML">
<table id="runs-table">
    <thead>
        <tr>
            <th>{{ sort_header('id', 'ID', sort, order) }}</th>
            <th>Shop</th>
            <th>{{ sort_header('phase', 'Phase', sort, order) }}</th>
            <th>{{ sort_header('status', 'Status', sort, order) }}</th>
            <th>Health</th>
            <th>{{ sort_header('started_at', 'Started', sort, order) }}</th>
            <th>Duration</th>
            <th>Progress</th>
            <th>{{ sort_header('items_added', 'Added', sort, order) }}</th>
            <th>{{ sort_header('items_updated', 'Updated', sort, order) }}</th>
            <th>{{ sort_header('error_count', 'Errors', sort, order) }}</th>
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
                {% if health == 'healthy' %}
                    <span class="health-healthy" title="Heartbeat active">&#9679; active</span>
                {% elif health == 'stale' %}
                    <span class="health-stale" title="No heartbeat for >5 min">&#9679; stale</span>
                {% elif health == 'dead' %}
                    <span class="health-dead" title="No heartbeat for >2 hours">&#9679; dead</span>
                {% endif %}
            </td>
            <td>{{ run.started_at.strftime('%Y-%m-%d %H:%M') if run.started_at else '-' }}</td>
            <td>
                {% if run.finished_at and run.started_at %}
                    {{ (run.finished_at - run.started_at) }}
                {% elif run.status == 'running' %}
                    running...
                {% else %}
                    -
                {% endif %}
            </td>
            <td>
                {% if run.urls_total %}
                    {{ run.urls_processed }}/{{ run.urls_total }}
                {% elif run.urls_processed %}
                    {{ run.urls_processed }}
                {% else %}
                    -
                {% endif %}
            </td>
            <td><a href="/runs/{{ run.id }}">{{ run.items_added }}</a></td>
            <td><a href="/runs/{{ run.id }}">{{ run.items_updated }}</a></td>
            <td><a href="/runs/{{ run.id }}">{{ run.error_count }}</a></td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>
{% endblock %}
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "Add run commands, cell links, and sorting to runs page"
```

---

### Task 10: Final Verification

- [ ] **Step 1: Run linting**

```bash
cd /Users/evaldas/Projects/book-scraper && uv run ruff check book_scraper/dashboard/ && uv run ruff format book_scraper/dashboard/
```

- [ ] **Step 2: Run type checking**

```bash
cd /Users/evaldas/Projects/book-scraper && uv run mypy book_scraper/dashboard/
```

- [ ] **Step 3: Run tests**

```bash
cd /Users/evaldas/Projects/book-scraper && uv run pytest tests/ -v
```

- [ ] **Step 4: Verify app imports**

```bash
cd /Users/evaldas/Projects/book-scraper && uv run python -c "
from book_scraper.dashboard.app import app
routes = [r.path for r in app.routes if hasattr(r, 'path')]
print('Routes:', sorted(routes))
assert '/logs' not in routes
assert '/shops/{shop_name}/not-listed' in routes
print('All good')
"
```

- [ ] **Step 5: Fix any issues found and commit**

```bash
git add -A && git commit -m "Fix linting and type issues from dashboard improvements"
```
