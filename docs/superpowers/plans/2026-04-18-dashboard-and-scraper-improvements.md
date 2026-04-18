# Dashboard & Scraper Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 8 backlog tasks spanning dashboard UX improvements, data extraction quality, and a persistent scraping pipeline queue.

**Architecture:** Dashboard tasks modify FastAPI routes, Jinja2 templates, and `queries.py`. Scraper tasks modify `discover.py` / `scan.py` spiders and introduce a new `scrape_url_items` DB table for crash-safe work queues.

**Tech Stack:** FastAPI, Jinja2, SQLAlchemy 2.0, Alembic, Scrapy, PostgreSQL, Python 3.12+

---

## File Map

### Modified files
- `book_scraper/dashboard/app.py` — add `relative_time` Jinja filter
- `book_scraper/dashboard/queries.py` — add `get_field_history()`, `get_attribute_keys()`, `get_attribute_values()`, extend `get_shop_books_page()` and `get_issues_page()` / `get_validation_lifecycle_counts()`
- `book_scraper/dashboard/routes/validation.py` — add `severity` param
- `book_scraper/dashboard/routes/shop_books.py` — add `attr_key`, `attr_value` params
- `book_scraper/dashboard/templates/shop_books.html` — "More filters" toggle, attribute filter
- `book_scraper/dashboard/templates/shop_book_detail.html` — description diff collapse, field history, click-to-filter
- `book_scraper/dashboard/templates/validation.html` — severity dropdown
- `book_scraper/spiders/discover.py` — yield `ShopBookItem` from `parse_categories` and `parse_full_crawl`
- `book_scraper/db/models.py` — add `ScrapeUrlItem` model
- `book_scraper/db/repo.py` — add scrape_url_item repo functions
- `book_scraper/services/scan.py` — `ScanPlan` + `prepare_scan()` refactor
- `book_scraper/spiders/scan.py` — use `scrape_url_items` table

### Created files
- `alembic/versions/<hash>_add_scrape_url_items_table.py` — migration

---

## Task 1: Relative Time Filter

**Files:**
- Modify: `book_scraper/dashboard/app.py`
- Modify: `book_scraper/dashboard/templates/shop_books.html`
- Test: `tests/unit/test_relative_time.py`

- [ ] **Step 1: Write the failing unit test**

```python
# tests/unit/test_relative_time.py
from datetime import UTC, datetime, timedelta

import pytest


def test_relative_time_just_now():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(seconds=30)
    assert _relative_time(dt) == "just now"


def test_relative_time_minutes():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(minutes=5)
    assert _relative_time(dt) == "5m ago"


def test_relative_time_hours():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(hours=3)
    assert _relative_time(dt) == "3h ago"


def test_relative_time_days():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(days=2)
    assert _relative_time(dt) == "2d ago"


def test_relative_time_weeks():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(weeks=3)
    assert _relative_time(dt) == "3w ago"


def test_relative_time_months():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(days=65)
    assert _relative_time(dt) == "2mo ago"


def test_relative_time_years():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(days=400)
    assert _relative_time(dt) == "1y ago"


def test_relative_time_none():
    from book_scraper.dashboard.app import _relative_time
    assert _relative_time(None) == "—"


def test_relative_time_naive_datetime():
    from book_scraper.dashboard.app import _relative_time
    # naive datetimes should not raise
    dt = datetime.utcnow() - timedelta(hours=1)
    result = _relative_time(dt)
    assert "h ago" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/evaldas/Projects/book-scraper
uv run pytest tests/unit/test_relative_time.py -v
```

Expected: `ImportError` or `AttributeError: module has no attribute '_relative_time'`

- [ ] **Step 3: Add `_relative_time` to `app.py`**

In `book_scraper/dashboard/app.py`, add this function after the imports and before `_render_description`, then register it as a Jinja filter at the bottom:

```python
def _relative_time(dt: "datetime | None") -> str:
    """Return human-friendly relative time string, e.g. '3d ago'."""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks}w ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"
```

The function needs `datetime` and `UTC` — add to the imports at the top of `app.py`:
```python
from datetime import UTC, datetime
```

Then at the bottom of `app.py`, add:
```python
templates.env.filters["relative_time"] = _relative_time
```

- [ ] **Step 4: Run unit tests to verify they pass**

```bash
uv run pytest tests/unit/test_relative_time.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Update `shop_books.html` Updated column**

In `book_scraper/dashboard/templates/shop_books.html`, locate the "Updated" column cell at line ~163:

```html
<td class="text-muted">{{ sb.last_seen_at.strftime('%Y-%m-%d') if sb.last_seen_at else '—' }}</td>
```

Replace with:

```html
<td class="text-muted"
    title="{{ sb.last_seen_at.strftime('%Y-%m-%d %H:%M UTC') if sb.last_seen_at else '' }}">
    {{ sb.last_seen_at|relative_time if sb.last_seen_at else '—' }}
</td>
```

- [ ] **Step 6: Commit**

```bash
git add book_scraper/dashboard/app.py \
        book_scraper/dashboard/templates/shop_books.html \
        tests/unit/test_relative_time.py
git commit -m "feat: add relative_time Jinja filter, use it in shop_books Updated column"
```

---

## Task 2: Collapse Description Diffs in Change History

**Files:**
- Modify: `book_scraper/dashboard/templates/shop_book_detail.html`

- [ ] **Step 1: Update the Change History table in `shop_book_detail.html`**

Find the Change History `<tbody>` loop (around line 338):

```html
{% for c in changes %}
<tr>
    <td class="text-muted">{{ c.changed_at.strftime('%Y-%m-%d %H:%M') }}</td>
    <td>{{ c.field }}</td>
    <td class="change-diff-cell">{{ change_diff(c.old_value, c.new_value, 200) }}</td>
    <td>{% if c.scrape_run_id %}<a href="/runs/{{ c.scrape_run_id }}">Run #{{ c.scrape_run_id }}</a>{% else %}<span class="text-muted">—</span>{% endif %}</td>
</tr>
{% endfor %}
```

Replace with:

```html
{% for c in changes %}
<tr>
    <td class="text-muted">{{ c.changed_at.strftime('%Y-%m-%d %H:%M') }}</td>
    <td>{{ c.field }}</td>
    <td class="change-diff-cell">
        {% if c.field == 'description' %}
        <details class="change-diff">
            <summary>Description changed — click to view diff</summary>
            <div class="change-diff-body">{{ change_diff(c.old_value, c.new_value, 999999) }}</div>
        </details>
        {% else %}
        {{ change_diff(c.old_value, c.new_value, 200) }}
        {% endif %}
    </td>
    <td>{% if c.scrape_run_id %}<a href="/runs/{{ c.scrape_run_id }}">Run #{{ c.scrape_run_id }}</a>{% else %}<span class="text-muted">—</span>{% endif %}</td>
</tr>
{% endfor %}
```

- [ ] **Step 2: Smoke-test via dashboard route test**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v -k "shop_book_detail or shop_books"
```

Expected: PASS (the template renders without error).

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/templates/shop_book_detail.html
git commit -m "feat: always collapse description diffs in Change History"
```

---

## Task 3: Filter Issues by Severity

**Files:**
- Modify: `book_scraper/dashboard/queries.py`
- Modify: `book_scraper/dashboard/routes/validation.py`
- Modify: `book_scraper/dashboard/templates/validation.html`
- Test: `tests/integration/test_validation_queries.py`

- [ ] **Step 1: Write failing tests for severity filtering**

Open `tests/integration/test_validation_queries.py` and add:

```python
def test_get_issues_page_severity_critical(db_session, shop, scrape_run, validation_issues):
    """Severity filter returns only critical issues."""
    from book_scraper.dashboard.queries import get_issues_page, ISSUE_SEVERITY
    rows, total = get_issues_page(db_session, state=None, severity="critical")
    critical_types = {k for k, v in ISSUE_SEVERITY.items() if v == "critical"}
    for row in rows:
        assert row["issue"] in critical_types


def test_get_issues_page_severity_warning(db_session, shop, scrape_run, validation_issues):
    """Severity filter returns only warning issues."""
    from book_scraper.dashboard.queries import get_issues_page, ISSUE_SEVERITY
    rows, total = get_issues_page(db_session, state=None, severity="warning")
    warning_types = {k for k, v in ISSUE_SEVERITY.items() if v == "warning"}
    for row in rows:
        assert row["issue"] in warning_types


def test_get_issues_page_severity_empty_returns_all(db_session, shop, scrape_run, validation_issues):
    """No severity filter returns all issues."""
    from book_scraper.dashboard.queries import get_issues_page
    rows_all, total_all = get_issues_page(db_session, state=None, severity="")
    rows_crit, total_crit = get_issues_page(db_session, state=None, severity="critical")
    rows_warn, total_warn = get_issues_page(db_session, state=None, severity="warning")
    assert total_all == total_crit + total_warn


def test_lifecycle_counts_severity_filter(db_session, shop, scrape_run, validation_issues):
    """get_validation_lifecycle_counts respects severity filter."""
    from book_scraper.dashboard.queries import get_validation_lifecycle_counts, ISSUE_SEVERITY
    counts_all = get_validation_lifecycle_counts(db_session)
    counts_crit = get_validation_lifecycle_counts(db_session, severity="critical")
    # Critical count must be <= all
    assert counts_crit["open"] <= counts_all["open"]
```

(Note: these tests require existing fixtures `db_session`, `shop`, `scrape_run`, `validation_issues` from the test file's conftest or existing fixtures. Check `tests/integration/test_validation_queries.py` for existing fixture usage and replicate it.)

- [ ] **Step 2: Run to verify tests fail**

```bash
uv run pytest tests/integration/test_validation_queries.py -v -k "severity"
```

Expected: `TypeError` — `get_issues_page` doesn't accept `severity` parameter.

- [ ] **Step 3: Add severity param to `get_issues_page()` in `queries.py`**

Find the `get_issues_page` signature (around line 236) and add `severity: str = ""`:

```python
def get_issues_page(
    session: Session,
    state: str | None = "open",
    shop_id: int | None = None,
    issue_type: str = "",
    run_id: int | None = None,
    q: str = "",
    severity: str = "",
    order: str = "desc",
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], int]:
```

Then after the `if issue_type:` block, add:

```python
    if severity in ("critical", "warning"):
        severity_types = [k for k, v in ISSUE_SEVERITY.items() if v == severity]
        query = query.filter(ValidationIssue.issue.in_(severity_types))
```

- [ ] **Step 4: Add severity param to `get_validation_lifecycle_counts()` in `queries.py`**

Find the `get_validation_lifecycle_counts` signature (around line 198) and add `severity: str = ""`:

```python
def get_validation_lifecycle_counts(
    session: Session,
    shop_id: int | None = None,
    issue_type: str = "",
    run_id: int | None = None,
    q: str = "",
    severity: str = "",
) -> dict[str, int]:
```

After the `if issue_type:` block, add:

```python
    if severity in ("critical", "warning"):
        severity_types = [k for k, v in ISSUE_SEVERITY.items() if v == severity]
        query = query.filter(ValidationIssue.issue.in_(severity_types))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_validation_queries.py -v -k "severity"
```

Expected: all severity tests PASS.

- [ ] **Step 6: Add `severity` param to `validation_list()` and `_filter_params()` in `routes/validation.py`**

Update `_filter_params`:

```python
def _filter_params(
    state: str, shop: str, issue_type: str, run_id: str, q: str, order: str, severity: str = ""
) -> str:
    params: dict[str, str] = {}
    if state:
        params["state"] = state
    if shop:
        params["shop"] = shop
    if issue_type:
        params["issue_type"] = issue_type
    if run_id:
        params["run_id"] = run_id
    if q:
        params["q"] = q
    if order:
        params["order"] = order
    if severity:
        params["severity"] = severity
    return urlencode(params)
```

Update `validation_list` signature:

```python
@router.get("/validation")
def validation_list(
    request: Request,
    state: str = "open",
    shop: str = "",
    issue_type: str = "",
    run_id: str = "",
    q: str = "",
    order: str = "desc",
    severity: str = "",
    page: int = 1,
    session: Session = Depends(get_db),
) -> Response:
```

Pass `severity` to both queries and the template:

```python
    rows, total = get_issues_page(
        session,
        state=lifecycle_state,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id_int,
        q=q,
        severity=severity,
        order=order,
        page=max(page, 1),
        per_page=_PER_PAGE,
    )
    counts = get_validation_lifecycle_counts(
        session,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id_int,
        q=q,
        severity=severity,
    )
```

In the `return templates.TemplateResponse(...)` call, add `"selected_severity": severity` to the context dict, and update `filter_params`:

```python
    "selected_severity": severity,
    "filter_params": _filter_params(
        state, shop, issue_type, str(run_id_int) if run_id_int else "", q, order, severity
    ),
```

Also update the lifecycle tabs `base` variable in `validation.html` to include severity — but that's a template change, handled in the next step.

- [ ] **Step 7: Add severity dropdown to `validation.html`**

In `validation.html`, find the filter bar form (after the Issue `<select>` and before the Run `<label>`), add:

```html
        <label>Severity</label>
        <select name="severity">
            <option value="">All severities</option>
            <option value="critical" {% if selected_severity == 'critical' %}selected{% endif %}>Critical</option>
            <option value="warning" {% if selected_severity == 'warning' %}selected{% endif %}>Warning</option>
        </select>
```

Also update the lifecycle tabs `base` line at the top of the template to include severity:

```html
{% set base = 'shop=' ~ selected_shop|urlencode ~ '&issue_type=' ~ selected_issue_type|urlencode ~ '&severity=' ~ selected_severity|urlencode ~ ('&run_id=' ~ selected_run_id if selected_run_id else '') ~ '&q=' ~ q|urlencode ~ '&order=' ~ order %}
```

Also update the Reset button condition in the filter bar to also reset severity:

```html
        {% if selected_shop or selected_issue_type or selected_run_id or q or selected_severity %}
        <a href="/validation?state={{ state }}" role="button" class="secondary">Reset</a>
        {% endif %}
```

- [ ] **Step 8: Smoke-test routes**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v -k "validation"
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add book_scraper/dashboard/queries.py \
        book_scraper/dashboard/routes/validation.py \
        book_scraper/dashboard/templates/validation.html \
        tests/integration/test_validation_queries.py
git commit -m "feat: add severity filter to Issues page"
```

---

## Task 4: Hide Non-Essential Filters Behind "More Filters"

**Files:**
- Modify: `book_scraper/dashboard/templates/shop_books.html`

- [ ] **Step 1: Restructure the filter bar in `shop_books.html`**

The current filter bar shows: q, author, publisher, category, type, format, missing, active.
Keep visible: q, shop (if applicable), active. Hide in `<details>`: author, publisher, category, type, format, missing.

Find the `<div class="filter-bar">` block (lines 14–87). The current structure has all inputs inline. Rewrite the filter bar section to wrap secondary filters in a `<details>` element:

```html
<form method="get" action="/shop-books">
    <div class="filter-bar">
        <input type="search" name="q" placeholder="Search by title..." value="{{ query }}">
        {% if shop_filter %}<input type="hidden" name="shop" value="{{ shop_filter }}">{% endif %}
        <select name="active">
            <option value="true" {{ 'selected' if active_filter == 'true' else '' }}>Active</option>
            <option value="false" {{ 'selected' if active_filter == 'false' else '' }}>Inactive</option>
            <option value="all" {{ 'selected' if active_filter == 'all' else '' }}>All</option>
        </select>

        <details class="more-filters-panel" {{ 'open' if secondary_filters_active else '' }}>
            <summary>More filters ▼</summary>
            <div class="more-filters-grid">
                <input type="search" name="author" placeholder="Filter by author..." value="{{ author_filter }}">
                <input type="search" name="publisher" placeholder="Filter by publisher..." value="{{ publisher_filter }}">
                <select name="category">
                    <option value="">All categories</option>
                    {% for cat in categories %}
                    <option value="{{ cat }}" {{ 'selected' if category == cat else '' }}>{{ cat }}</option>
                    {% endfor %}
                </select>
                <select name="type">
                    <option value="">All types</option>
                    {% for book_type in types %}
                    <option value="{{ book_type }}" {{ 'selected' if type_filter == book_type else '' }}>{{ book_type }}</option>
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
        </details>

        {% if has_isbn %}<input type="hidden" name="has_isbn" value="true">{% endif %}
        {% if sort %}<input type="hidden" name="sort" value="{{ sort }}">{% endif %}
        {% if order %}<input type="hidden" name="order" value="{{ order }}">{% endif %}

        <details class="field-filters-panel" {{ 'open' if field_filters_active else '' }}>
            <summary>All field filters</summary>
            <div class="field-filter-grid">
                {% for field in field_filters %}
                <div class="field-filter-card">
                    <label for="field_{{ field.name }}_op">{{ field.label }}</label>
                    <div class="field-filter-controls">
                        <select id="field_{{ field.name }}_op" name="field_{{ field.name }}_op">
                            {% for option in field.operators %}
                            <option value="{{ option.value }}" {{ 'selected' if field.operator == option.value else '' }}>{{ option.label }}</option>
                            {% endfor %}
                        </select>
                        {% if field.show_value_input %}
                        <input
                            type="{{ field.input_type }}"
                            name="field_{{ field.name }}_value"
                            value="{{ field.value }}"
                            placeholder="{{ field.placeholder }}"
                            {% if field.input_step %}step="{{ field.input_step }}"{% endif %}
                        >
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </details>

        <button type="submit">Filter</button>
        {% if has_visible_filters %}
        <a href="{{ reset_url }}" role="button" class="secondary">Reset</a>
        {% endif %}
    </div>
</form>
```

Add CSS for the new `.more-filters-panel` and `.more-filters-grid` inside the existing styles or in `base.html`. Add inline in the template:

```html
<style>
.more-filters-panel { width: 100%; }
.more-filters-panel summary { cursor: pointer; font-size: 0.85rem; color: var(--text-secondary); padding: 0.25rem 0; }
.more-filters-grid { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; }
.more-filters-grid input, .more-filters-grid select { min-width: 160px; }
</style>
```

- [ ] **Step 2: Add `secondary_filters_active` to the route in `routes/shop_books.py`**

In `shop_books_page()`, add to the return context dict:

```python
"secondary_filters_active": bool(author or publisher or category or type or format or missing),
```

- [ ] **Step 3: Smoke-test**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v -k "shop_book"
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/templates/shop_books.html \
        book_scraper/dashboard/routes/shop_books.py
git commit -m "feat: hide secondary shop book filters behind More Filters toggle"
```

---

## Task 5: Field History Timestamps + Click-to-Filter Change History

**Files:**
- Modify: `book_scraper/dashboard/queries.py`
- Modify: `book_scraper/dashboard/routes/shop_books.py`
- Modify: `book_scraper/dashboard/templates/shop_book_detail.html`
- Test: `tests/integration/test_db_repo_extra.py`

- [ ] **Step 1: Write failing tests for `get_field_history()`**

In `tests/integration/test_db_repo_extra.py`, add:

```python
def test_get_field_history_returns_first_and_last(db_session, shop):
    """get_field_history returns first_seen_at and changed_at per field."""
    from datetime import UTC, datetime, timedelta
    from book_scraper.dashboard.queries import get_field_history
    from book_scraper.db.models import ShopBook, ShopBookChange, ShopBookFieldUpdate

    sb = ShopBook(
        shop_id=shop.id, url="https://example.com/b1", title="Book",
        in_stock=True, first_seen_at=datetime.now(UTC) - timedelta(days=10),
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(sb)
    db_session.flush()

    # Add a change record: author was set from None
    change1 = ShopBookChange(
        shop_book_id=sb.id, field="author",
        old_value=None, new_value="Alice",
        changed_at=datetime.now(UTC) - timedelta(days=9),
    )
    db_session.add(change1)

    # Add field update record
    update = ShopBookFieldUpdate(
        shop_book_id=sb.id, field="author",
        updated_at=datetime.now(UTC) - timedelta(days=2),
    )
    db_session.add(update)
    db_session.flush()

    history = get_field_history(db_session, sb.id)
    assert "author" in history
    assert history["author"]["changed_at"] is not None
    assert history["author"]["first_seen_at"] is not None


def test_get_field_history_no_changes(db_session, shop):
    """get_field_history returns empty dict for book with no changes."""
    from datetime import UTC, datetime
    from book_scraper.dashboard.queries import get_field_history
    from book_scraper.db.models import ShopBook

    sb = ShopBook(
        shop_id=shop.id, url="https://example.com/b2", title="Book2",
        in_stock=True, first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
    )
    db_session.add(sb)
    db_session.flush()

    history = get_field_history(db_session, sb.id)
    assert history == {}
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/integration/test_db_repo_extra.py -v -k "field_history"
```

Expected: `ImportError` — `get_field_history` not defined.

- [ ] **Step 3: Add `get_field_history()` to `queries.py`**

After `get_field_updates()` (around line 374), add:

```python
def get_field_history(
    session: Session, shop_book_id: int
) -> dict[str, dict[str, "datetime | None"]]:
    """Return {field: {first_seen_at, changed_at}} for a shop_book's tracked fields.

    first_seen_at: earliest ShopBookChange where old_value IS NULL (field was set for first time).
    changed_at: ShopBookFieldUpdate.updated_at (last time the field changed).
    If a field has a ShopBookFieldUpdate but no change with old_value=None,
    first_seen_at falls back to the shop_book's first_seen_at.
    """
    from sqlalchemy import func

    # Last changed timestamps from ShopBookFieldUpdate
    updates = (
        session.query(ShopBookFieldUpdate)
        .filter(ShopBookFieldUpdate.shop_book_id == shop_book_id)
        .all()
    )
    if not updates:
        return {}

    changed_map: dict[str, datetime] = {r.field: r.updated_at for r in updates}

    # Earliest "field set from None" change per field
    first_set_rows = (
        session.query(
            ShopBookChange.field,
            func.min(ShopBookChange.changed_at).label("first_at"),
        )
        .filter(
            ShopBookChange.shop_book_id == shop_book_id,
            ShopBookChange.old_value.is_(None),
        )
        .group_by(ShopBookChange.field)
        .all()
    )
    first_set_map: dict[str, datetime] = {r.field: r.first_at for r in first_set_rows}

    # Fallback: shop_book.first_seen_at
    from book_scraper.db.models import ShopBook as _ShopBook
    sb = session.get(_ShopBook, shop_book_id)
    fallback = sb.first_seen_at if sb else None

    result: dict[str, dict[str, datetime | None]] = {}
    for field, changed_at in changed_map.items():
        result[field] = {
            "first_seen_at": first_set_map.get(field, fallback),
            "changed_at": changed_at,
        }
    return result
```

Also add the `datetime` import at the top of the function's return type annotation — it's already imported at the top of `queries.py`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_db_repo_extra.py -v -k "field_history"
```

Expected: PASS.

- [ ] **Step 5: Update `shop_book_detail()` route in `routes/shop_books.py`**

Import and use `get_field_history`:

```python
from book_scraper.dashboard.queries import (
    ...
    get_field_history,
    ...
)
```

In `shop_book_detail()`, replace:

```python
field_updates = get_field_updates(session, shop_book_id)
```

with:

```python
field_updates = get_field_updates(session, shop_book_id)
field_history = get_field_history(session, shop_book_id)
```

And add to the template context:

```python
"field_history": field_history,
```

- [ ] **Step 6: Update `changed()` macro in `shop_book_detail.html`**

Replace the `changed()` macro (lines 36-39):

```html
{% macro changed(field) %}
    {% set ts = field_updates.get(field) if field_updates else None %}
    {% if ts %}<div class="text-muted"><small>changed {{ ts.strftime('%Y-%m-%d') }}</small></div>{% endif %}
{% endmacro %}
```

With:

```html
{% macro changed(field) %}
    {% set h = field_history.get(field) if field_history else None %}
    {% if h %}
    <div class="text-muted" style="font-size:0.75rem; margin-top:0.2rem; display:flex; gap:0.75rem;">
        {% if h.first_seen_at %}
        <span title="{{ h.first_seen_at.strftime('%Y-%m-%d %H:%M UTC') }}">
            added {{ h.first_seen_at|relative_time }}
        </span>
        {% endif %}
        {% if h.changed_at %}
        <span title="{{ h.changed_at.strftime('%Y-%m-%d %H:%M UTC') }}">
            changed {{ h.changed_at|relative_time }}
        </span>
        {% endif %}
    </div>
    {% endif %}
{% endmacro %}
```

- [ ] **Step 7: Add `changed()` call to Original Price row**

In `shop_book_detail.html`, find the Original Price row (around line 112):

```html
<tr>
    <th>Original Price</th>
    <td>{% if shop_book.price_original %}{{ shop_book.price_original }}{% else %}<span class="text-muted">—</span>{% endif %}</td>
</tr>
```

Replace with:

```html
<tr>
    <th>Original Price</th>
    <td>{% if shop_book.price_original %}{{ shop_book.price_original }}{% else %}<span class="text-muted">—</span>{% endif %}{{ changed('price_original') }}</td>
</tr>
```

- [ ] **Step 8: Add click-to-filter JS for Change History**

Add a JS snippet and field filter chip at the bottom of `shop_book_detail.html`, before the existing `<script>` tag for the price chart:

```html
<script>
(function() {
    // Click-to-filter in Change History table
    const fieldCells = document.querySelectorAll('.change-history-field');
    const changeRows = document.querySelectorAll('.change-history-row');
    let activeField = null;

    fieldCells.forEach(function(cell) {
        cell.style.cursor = 'pointer';
        cell.title = 'Click to filter by this field';
        cell.addEventListener('click', function() {
            const field = cell.dataset.field;
            if (activeField === field) {
                // toggle off
                activeField = null;
                changeRows.forEach(function(row) { row.style.display = ''; });
                cell.style.fontWeight = '';
                document.getElementById('change-field-chip').style.display = 'none';
            } else {
                activeField = field;
                changeRows.forEach(function(row) {
                    row.style.display = row.dataset.field === field ? '' : 'none';
                });
                // reset bold on all
                fieldCells.forEach(function(c) { c.style.fontWeight = ''; });
                cell.style.fontWeight = 'bold';
                const chip = document.getElementById('change-field-chip');
                chip.style.display = 'inline-flex';
                chip.querySelector('.chip-label').textContent = 'Field: ' + field;
            }
        });
    });

    const chip = document.getElementById('change-field-chip');
    if (chip) {
        chip.querySelector('.chip-remove').addEventListener('click', function() {
            activeField = null;
            changeRows.forEach(function(row) { row.style.display = ''; });
            fieldCells.forEach(function(c) { c.style.fontWeight = ''; });
            chip.style.display = 'none';
        });
    }
})();
</script>
```

Also update the Change History table markup to add the data attributes and chip container. Find the Change History section and update it:

```html
<div class="card" style="padding: 0; overflow: hidden;">
    <div class="card-title" style="padding: 1rem 1.25rem 0; display:flex; align-items:center; gap:0.75rem;">
        Change History
        <span id="change-field-chip" class="filter-badge" style="display:none;">
            <span class="chip-label"></span>
            <a href="#" class="chip-remove" style="cursor:pointer;">✕</a>
        </span>
    </div>
    {% if changes %}
    <table class="data-table">
        <thead>
            <tr>
                <th>Date</th>
                <th>Field</th>
                <th>Change</th>
                <th>Run</th>
            </tr>
        </thead>
        <tbody>
            {% for c in changes %}
            <tr class="change-history-row" data-field="{{ c.field }}">
                <td class="text-muted">{{ c.changed_at.strftime('%Y-%m-%d %H:%M') }}</td>
                <td class="change-history-field" data-field="{{ c.field }}">{{ c.field }}</td>
                <td class="change-diff-cell">
                    {% if c.field == 'description' %}
                    <details class="change-diff">
                        <summary>Description changed — click to view diff</summary>
                        <div class="change-diff-body">{{ change_diff(c.old_value, c.new_value, 999999) }}</div>
                    </details>
                    {% else %}
                    {{ change_diff(c.old_value, c.new_value, 200) }}
                    {% endif %}
                </td>
                <td>{% if c.scrape_run_id %}<a href="/runs/{{ c.scrape_run_id }}">Run #{{ c.scrape_run_id }}</a>{% else %}<span class="text-muted">—</span>{% endif %}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p class="text-muted" style="padding: 1rem 1.25rem;">No changes recorded yet. Changes will appear after the next scrape.</p>
    {% endif %}
</div>
```

Note: This also supersedes the description diff change from Task 2 — the template now has both.

- [ ] **Step 9: Smoke-test**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v -k "shop_book_detail"
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add book_scraper/dashboard/queries.py \
        book_scraper/dashboard/routes/shop_books.py \
        book_scraper/dashboard/templates/shop_book_detail.html \
        tests/integration/test_db_repo_extra.py
git commit -m "feat: show field added/changed timestamps, click-to-filter change history"
```

---

## Task 6: Filter Shop Books by Attribute

**Files:**
- Modify: `book_scraper/dashboard/queries.py`
- Modify: `book_scraper/dashboard/routes/shop_books.py`
- Modify: `book_scraper/dashboard/templates/shop_books.html`
- Test: `tests/integration/test_shop_books_filter_sort.py`

- [ ] **Step 1: Write failing tests**

In `tests/integration/test_shop_books_filter_sort.py`, add:

```python
def test_get_attribute_keys(db_session, shop_with_books_and_attrs):
    """get_attribute_keys returns distinct attribute key names."""
    from book_scraper.dashboard.queries import get_attribute_keys
    keys = get_attribute_keys(db_session)
    assert "cover_type" in keys
    assert "pages" in keys


def test_get_attribute_values(db_session, shop_with_books_and_attrs):
    """get_attribute_values returns distinct values for a given key."""
    from book_scraper.dashboard.queries import get_attribute_values
    values = get_attribute_values(db_session, "cover_type")
    assert len(values) > 0
    for v in values:
        assert isinstance(v, str)


def test_filter_by_attribute(db_session, shop_with_books_and_attrs):
    """get_shop_books_page filters by attribute key+value."""
    from book_scraper.dashboard.queries import get_shop_books_page
    books, total = get_shop_books_page(db_session, attr_key="cover_type", attr_value="Hardcover")
    assert total > 0
    for book in books:
        attrs = {a.key: a.value for a in book.attributes}
        assert attrs.get("cover_type") == "Hardcover"


def test_filter_by_attribute_key_only(db_session, shop_with_books_and_attrs):
    """Filtering by attr_key only (no value) returns books that have that attribute."""
    from book_scraper.dashboard.queries import get_shop_books_page
    books, total = get_shop_books_page(db_session, attr_key="pages")
    assert total > 0
    for book in books:
        keys = {a.key for a in book.attributes}
        assert "pages" in keys
```

(If `shop_with_books_and_attrs` fixture doesn't exist, create it in the test file or conftest. It should create a shop with 3 shop_books, two of which have `cover_type=Hardcover` and one with `cover_type=Softcover`, and two with `pages=200`.)

- [ ] **Step 2: Add fixture `shop_with_books_and_attrs` if missing**

Check if the fixture exists:

```bash
grep -n "shop_with_books_and_attrs" tests/integration/test_shop_books_filter_sort.py
```

If not found, add at the top of the test file:

```python
@pytest.fixture
def shop_with_books_and_attrs(db_session):
    from book_scraper.db.models import Shop, ShopBook, ShopBookAttribute
    shop = Shop(name="test_attr_shop", base_url="https://test.com")
    db_session.add(shop)
    db_session.flush()
    books_data = [
        ("Book One", "Hardcover", "200"),
        ("Book Two", "Hardcover", "350"),
        ("Book Three", "Softcover", None),
    ]
    for title, cover_type, pages in books_data:
        sb = ShopBook(
            shop_id=shop.id, url=f"https://test.com/{title.lower().replace(' ','-')}",
            title=title, in_stock=True,
        )
        db_session.add(sb)
        db_session.flush()
        db_session.add(ShopBookAttribute(shop_book_id=sb.id, key="cover_type", value=cover_type))
        if pages:
            db_session.add(ShopBookAttribute(shop_book_id=sb.id, key="pages", value=pages))
    db_session.flush()
    return shop
```

- [ ] **Step 3: Run tests to confirm failure**

```bash
uv run pytest tests/integration/test_shop_books_filter_sort.py -v -k "attribute"
```

Expected: `TypeError` — unexpected keyword argument `attr_key`.

- [ ] **Step 4: Add `get_attribute_keys()` and `get_attribute_values()` to `queries.py`**

After `get_all_formats()`:

```python
def get_attribute_keys(
    session: Session, shop_id: int | None = None
) -> list[str]:
    """Return distinct attribute keys across all shop_books (or for one shop)."""
    from book_scraper.db.models import ShopBookAttribute

    query = session.query(ShopBookAttribute.key).distinct()
    if shop_id is not None:
        query = query.join(ShopBook, ShopBookAttribute.shop_book_id == ShopBook.id).filter(
            ShopBook.shop_id == shop_id
        )
    return sorted(r[0] for r in query.all())


def get_attribute_values(
    session: Session, key: str, shop_id: int | None = None
) -> list[str]:
    """Return distinct non-null attribute values for a given key."""
    from book_scraper.db.models import ShopBookAttribute

    query = (
        session.query(ShopBookAttribute.value)
        .filter(ShopBookAttribute.key == key, ShopBookAttribute.value.isnot(None))
        .distinct()
    )
    if shop_id is not None:
        query = query.join(ShopBook, ShopBookAttribute.shop_book_id == ShopBook.id).filter(
            ShopBook.shop_id == shop_id
        )
    return sorted(r[0] for r in query.all())
```

- [ ] **Step 5: Add `attr_key` and `attr_value` to `get_shop_books_page()`**

Add to the signature:

```python
def get_shop_books_page(
    session: Session,
    ...
    attr_key: str = "",
    attr_value: str = "",
) -> tuple[list[ShopBook], int]:
```

Add filtering logic after the `has_isbn` block:

```python
    if attr_key:
        from book_scraper.db.models import ShopBookAttribute
        from sqlalchemy import exists

        attr_subq = session.query(ShopBookAttribute).filter(
            ShopBookAttribute.shop_book_id == ShopBook.id,
            ShopBookAttribute.key == attr_key,
        )
        if attr_value:
            attr_subq = attr_subq.filter(ShopBookAttribute.value == attr_value)
        query = query.filter(exists(attr_subq))
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_shop_books_filter_sort.py -v -k "attribute"
```

Expected: PASS.

- [ ] **Step 7: Update `shop_books_page()` route**

Add `attr_key: str = ""` and `attr_value: str = ""` to the route function signature.

Pass them to `get_shop_books_page()`:

```python
shop_books, total = get_shop_books_page(
    session,
    ...
    attr_key=attr_key,
    attr_value=attr_value,
)
```

Add attribute_keys and values to the context (call `get_attribute_keys()` and conditionally `get_attribute_values()`):

```python
from book_scraper.dashboard.queries import (
    ...
    get_attribute_keys,
    get_attribute_values,
)
...
attribute_keys = get_attribute_keys(session, shop_id=shop_id)
attribute_values = get_attribute_values(session, attr_key, shop_id=shop_id) if attr_key else []
```

Add to `filter_params` dict:

```python
"attr_key": attr_key,
"attr_value": attr_value,
```

Add to `has_visible_filters`:

```python
has_visible_filters = any([
    q, author, publisher, category, type, format, missing, shop, has_isbn,
    active != "true", bool(field_filters), attr_key, attr_value,
])
```

Add filter badge for attr_key/attr_value:

```python
if attr_key:
    label = f"Attr: {attr_key}" + (f"={attr_value}" if attr_value else " (any)")
    params = dict(filter_and_sort_params)
    params.pop("attr_key", None)
    params.pop("attr_value", None)
    filter_badges.append({"label": label, "remove_url": _build_shop_books_url(params)})
```

Add to template context:

```python
"attr_key": attr_key,
"attr_value": attr_value,
"attribute_keys": attribute_keys,
"attribute_values": attribute_values,
"secondary_filters_active": bool(author or publisher or category or type or format or missing or attr_key),
```

- [ ] **Step 8: Add attribute filter to `shop_books.html`**

Inside the `.more-filters-grid` `<details>` block (added in Task 4), add after the missing `<select>`:

```html
                <select name="attr_key" id="attr_key_select" onchange="this.form.submit()">
                    <option value="">All attributes</option>
                    {% for key in attribute_keys %}
                    <option value="{{ key }}" {{ 'selected' if attr_key == key else '' }}>{{ key }}</option>
                    {% endfor %}
                </select>
                {% if attr_key %}
                <select name="attr_value">
                    <option value="">Any value</option>
                    {% for val in attribute_values %}
                    <option value="{{ val }}" {{ 'selected' if attr_value == val else '' }}>{{ val }}</option>
                    {% endfor %}
                </select>
                {% endif %}
```

- [ ] **Step 9: Smoke-test**

```bash
uv run pytest tests/integration/test_dashboard_routes.py tests/integration/test_shop_books_filter_sort.py -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add book_scraper/dashboard/queries.py \
        book_scraper/dashboard/routes/shop_books.py \
        book_scraper/dashboard/templates/shop_books.html \
        tests/integration/test_shop_books_filter_sort.py
git commit -m "feat: filter shop books by attribute key/value"
```

---

## Task 7: Maximize Data Extraction from Discover Spider

**Files:**
- Modify: `book_scraper/spiders/discover.py`
- Test: `tests/unit/test_spiders.py`

- [ ] **Step 1: Write failing tests for `parse_categories` yielding `ShopBookItem`**

Open `tests/unit/test_spiders.py` and add:

```python
def test_parse_categories_yields_shop_book_item(fake_category_response, discover_spider):
    """parse_categories yields ShopBookItem (not PriceItem) when price is available."""
    from book_scraper.items import ShopBookItem, PriceItem
    items = list(discover_spider.parse_categories(fake_category_response))
    shop_book_items = [i for i in items if isinstance(i, ShopBookItem)]
    price_items = [i for i in items if isinstance(i, PriceItem)]
    assert len(shop_book_items) > 0, "Expected at least one ShopBookItem"
    assert len(price_items) == 0, "Should not yield PriceItem anymore"
    item = shop_book_items[0]
    assert item["url"]
    assert item["title"]
    assert item["price"] is not None


def test_parse_full_crawl_yields_shop_book_for_product_url(
    fake_product_response, discover_spider_with_product_url_pattern
):
    """parse_full_crawl yields ShopBookItem when the current URL matches product pattern."""
    from book_scraper.items import ShopBookItem
    items = list(discover_spider_with_product_url_pattern.parse_full_crawl(fake_product_response))
    shop_book_items = [i for i in items if isinstance(i, ShopBookItem)]
    assert len(shop_book_items) > 0, "Expected ShopBookItem for product URL"
```

(These tests use `discover_spider` and fixture helpers from the existing `test_spiders.py`. Review existing fixtures in that file and adapt — the key fixture is a fake Scrapy response with category-page HTML, and a discover spider pointed at the vaga shop.)

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_spiders.py -v -k "categories_yields_shop_book or full_crawl_yields_shop_book"
```

Expected: FAIL — currently `parse_categories` yields `PriceItem`, not `ShopBookItem`.

- [ ] **Step 3: Update `parse_categories()` in `discover.py` to yield `ShopBookItem`**

Add `ShopBookItem` to the import in `discover.py`:

```python
from book_scraper.items import DiscoveredUrlItem, PriceItem, ShopBookItem
```

In `parse_categories()`, replace the `PriceItem` yield block:

```python
            # Also yield price data if available
            if product.get("price"):
                yield PriceItem(
                    url=url,
                    shop_name=self.shop_name,
                    title=product.get("title", ""),
                    author=product.get("author"),
                    price=product.get("price"),
                    price_original=product.get("price_original"),
                    in_stock=True,
                )
```

With:

```python
            # Yield product data when we have at least a title and price
            if product.get("title") and product.get("price"):
                yield ShopBookItem(
                    url=url,
                    shop_name=self.shop_name,
                    title=product["title"],
                    author=product.get("author"),
                    price=product.get("price"),
                    price_original=product.get("price_original"),
                    in_stock=True,
                    type=None,
                    sku=None,
                    isbn=None,
                    publisher=None,
                    year=None,
                    format=None,
                    description=None,
                    image_url=product.get("image_url"),
                    categories=product.get("categories", []),
                    properties=None,
                )
```

- [ ] **Step 4: Update `parse_full_crawl()` in `discover.py` to extract product data**

In the `parse_full_crawl()` method, add product-page parsing for matching URLs. Insert this block at the beginning of the method body (after the seen-set setup but before the link-following loop):

```python
    def parse_full_crawl(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem | ShopBookItem | scrapy.Request, None, None]:
        """Follow all internal links, yield product URLs and parse product data."""
        base_url: str = self.conf.shop.base_url
        seen: set[str] = getattr(self, "_seen_urls", set())
        self._seen_urls = seen
        if self._max_pages and len(seen) >= self._max_pages:
            return

        # If the current page matches the product URL pattern, extract product data
        current_url = response.url.split("?")[0]
        if self._url_passes_filter(current_url):
            data = self.parsers.parse_product_page(response.text)
            if data.get("title"):
                props: dict[str, object] = {}
                for key in ("pages", "cover_type", "duration", "narrator", "translator"):
                    if data.get(key) is not None:
                        props[key] = data[key]
                yield ShopBookItem(
                    url=current_url,
                    shop_name=self.shop_name,
                    type=data.get("type"),
                    title=data["title"],
                    author=data.get("author"),
                    sku=data.get("sku"),
                    isbn=data.get("isbn"),
                    publisher=data.get("publisher"),
                    year=data.get("year"),
                    format=data.get("format"),
                    description=data.get("description"),
                    image_url=data.get("image_url"),
                    categories=data.get("categories", []),
                    properties=props or None,
                    price=data.get("price"),
                    price_original=data.get("price_original"),
                    in_stock=data.get("in_stock"),
                )

        for link in response.css("a::attr(href)").getall():
            ...  # rest of the existing link-following code unchanged
```

(Keep the existing link-following loop intact.)

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_spiders.py -v
```

Expected: existing tests still PASS, new tests PASS.

- [ ] **Step 6: Commit**

```bash
git add book_scraper/spiders/discover.py tests/unit/test_spiders.py
git commit -m "feat: yield ShopBookItem from discover spider (categories + full_crawl)"
```

---

## Task 8: Persistent Scraping Pipeline Queue (`scrape_url_items`)

**Files:**
- Modify: `book_scraper/db/models.py`
- Create: `alembic/versions/<hash>_add_scrape_url_items_table.py`
- Modify: `book_scraper/db/repo.py`
- Modify: `book_scraper/services/scan.py`
- Modify: `book_scraper/spiders/scan.py`
- Test: `tests/integration/test_scan_service.py`

### Sub-task 8a: Model + Migration

- [ ] **Step 1: Add `ScrapeUrlItem` model to `models.py`**

In `book_scraper/db/models.py`, add after the `ScrapeRun` class:

```python
scrape_url_status_enum = Enum(
    "pending", "processing", "done", "failed",
    name="scrape_url_status",
    create_type=False,
)


class ScrapeUrlItem(Base):
    """Persistent work-queue item for the scan spider.

    Written by ScanService.prepare_scan() before scraping begins.
    Allows the spider to resume after a crash: any 'processing' rows
    from a previous run are reset to 'pending' on next start.
    """

    __tablename__ = "scrape_url_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), nullable=False)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    discovered_url_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovered_urls.id"), nullable=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        scrape_url_status_enum, nullable=False, server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_scrape_url_items_run_status", "run_id", "status"),
    )
```

Also add `scrape_url_status_enum` to the imports pattern that `Enum` is already imported from sqlalchemy, and `Index` too.

- [ ] **Step 2: Generate Alembic migration**

```bash
cd /Users/evaldas/Projects/book-scraper
PYTHONPATH=. uv run alembic revision --autogenerate -m "add_scrape_url_items_table"
```

Review the generated file in `alembic/versions/` to confirm it creates:
- The `scrape_url_status` enum type
- The `scrape_url_items` table with correct columns and index

Edit the migration if autogenerate missed the enum (add manually):

```python
def upgrade() -> None:
    sa.Enum("pending", "processing", "done", "failed", name="scrape_url_status").create(op.get_bind())
    op.create_table(
        "scrape_url_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("discovered_url_id", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("pending", "processing", "done", "failed", name="scrape_url_status"), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["scrape_runs.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["discovered_url_id"], ["discovered_urls.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scrape_url_items_run_status", "scrape_url_items", ["run_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_scrape_url_items_run_status", table_name="scrape_url_items")
    op.drop_table("scrape_url_items")
    sa.Enum(name="scrape_url_status").drop(op.get_bind())
```

- [ ] **Step 3: Apply migration to test DB**

```bash
PYTHONPATH=. uv run alembic upgrade head
```

Expected: migration applies without error.

### Sub-task 8b: Repo Functions

- [ ] **Step 4: Write failing repo tests**

In `tests/integration/test_scan_service.py`, add:

```python
def test_prepare_scrape_url_items_inserts_rows(db_session, shop, scrape_run, discovered_urls):
    """prepare_scrape_url_items inserts pending rows into scrape_url_items."""
    from book_scraper.db.repo import prepare_scrape_url_items, get_pending_scrape_url_items

    url_records = discovered_urls[:3]
    prepare_scrape_url_items(db_session, shop.id, scrape_run.id, url_records)
    db_session.commit()

    items = get_pending_scrape_url_items(db_session, scrape_run.id)
    assert len(items) == 3
    urls = {item["url"] for item in items}
    assert urls == {u.url for u in url_records}


def test_get_pending_skips_done_items(db_session, shop, scrape_run, discovered_urls):
    """get_pending_scrape_url_items returns only 'pending' items."""
    from book_scraper.db.repo import (
        prepare_scrape_url_items,
        get_pending_scrape_url_items,
        mark_scrape_url_item_done,
    )

    url_records = discovered_urls[:3]
    prepare_scrape_url_items(db_session, shop.id, scrape_run.id, url_records)
    db_session.commit()

    items = get_pending_scrape_url_items(db_session, scrape_run.id)
    mark_scrape_url_item_done(db_session, items[0]["id"])
    db_session.commit()

    remaining = get_pending_scrape_url_items(db_session, scrape_run.id)
    assert len(remaining) == 2


def test_reset_stale_processing_items(db_session, shop, scrape_run, discovered_urls):
    """reset_processing_scrape_url_items resets 'processing' rows back to 'pending'."""
    from book_scraper.db.repo import (
        prepare_scrape_url_items,
        get_pending_scrape_url_items,
        reset_processing_scrape_url_items,
    )
    from book_scraper.db.models import ScrapeUrlItem

    url_records = discovered_urls[:2]
    prepare_scrape_url_items(db_session, shop.id, scrape_run.id, url_records)
    db_session.commit()

    # Manually set one to 'processing' (simulates a crashed mid-run)
    item = db_session.query(ScrapeUrlItem).filter_by(run_id=scrape_run.id).first()
    item.status = "processing"
    db_session.commit()

    reset_processing_scrape_url_items(db_session, scrape_run.id)
    db_session.commit()

    pending = get_pending_scrape_url_items(db_session, scrape_run.id)
    assert len(pending) == 2  # both are pending again
```

- [ ] **Step 5: Run to confirm failure**

```bash
uv run pytest tests/integration/test_scan_service.py -v -k "scrape_url"
```

Expected: `ImportError` or `AttributeError`.

- [ ] **Step 6: Add repo functions to `db/repo.py`**

Import `ScrapeUrlItem` at the top of `repo.py`:

```python
from book_scraper.db.models import (
    ...
    ScrapeUrlItem,
)
```

Add functions near the end of `repo.py`:

```python
# --- Scrape URL Items ---


def prepare_scrape_url_items(
    session: Session,
    shop_id: int,
    run_id: int,
    url_records: list["DiscoveredUrl"],
) -> None:
    """Insert pending scrape_url_items for a new scan run.

    Call before yielding requests; allows crash-resume.
    """
    for rec in url_records:
        session.add(
            ScrapeUrlItem(
                run_id=run_id,
                shop_id=shop_id,
                discovered_url_id=rec.id,
                url=rec.url,
                status="pending",
            )
        )
    session.flush()


def get_pending_scrape_url_items(
    session: Session, run_id: int
) -> list[dict[str, Any]]:
    """Return all pending items for a run as dicts {id, url, discovered_url_id}."""
    rows = (
        session.query(ScrapeUrlItem)
        .filter(ScrapeUrlItem.run_id == run_id, ScrapeUrlItem.status == "pending")
        .all()
    )
    return [
        {
            "id": r.id,
            "url": r.url,
            "discovered_url_id": r.discovered_url_id,
        }
        for r in rows
    ]


def mark_scrape_url_item_done(session: Session, item_id: int) -> None:
    """Mark a scrape_url_item as done."""
    item = session.get(ScrapeUrlItem, item_id)
    if item:
        item.status = "done"
        item.done_at = datetime.now(UTC)
        session.flush()


def mark_scrape_url_item_failed(session: Session, item_id: int) -> None:
    """Mark a scrape_url_item as failed."""
    item = session.get(ScrapeUrlItem, item_id)
    if item:
        item.status = "failed"
        item.done_at = datetime.now(UTC)
        session.flush()


def reset_processing_scrape_url_items(session: Session, run_id: int) -> int:
    """Reset 'processing' items back to 'pending' (for crash recovery).

    Returns the number of items reset.
    """
    items = (
        session.query(ScrapeUrlItem)
        .filter(ScrapeUrlItem.run_id == run_id, ScrapeUrlItem.status == "processing")
        .all()
    )
    for item in items:
        item.status = "pending"
        item.claimed_at = None
    session.flush()
    return len(items)


def has_existing_scrape_url_items(session: Session, run_id: int) -> bool:
    """Return True if this run already has scrape_url_items (crash-resume path)."""
    return (
        session.query(ScrapeUrlItem)
        .filter(ScrapeUrlItem.run_id == run_id)
        .limit(1)
        .count()
        > 0
    )
```

- [ ] **Step 7: Run repo tests to verify they pass**

```bash
uv run pytest tests/integration/test_scan_service.py -v -k "scrape_url"
```

Expected: PASS.

### Sub-task 8c: ScanService Refactor

- [ ] **Step 8: Refactor `ScanPlan` and `prepare_scan()` in `services/scan.py`**

Update `ScanPlan` dataclass to remove `urls_to_scrape` (now persisted to DB):

```python
@dataclass
class ScanPlan:
    run_id: int
    urls_total: int
    urls_skipped: int
    freshness_warnings: list[str] = field(default_factory=list)
```

Update imports in `services/scan.py`:

```python
from book_scraper.db.repo import (
    check_discover_freshness,
    create_scrape_run,
    finish_scrape_run,
    get_pending_scan_urls,
    get_urls_already_scraped,
    mark_stale_runs_failed,
    prepare_scrape_url_items,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_shop,
)
```

Update `prepare_scan()`:

```python
    def prepare_scan(
        self,
        shop_name: str,
        base_url: str,
        shop_config: Any,
        rescrape: bool = False,
    ) -> ScanPlan:
        """Prepare a scan run: upsert shop, mark stale, check freshness,
        load pending URLs, filter already done, persist to scrape_url_items, create run."""
        shop = upsert_shop(self.session, shop_name, base_url)

        mark_stale_runs_failed(self.session, shop.id, "scan")

        if isinstance(shop_config, dict):
            discover_config = shop_config.get("discover", {})
        else:
            discover_config = shop_config.discover
        warnings = check_discover_freshness(
            self.session, shop.id, shop_name, discover_config
        )

        pending_urls = get_pending_scan_urls(self.session, shop.id)

        if rescrape:
            urls_to_scrape = pending_urls
            urls_skipped = 0
        else:
            already_done = get_urls_already_scraped(self.session, shop.id)
            urls_to_scrape = [u for u in pending_urls if u.url not in already_done]
            urls_skipped = len(pending_urls) - len(urls_to_scrape)

        run = create_scrape_run(
            self.session, shop.id, "scan", urls_total=len(urls_to_scrape)
        )
        # Persist work queue to DB for crash recovery
        prepare_scrape_url_items(self.session, shop.id, run.id, urls_to_scrape)
        self.session.commit()

        return ScanPlan(
            run_id=run.id,
            urls_total=len(urls_to_scrape),
            urls_skipped=urls_skipped,
            freshness_warnings=warnings,
        )
```

- [ ] **Step 9: Refactor `ScanSpider.start()` to read from `scrape_url_items`**

Update `book_scraper/spiders/scan.py` to use the new repo functions:

```python
from book_scraper.db.repo import (
    increment_scrape_run_stats,
    get_pending_scrape_url_items,
    mark_scrape_url_item_done,
    mark_scrape_url_item_failed,
    reset_processing_scrape_url_items,
)
```

Change `_url_status_updates` to also track scrape_url_item_id. Update the `_queue_url_status_update()` method signature:

```python
    def _queue_url_status_update(
        self,
        url_id: int | None,
        http_status: int | None = None,
        url_type: str | None = None,
        increment_fail: bool = False,
        scrape_url_item_id: int | None = None,
        success: bool = False,
    ) -> None:
        """Queue a URL status update and flush periodically."""
        if url_id is None and scrape_url_item_id is None:
            return
        update: dict[str, Any] = {
            "url_id": url_id,
            "http_status": http_status,
            "url_type": url_type,
            "increment_fail": increment_fail,
        }
        if scrape_url_item_id is not None:
            update["scrape_url_item_id"] = scrape_url_item_id
            update["scrape_url_item_success"] = success
        self._url_status_updates.append(update)
        self._urls_responded += 1
        if self._urls_responded % self._flush_every == 0:
            self._flush_progress()
```

Update `start()` in the non-single-URL path to read from `scrape_url_items`:

```python
        try:
            service = ScanService(session)
            plan = service.prepare_scan(
                self.shop_name,
                self.conf.shop.base_url,
                self.conf,
                rescrape=self._rescrape,
            )
            self._run_id = plan.run_id

            for warning in plan.freshness_warnings:
                self.logger.warning(warning)

            # Load work queue from DB (supports crash-resume)
            reset_processing_scrape_url_items(session, plan.run_id)
            url_items = get_pending_scrape_url_items(session, plan.run_id)
            session.commit()

            if self._max_urls and len(url_items) > self._max_urls:
                self.logger.info(
                    "max_urls cap: scraping %d of %d planned URLs",
                    self._max_urls,
                    len(url_items),
                )
                url_items = url_items[: self._max_urls]

            total = len(url_items)
            self.logger.info(
                "Scan starting: %d URLs (%d skipped). Pacing via Scrapy "
                "CONCURRENT_REQUESTS_PER_DOMAIN + DOWNLOAD_DELAY + AUTOTHROTTLE.",
                total,
                plan.urls_skipped,
            )

            for item in url_items:
                yield scrapy.Request(
                    item["url"],
                    callback=self.parse_product,
                    errback=self.handle_error,
                    meta={
                        "discovered_url_id": item["discovered_url_id"],
                        "scrape_url_item_id": item["id"],
                    },
                )
```

Update `parse_product()` to pass `scrape_url_item_id` to `_queue_url_status_update`:

```python
    def parse_product(self, response):
        discovered_url_id = response.meta.get("discovered_url_id")
        scrape_url_item_id = response.meta.get("scrape_url_item_id")
        ...
        # In all _queue_url_status_update calls, add:
        self._queue_url_status_update(
            discovered_url_id,
            http_status=response.status,
            increment_fail=True,
            scrape_url_item_id=scrape_url_item_id,
            success=False,
        )
        ...
        # On success:
        self._queue_url_status_update(
            discovered_url_id,
            http_status=200,
            url_type="product",
            scrape_url_item_id=scrape_url_item_id,
            success=True,
        )
```

Update `handle_error()` similarly to pass `scrape_url_item_id`.

Update `flush_progress()` in `ScanService` to also process `scrape_url_item` updates:

In `services/scan.py`, update `flush_progress()`:

```python
    def flush_progress(
        self,
        run_id: int,
        urls_processed: int,
        url_status_updates: list[dict[str, Any]],
    ) -> None:
        """Flush queued URL status updates and progress to DB mid-run."""
        from book_scraper.db.repo import mark_scrape_url_item_done, mark_scrape_url_item_failed

        for update in url_status_updates:
            scrape_item_id = update.pop("scrape_url_item_id", None)
            scrape_item_success = update.pop("scrape_url_item_success", False)
            update_discovered_url_status(self.session, **update)
            if scrape_item_id is not None:
                if scrape_item_success:
                    mark_scrape_url_item_done(self.session, scrape_item_id)
                else:
                    mark_scrape_url_item_failed(self.session, scrape_item_id)
        update_scrape_run_progress(self.session, run_id, urls_processed)
        self.session.commit()
```

Do the same for `finish_scan()`.

- [ ] **Step 10: Update existing `test_scan_service.py` tests that use `ScanPlan.urls_to_scrape`**

Run the existing scan service tests:

```bash
uv run pytest tests/integration/test_scan_service.py -v
```

Any test that does `plan.urls_to_scrape` must be updated to use `plan.urls_total` or to query `get_pending_scrape_url_items()` instead. Update those tests accordingly.

- [ ] **Step 11: Run full test suite**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -40
```

Expected: all tests PASS.

- [ ] **Step 12: Commit**

```bash
git add book_scraper/db/models.py \
        book_scraper/db/repo.py \
        book_scraper/services/scan.py \
        book_scraper/spiders/scan.py \
        tests/integration/test_scan_service.py \
        alembic/versions/
git commit -m "feat: add scrape_url_items table for persistent scan pipeline queue"
```

---

## Post-Implementation Checklist

- [ ] Rebuild both containers: `docker compose build dashboard scraper && docker compose up -d dashboard scraper`
- [ ] Smoke-test all routes: `uv run pytest tests/integration/test_dashboard_routes.py -v`
- [ ] Trigger short scan to verify scraper container works: `docker compose exec scraper scrapy crawl scan -a shop=vaga -a max_urls=5`
- [ ] Check `/shop-books` — relative timestamps, "More filters" toggle, attribute filter
- [ ] Check `/shop-books/<id>` — field history timestamps, click-to-filter in Change History, description diff collapsed
- [ ] Check `/validation` — severity dropdown
