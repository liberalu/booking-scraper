# Docker + Monitoring Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize the book scraper and add a web-based monitoring dashboard with scheduled scraping and on-demand triggers.

**Architecture:** Three Docker Compose services (postgres, scraper, dashboard) sharing a network. The scraper runs cron-scheduled Scrapy jobs. The dashboard is a FastAPI app with Jinja2/HTMX that reads from PostgreSQL and triggers scraper runs via Docker exec.

**Tech Stack:** Docker, FastAPI, Jinja2, HTMX, Chart.js, Pico CSS, Docker SDK for Python

---

## File Structure

### New files

```
Dockerfile                              # Multi-stage: base, scraper, dashboard targets
cron/scraper-crontab                    # Cron schedule for scraper container
scripts/entrypoint-scraper.sh           # Runs migrations + starts cron
scripts/entrypoint-dashboard.sh         # Runs migrations + starts uvicorn
book_scraper/dashboard/
    __init__.py
    app.py                              # FastAPI app setup, mounts routes
    deps.py                             # Session dependency, Docker client
    queries.py                          # Read-only DB query functions
    routes/
        __init__.py
        overview.py                     # GET /
        runs.py                         # GET /runs, GET /runs/{id}, POST /runs/trigger
        validation.py                   # GET /validation, GET /validation/{issue}
        prices.py                       # GET /prices, GET /api/prices/{id}/chart
        inventory.py                    # GET /inventory
        logs.py                         # GET /logs, GET /api/logs/stream
    templates/
        base.html                       # Layout with nav, HTMX, Pico CSS, Chart.js
        overview.html
        runs.html
        run_detail.html
        validation.html
        validation_detail.html
        prices.html
        inventory.html
        logs.html
tests/unit/test_dashboard_queries.py    # Unit tests for query functions
tests/unit/test_dashboard_routes.py     # FastAPI TestClient route tests
```

### Modified files

```
pyproject.toml                          # Add dashboard optional deps
docker-compose.yml                      # Add scraper + dashboard services
alembic/env.py                          # Support DATABASE_URL env var
config/default.toml                     # Note: DB URL overridden by env var in Docker
```

---

### Task 1: Add dashboard dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dashboard optional extra**

In `pyproject.toml`, add after the `dev` optional dependencies:

```toml
[project.optional-dependencies]
dashboard = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "jinja2>=3.1",
    "docker>=7.0",
]
```

- [ ] **Step 2: Install and verify**

Run: `uv sync --all-extras`
Expected: all deps installed without errors

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add dashboard dependencies (fastapi, uvicorn, jinja2, docker)"
```

---

### Task 2: Make alembic support DATABASE_URL env var

**Files:**
- Modify: `alembic/env.py`

- [ ] **Step 1: Update env.py to read DATABASE_URL**

Replace the `run_migrations_online` function in `alembic/env.py`. Add at the top of the file, after the existing imports:

```python
import os
```

Then replace the `run_migrations_online` function:

```python
def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    url = os.environ.get("DATABASE_URL")
    if url:
        # Ensure sync driver for migrations
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg2")
        connectable = create_engine(url, poolclass=pool.NullPool)
    else:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()
```

Add the `create_engine` import at the top:

```python
from sqlalchemy import create_engine
```

- [ ] **Step 2: Verify migrations still work locally**

Run: `PYTHONPATH=. uv run alembic current`
Expected: shows current head revision

Run: `PYTHONPATH=. DATABASE_URL=postgresql://postgres:postgres@localhost:5432/book_scraper uv run alembic current`
Expected: shows same head revision

- [ ] **Step 3: Commit**

```bash
git add alembic/env.py
git commit -m "feat: support DATABASE_URL env var in alembic migrations"
```

---

### Task 3: Dashboard app skeleton and dependencies module

**Files:**
- Create: `book_scraper/dashboard/__init__.py`
- Create: `book_scraper/dashboard/deps.py`
- Create: `book_scraper/dashboard/app.py`

- [ ] **Step 1: Create package init**

```python
# book_scraper/dashboard/__init__.py
```

(Empty file)

- [ ] **Step 2: Create deps.py with session dependency and Docker client**

```python
# book_scraper/dashboard/deps.py
import os
from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session

from book_scraper.db.session import get_session_factory

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper",
)

_session_factory = get_session_factory(DATABASE_URL)


def get_db() -> Generator[Session, None, None]:
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def get_docker_client() -> Any:
    """Get Docker client. Returns None if Docker is not available."""
    try:
        import docker

        return docker.from_env()
    except Exception:
        return None
```

- [ ] **Step 3: Create app.py with FastAPI setup**

```python
# book_scraper/dashboard/app.py
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from book_scraper.dashboard.routes import (
    inventory,
    logs,
    overview,
    prices,
    runs,
    validation,
)

app = FastAPI(title="Book Scraper Dashboard")

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.include_router(overview.router)
app.include_router(runs.router)
app.include_router(validation.router)
app.include_router(prices.router)
app.include_router(inventory.router)
app.include_router(logs.router)
```

- [ ] **Step 4: Create routes package init**

```python
# book_scraper/dashboard/routes/__init__.py
```

(Empty file)

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/
git commit -m "feat: scaffold dashboard app with deps and route structure"
```

---

### Task 4: Dashboard queries module

**Files:**
- Create: `book_scraper/dashboard/queries.py`
- Create: `tests/unit/test_dashboard_queries.py`

- [ ] **Step 1: Write tests for query functions**

```python
# tests/unit/test_dashboard_queries.py
"""Tests for dashboard query functions using real DB."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from book_scraper.dashboard.queries import (
    get_inventory_stats,
    get_overview_stats,
    get_price_changes,
    get_price_history,
    get_recent_runs,
    get_run_detail,
    get_validation_by_type,
    get_validation_summary,
    search_listings,
)
from book_scraper.db.repo import (
    bulk_insert_validation_issues,
    create_scrape_run,
    finish_scrape_run,
    insert_price,
    upsert_listing,
    upsert_shop,
)


@pytest.fixture
def seeded_db(db_session):
    """Seed DB with sample data for dashboard queries."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")

    listing1, _, _ = upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/book-1",
        title="Python Programming",
        author="Author One",
        isbn="9780306406157",
        format="hardcover",
        year=2024,
        price=Decimal("19.99"),
        price_original=Decimal("24.99"),
    )
    listing2, _, _ = upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/book-2",
        title="Data Science Guide",
        format="paperback",
        price=Decimal("14.99"),
    )

    insert_price(
        db_session, listing1.id, Decimal("19.99"), Decimal("24.99"), True
    )
    insert_price(
        db_session, listing2.id, Decimal("14.99"), None, True
    )

    run = create_scrape_run(db_session, shop.id, "scan")
    finish_scrape_run(db_session, run.id, "completed")

    bulk_insert_validation_issues(db_session, [
        {
            "scrape_run_id": run.id,
            "url": "https://vaga.lt/book-1",
            "field": "isbn",
            "issue": "invalid_isbn",
            "raw_value": "BAD",
        },
        {
            "scrape_run_id": run.id,
            "url": "https://vaga.lt/book-2",
            "field": "price",
            "issue": "missing_price",
            "raw_value": None,
        },
    ])
    db_session.commit()

    return {
        "shop": shop,
        "listing1": listing1,
        "listing2": listing2,
        "run": run,
    }


def test_get_overview_stats(db_session, seeded_db):
    stats = get_overview_stats(db_session)
    assert stats["total_listings"] == 2
    assert stats["active_listings"] == 2
    assert stats["total_prices"] >= 2
    assert stats["with_isbn"] == 1


def test_get_recent_runs(db_session, seeded_db):
    runs = get_recent_runs(db_session, limit=5)
    assert len(runs) >= 1
    assert runs[0].status == "completed"


def test_get_run_detail(db_session, seeded_db):
    run_id = seeded_db["run"].id
    run, issues = get_run_detail(db_session, run_id)
    assert run.id == run_id
    assert len(issues) == 2


def test_get_validation_summary(db_session, seeded_db):
    summary = get_validation_summary(db_session)
    assert len(summary) >= 1
    types = {row["issue"]: row["count"] for row in summary}
    assert types["invalid_isbn"] == 1
    assert types["missing_price"] == 1


def test_get_validation_by_type(db_session, seeded_db):
    issues = get_validation_by_type(db_session, "invalid_isbn")
    assert len(issues) == 1
    assert issues[0].url == "https://vaga.lt/book-1"


def test_search_listings(db_session, seeded_db):
    results = search_listings(db_session, "Python")
    assert len(results) == 1
    assert results[0].title == "Python Programming"


def test_search_listings_no_match(db_session, seeded_db):
    results = search_listings(db_session, "NonexistentBook")
    assert len(results) == 0


def test_get_price_history(db_session, seeded_db):
    listing_id = seeded_db["listing1"].id
    prices = get_price_history(db_session, listing_id)
    assert len(prices) >= 1
    assert prices[0].price == Decimal("19.99")


def test_get_price_changes(db_session, seeded_db):
    changes = get_price_changes(db_session, days=7)
    # May be empty since we only inserted one price per listing
    assert isinstance(changes, list)


def test_get_inventory_stats(db_session, seeded_db):
    stats = get_inventory_stats(db_session)
    assert stats["total"] == 2
    assert stats["active"] == 2
    assert stats["with_isbn"] == 1
    assert stats["with_author"] == 1
    formats = {f["format"]: f["count"] for f in stats["by_format"]}
    assert formats["hardcover"] == 1
    assert formats["paperback"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_dashboard_queries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'book_scraper.dashboard.queries'`

- [ ] **Step 3: Implement queries.py**

```python
# book_scraper/dashboard/queries.py
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from book_scraper.db.models import (
    Listing,
    Price,
    ScrapeRun,
    ValidationIssue,
)


def get_overview_stats(session: Session) -> dict[str, Any]:
    total = session.scalar(select(func.count(Listing.id))) or 0
    active = session.scalar(
        select(func.count(Listing.id)).where(Listing.is_active.is_(True))
    ) or 0
    with_isbn = session.scalar(
        select(func.count(Listing.id)).where(Listing.isbn.isnot(None))
    ) or 0
    total_prices = session.scalar(select(func.count(Price.id))) or 0
    return {
        "total_listings": total,
        "active_listings": active,
        "with_isbn": with_isbn,
        "total_prices": total_prices,
    }


def get_recent_runs(session: Session, limit: int = 20) -> list[ScrapeRun]:
    stmt = (
        select(ScrapeRun)
        .order_by(ScrapeRun.started_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def get_run_detail(
    session: Session, run_id: int
) -> tuple[ScrapeRun | None, list[ValidationIssue]]:
    run = session.get(ScrapeRun, run_id)
    if run is None:
        return None, []
    issues_stmt = (
        select(ValidationIssue)
        .where(ValidationIssue.scrape_run_id == run_id)
        .order_by(ValidationIssue.id)
    )
    issues = list(session.scalars(issues_stmt))
    return run, issues


def get_validation_summary(session: Session) -> list[dict[str, Any]]:
    stmt = (
        select(
            ValidationIssue.issue,
            func.count(ValidationIssue.id).label("count"),
        )
        .group_by(ValidationIssue.issue)
        .order_by(func.count(ValidationIssue.id).desc())
    )
    return [{"issue": row.issue, "count": row.count} for row in session.execute(stmt)]


def get_validation_by_type(
    session: Session, issue_type: str, limit: int = 100
) -> list[ValidationIssue]:
    stmt = (
        select(ValidationIssue)
        .where(ValidationIssue.issue == issue_type)
        .order_by(ValidationIssue.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def search_listings(
    session: Session, query: str, limit: int = 50
) -> list[Listing]:
    stmt = (
        select(Listing)
        .where(Listing.title.ilike(f"%{query}%"))
        .order_by(Listing.title)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def get_price_history(
    session: Session, listing_id: int
) -> list[Price]:
    stmt = (
        select(Price)
        .where(Price.listing_id == listing_id)
        .order_by(Price.scraped_at)
    )
    return list(session.scalars(stmt))


def get_price_changes(
    session: Session, days: int = 7
) -> list[dict[str, Any]]:
    """Get listings with biggest price changes in the last N days."""
    sql = text("""
        WITH recent AS (
            SELECT
                p.listing_id,
                p.price,
                p.scraped_at,
                LAG(p.price) OVER (
                    PARTITION BY p.listing_id ORDER BY p.scraped_at
                ) AS prev_price
            FROM prices p
            WHERE p.scraped_at > NOW() - :interval
        )
        SELECT
            r.listing_id,
            l.title,
            l.url,
            r.prev_price,
            r.price AS new_price,
            r.price - r.prev_price AS change,
            CASE WHEN r.prev_price > 0
                THEN ROUND(((r.price - r.prev_price) / r.prev_price) * 100, 1)
                ELSE 0
            END AS change_pct
        FROM recent r
        JOIN listings l ON l.id = r.listing_id
        WHERE r.prev_price IS NOT NULL
            AND r.prev_price != r.price
        ORDER BY ABS(r.price - r.prev_price) DESC
        LIMIT 50
    """)
    rows = session.execute(sql, {"interval": f"{days} days"})
    return [dict(row._mapping) for row in rows]


def get_inventory_stats(session: Session) -> dict[str, Any]:
    total = session.scalar(select(func.count(Listing.id))) or 0
    active = session.scalar(
        select(func.count(Listing.id)).where(Listing.is_active.is_(True))
    ) or 0
    with_isbn = session.scalar(
        select(func.count(Listing.id)).where(Listing.isbn.isnot(None))
    ) or 0
    with_author = session.scalar(
        select(func.count(Listing.id)).where(Listing.author.isnot(None))
    ) or 0
    with_year = session.scalar(
        select(func.count(Listing.id)).where(Listing.year.isnot(None))
    ) or 0
    with_publisher = session.scalar(
        select(func.count(Listing.id)).where(Listing.publisher.isnot(None))
    ) or 0

    format_stmt = (
        select(Listing.format, func.count(Listing.id).label("count"))
        .where(Listing.format.isnot(None))
        .group_by(Listing.format)
        .order_by(func.count(Listing.id).desc())
    )
    by_format = [
        {"format": row.format, "count": row.count}
        for row in session.execute(format_stmt)
    ]

    return {
        "total": total,
        "active": active,
        "with_isbn": with_isbn,
        "with_author": with_author,
        "with_year": with_year,
        "with_publisher": with_publisher,
        "by_format": by_format,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_dashboard_queries.py -v`
Expected: all tests PASS

Note: These tests use the `db_session` fixture from `conftest.py` which connects to the test DB on port 5433. Start the test DB first: `docker compose up -d postgres-test`

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/queries.py tests/unit/test_dashboard_queries.py
git commit -m "feat: add dashboard query functions with tests"
```

---

### Task 5: Base template and overview page

**Files:**
- Create: `book_scraper/dashboard/templates/base.html`
- Create: `book_scraper/dashboard/templates/overview.html`
- Create: `book_scraper/dashboard/routes/overview.py`

- [ ] **Step 1: Create base.html template**

```html
<!-- book_scraper/dashboard/templates/base.html -->
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}Book Scraper{% endblock %}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <style>
        .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
        .stat-card { text-align: center; padding: 1rem; }
        .stat-card h2 { margin-bottom: 0.25rem; }
        .stat-card small { color: var(--pico-muted-color); }
        .badge { padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.85rem; }
        .badge-completed { background: #2ecc40; color: white; }
        .badge-failed { background: #ff4136; color: white; }
        .badge-running { background: #ffdc00; color: black; }
        table { font-size: 0.9rem; }
        nav ul li a[aria-current="page"] { font-weight: bold; }
    </style>
</head>
<body>
    <nav class="container">
        <ul>
            <li><strong>Book Scraper</strong></li>
        </ul>
        <ul>
            <li><a href="/" {% if active_page == "overview" %}aria-current="page"{% endif %}>Overview</a></li>
            <li><a href="/runs" {% if active_page == "runs" %}aria-current="page"{% endif %}>Runs</a></li>
            <li><a href="/validation" {% if active_page == "validation" %}aria-current="page"{% endif %}>Validation</a></li>
            <li><a href="/prices" {% if active_page == "prices" %}aria-current="page"{% endif %}>Prices</a></li>
            <li><a href="/inventory" {% if active_page == "inventory" %}aria-current="page"{% endif %}>Inventory</a></li>
            <li><a href="/logs" {% if active_page == "logs" %}aria-current="page"{% endif %}>Logs</a></li>
        </ul>
    </nav>
    <main class="container">
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

- [ ] **Step 2: Create overview.html template**

```html
<!-- book_scraper/dashboard/templates/overview.html -->
{% extends "base.html" %}
{% block title %}Overview - Book Scraper{% endblock %}
{% block content %}
<h1>Overview</h1>

<div class="stat-grid">
    <article class="stat-card">
        <h2>{{ stats.total_listings }}</h2>
        <small>Total Listings</small>
    </article>
    <article class="stat-card">
        <h2>{{ stats.active_listings }}</h2>
        <small>Active Listings</small>
    </article>
    <article class="stat-card">
        <h2>{{ stats.with_isbn }}</h2>
        <small>With ISBN</small>
    </article>
    <article class="stat-card">
        <h2>{{ stats.total_prices }}</h2>
        <small>Price Records</small>
    </article>
</div>

<h2>Recent Runs</h2>
<table>
    <thead>
        <tr>
            <th>ID</th>
            <th>Phase</th>
            <th>Status</th>
            <th>Started</th>
            <th>Items</th>
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
            <td>+{{ run.items_added }} / ~{{ run.items_updated }}</td>
            <td>{{ run.error_count }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>

{% if validation_summary %}
<h2>Validation Issues (Latest Run)</h2>
<table>
    <thead>
        <tr><th>Issue</th><th>Count</th></tr>
    </thead>
    <tbody>
        {% for v in validation_summary %}
        <tr>
            <td><a href="/validation/{{ v.issue }}">{{ v.issue }}</a></td>
            <td>{{ v.count }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Create overview route**

```python
# book_scraper/dashboard/routes/overview.py
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import templates
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import (
    get_overview_stats,
    get_recent_runs,
    get_validation_summary,
)

router = APIRouter()


@router.get("/")
def overview(request: Request, db: Session = Depends(get_db)):
    stats = get_overview_stats(db)
    recent_runs = get_recent_runs(db, limit=5)
    validation_summary = get_validation_summary(db)
    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "active_page": "overview",
            "stats": stats,
            "recent_runs": recent_runs,
            "validation_summary": validation_summary,
        },
    )
```

- [ ] **Step 4: Verify the app starts**

Run: `DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper uv run uvicorn book_scraper.dashboard.app:app --reload --port 8000`

Open: `http://localhost:8000/`
Expected: Overview page renders with stats from the DB

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/templates/ book_scraper/dashboard/routes/overview.py
git commit -m "feat: add dashboard overview page with stats and recent runs"
```

---

### Task 6: Runs page with trigger support

**Files:**
- Create: `book_scraper/dashboard/templates/runs.html`
- Create: `book_scraper/dashboard/templates/run_detail.html`
- Create: `book_scraper/dashboard/routes/runs.py`

- [ ] **Step 1: Create runs.html template**

```html
<!-- book_scraper/dashboard/templates/runs.html -->
{% extends "base.html" %}
{% block title %}Scrape Runs - Book Scraper{% endblock %}
{% block content %}
<h1>Scrape Runs</h1>

<article>
    <h3>Run Now</h3>
    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
        <button hx-post="/runs/trigger" hx-vals='{"command": "discover_sitemap"}' hx-swap="none" hx-indicator="#spinner">Discover (Sitemap)</button>
        <button hx-post="/runs/trigger" hx-vals='{"command": "discover_categories"}' hx-swap="none" hx-indicator="#spinner">Discover (Categories)</button>
        <button hx-post="/runs/trigger" hx-vals='{"command": "scan"}' hx-swap="none" hx-indicator="#spinner">Scan</button>
        <button hx-post="/runs/trigger" hx-vals='{"command": "rescrape"}' hx-swap="none" hx-indicator="#spinner">Rescrape All</button>
    </div>
    <span id="spinner" class="htmx-indicator" aria-busy="true">Starting...</span>
</article>

<table>
    <thead>
        <tr>
            <th>ID</th>
            <th>Phase</th>
            <th>Status</th>
            <th>Started</th>
            <th>Duration</th>
            <th>Added</th>
            <th>Updated</th>
            <th>Errors</th>
        </tr>
    </thead>
    <tbody hx-get="/runs" hx-trigger="every 10s" hx-select="tbody tr" hx-swap="innerHTML">
        {% for run in runs %}
        <tr>
            <td><a href="/runs/{{ run.id }}">{{ run.id }}</a></td>
            <td>{{ run.phase }}</td>
            <td><span class="badge badge-{{ run.status }}">{{ run.status }}</span></td>
            <td>{{ run.started_at.strftime('%Y-%m-%d %H:%M') if run.started_at else '-' }}</td>
            <td>
                {% if run.finished_at and run.started_at %}
                    {{ (run.finished_at - run.started_at).total_seconds() | int }}s
                {% elif run.status == 'running' %}
                    running...
                {% else %}
                    -
                {% endif %}
            </td>
            <td>{{ run.items_added }}</td>
            <td>{{ run.items_updated }}</td>
            <td>{{ run.error_count }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}
```

- [ ] **Step 2: Create run_detail.html template**

```html
<!-- book_scraper/dashboard/templates/run_detail.html -->
{% extends "base.html" %}
{% block title %}Run #{{ run.id }} - Book Scraper{% endblock %}
{% block content %}
<h1>Run #{{ run.id }}</h1>

<article>
    <div class="stat-grid">
        <div><strong>Phase:</strong> {{ run.phase }}</div>
        <div><strong>Status:</strong> <span class="badge badge-{{ run.status }}">{{ run.status }}</span></div>
        <div><strong>Started:</strong> {{ run.started_at.strftime('%Y-%m-%d %H:%M:%S') if run.started_at else '-' }}</div>
        <div><strong>Finished:</strong> {{ run.finished_at.strftime('%Y-%m-%d %H:%M:%S') if run.finished_at else '-' }}</div>
        <div><strong>URLs Total:</strong> {{ run.urls_total or '-' }}</div>
        <div><strong>URLs Processed:</strong> {{ run.urls_processed }}</div>
        <div><strong>Items Added:</strong> {{ run.items_added }}</div>
        <div><strong>Items Updated:</strong> {{ run.items_updated }}</div>
        <div><strong>4xx Errors:</strong> {{ run.errors_4xx }}</div>
        <div><strong>5xx Errors:</strong> {{ run.errors_5xx }}</div>
    </div>
</article>

{% if issues %}
<h2>Validation Issues ({{ issues | length }})</h2>
<table>
    <thead>
        <tr><th>URL</th><th>Field</th><th>Issue</th><th>Raw Value</th></tr>
    </thead>
    <tbody>
        {% for issue in issues %}
        <tr>
            <td><a href="{{ issue.url }}" target="_blank">{{ issue.url | truncate(60) }}</a></td>
            <td>{{ issue.field }}</td>
            <td>{{ issue.issue }}</td>
            <td>{{ issue.raw_value or '-' }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p>No validation issues for this run.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Create runs route with trigger endpoint**

```python
# book_scraper/dashboard/routes/runs.py
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import templates
from book_scraper.dashboard.deps import get_db, get_docker_client
from book_scraper.dashboard.queries import get_recent_runs, get_run_detail

logger = logging.getLogger(__name__)

router = APIRouter()

COMMANDS = {
    "discover_sitemap": [
        "uv", "run", "scrapy", "crawl", "discover",
        "-a", "shop=vaga", "-a", "strategy=sitemap",
    ],
    "discover_categories": [
        "uv", "run", "scrapy", "crawl", "discover",
        "-a", "shop=vaga", "-a", "strategy=categories",
    ],
    "scan": [
        "uv", "run", "scrapy", "crawl", "scan", "-a", "shop=vaga",
    ],
    "rescrape": [
        "uv", "run", "scrapy", "crawl", "scan",
        "-a", "shop=vaga", "-a", "rescrape=true",
    ],
}


@router.get("/runs")
def runs_list(request: Request, db: Session = Depends(get_db)):
    runs = get_recent_runs(db, limit=50)
    return templates.TemplateResponse(
        "runs.html",
        {"request": request, "active_page": "runs", "runs": runs},
    )


@router.get("/runs/{run_id}")
def run_detail(run_id: int, request: Request, db: Session = Depends(get_db)):
    run, issues = get_run_detail(db, run_id)
    if run is None:
        return HTMLResponse("Run not found", status_code=404)
    return templates.TemplateResponse(
        "run_detail.html",
        {
            "request": request,
            "active_page": "runs",
            "run": run,
            "issues": issues,
        },
    )


@router.post("/runs/trigger")
def trigger_run(command: str, request: Request):
    if command not in COMMANDS:
        return HTMLResponse(f"Unknown command: {command}", status_code=400)

    client = get_docker_client()
    if client is None:
        return HTMLResponse("Docker not available", status_code=503)

    try:
        containers = client.containers.list(
            filters={"label": "com.docker.compose.service=scraper"}
        )
        if not containers:
            return HTMLResponse("Scraper container not found", status_code=503)

        container = containers[0]
        container.exec_run(COMMANDS[command], detach=True, workdir="/app")
        logger.info("Triggered %s on container %s", command, container.name)
        return HTMLResponse(
            '<span style="color: green;">Started!</span>', status_code=200
        )
    except Exception as e:
        logger.error("Failed to trigger %s: %s", command, e)
        return HTMLResponse(f"Error: {e}", status_code=500)
```

- [ ] **Step 4: Verify runs page**

Open: `http://localhost:8000/runs`
Expected: Table of scrape runs with "Run Now" buttons

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/templates/runs.html book_scraper/dashboard/templates/run_detail.html book_scraper/dashboard/routes/runs.py
git commit -m "feat: add runs page with trigger support and run detail view"
```

---

### Task 7: Validation, prices, inventory, and logs pages

**Files:**
- Create: `book_scraper/dashboard/templates/validation.html`
- Create: `book_scraper/dashboard/templates/validation_detail.html`
- Create: `book_scraper/dashboard/templates/prices.html`
- Create: `book_scraper/dashboard/templates/inventory.html`
- Create: `book_scraper/dashboard/templates/logs.html`
- Create: `book_scraper/dashboard/routes/validation.py`
- Create: `book_scraper/dashboard/routes/prices.py`
- Create: `book_scraper/dashboard/routes/inventory.py`
- Create: `book_scraper/dashboard/routes/logs.py`

- [ ] **Step 1: Create validation routes and templates**

```python
# book_scraper/dashboard/routes/validation.py
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import templates
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import (
    get_validation_by_type,
    get_validation_summary,
)

router = APIRouter()


@router.get("/validation")
def validation_list(request: Request, db: Session = Depends(get_db)):
    summary = get_validation_summary(db)
    return templates.TemplateResponse(
        "validation.html",
        {"request": request, "active_page": "validation", "summary": summary},
    )


@router.get("/validation/{issue_type}")
def validation_detail(
    issue_type: str, request: Request, db: Session = Depends(get_db)
):
    issues = get_validation_by_type(db, issue_type)
    return templates.TemplateResponse(
        "validation_detail.html",
        {
            "request": request,
            "active_page": "validation",
            "issue_type": issue_type,
            "issues": issues,
        },
    )
```

```html
<!-- book_scraper/dashboard/templates/validation.html -->
{% extends "base.html" %}
{% block title %}Validation - Book Scraper{% endblock %}
{% block content %}
<h1>Validation Issues</h1>
<table>
    <thead>
        <tr><th>Issue Type</th><th>Total Count</th></tr>
    </thead>
    <tbody>
        {% for v in summary %}
        <tr>
            <td><a href="/validation/{{ v.issue }}">{{ v.issue }}</a></td>
            <td>{{ v.count }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}
```

```html
<!-- book_scraper/dashboard/templates/validation_detail.html -->
{% extends "base.html" %}
{% block title %}{{ issue_type }} - Validation{% endblock %}
{% block content %}
<h1>{{ issue_type }}</h1>
<p><a href="/validation">&larr; Back to all issues</a></p>
<table>
    <thead>
        <tr><th>URL</th><th>Field</th><th>Raw Value</th><th>Run</th></tr>
    </thead>
    <tbody>
        {% for issue in issues %}
        <tr>
            <td><a href="{{ issue.url }}" target="_blank">{{ issue.url | truncate(70) }}</a></td>
            <td>{{ issue.field }}</td>
            <td>{{ issue.raw_value or '-' }}</td>
            <td><a href="/runs/{{ issue.scrape_run_id }}">#{{ issue.scrape_run_id }}</a></td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}
```

- [ ] **Step 2: Create prices routes and template**

```python
# book_scraper/dashboard/routes/prices.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import templates
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import (
    get_price_changes,
    get_price_history,
    search_listings,
)

router = APIRouter()


@router.get("/prices")
def prices_page(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
):
    listings = search_listings(db, q) if q else []
    changes = get_price_changes(db, days=7)
    return templates.TemplateResponse(
        "prices.html",
        {
            "request": request,
            "active_page": "prices",
            "query": q,
            "listings": listings,
            "changes": changes,
        },
    )


@router.get("/api/prices/{listing_id}/chart")
def price_chart_data(listing_id: int, db: Session = Depends(get_db)):
    prices = get_price_history(db, listing_id)
    return JSONResponse({
        "labels": [p.scraped_at.strftime("%Y-%m-%d %H:%M") for p in prices],
        "prices": [float(p.price) for p in prices],
        "originals": [
            float(p.price_original) if p.price_original else None
            for p in prices
        ],
    })
```

```html
<!-- book_scraper/dashboard/templates/prices.html -->
{% extends "base.html" %}
{% block title %}Prices - Book Scraper{% endblock %}
{% block content %}
<h1>Price Trends</h1>

<form action="/prices" method="get">
    <input type="search" name="q" value="{{ query }}" placeholder="Search by title...">
</form>

{% if listings %}
<h3>Search Results</h3>
<table>
    <thead><tr><th>Title</th><th>Current Price</th><th>Original</th><th>Chart</th></tr></thead>
    <tbody>
    {% for l in listings %}
    <tr>
        <td>{{ l.title | truncate(60) }}</td>
        <td>{{ l.price or '-' }}</td>
        <td>{{ l.price_original or '-' }}</td>
        <td><button onclick="loadChart({{ l.id }}, '{{ l.title | truncate(40) }}')">Show</button></td>
    </tr>
    {% endfor %}
    </tbody>
</table>
{% endif %}

<div id="chart-container" style="display:none;">
    <h3 id="chart-title"></h3>
    <canvas id="priceChart" height="100"></canvas>
</div>

{% if changes %}
<h2>Recent Price Changes (7 days)</h2>
<table>
    <thead><tr><th>Title</th><th>Old</th><th>New</th><th>Change</th></tr></thead>
    <tbody>
    {% for c in changes %}
    <tr>
        <td><a href="{{ c.url }}" target="_blank">{{ c.title | truncate(50) }}</a></td>
        <td>{{ c.prev_price }}</td>
        <td>{{ c.new_price }}</td>
        <td style="color: {{ 'red' if c.change > 0 else 'green' }}">
            {{ c.change_pct }}%
        </td>
    </tr>
    {% endfor %}
    </tbody>
</table>
{% endif %}

<script>
let chart = null;
async function loadChart(id, title) {
    const resp = await fetch(`/api/prices/${id}/chart`);
    const data = await resp.json();
    document.getElementById('chart-container').style.display = 'block';
    document.getElementById('chart-title').textContent = title;
    if (chart) chart.destroy();
    chart = new Chart(document.getElementById('priceChart'), {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [
                { label: 'Price', data: data.prices, borderColor: '#3498db', tension: 0.1 },
                { label: 'Original', data: data.originals, borderColor: '#e74c3c', borderDash: [5,5], tension: 0.1 }
            ]
        },
        options: { responsive: true, scales: { y: { beginAtZero: false } } }
    });
}
</script>
{% endblock %}
```

- [ ] **Step 3: Create inventory route and template**

```python
# book_scraper/dashboard/routes/inventory.py
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import templates
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import get_inventory_stats

router = APIRouter()


@router.get("/inventory")
def inventory_page(request: Request, db: Session = Depends(get_db)):
    stats = get_inventory_stats(db)
    return templates.TemplateResponse(
        "inventory.html",
        {"request": request, "active_page": "inventory", "stats": stats},
    )
```

```html
<!-- book_scraper/dashboard/templates/inventory.html -->
{% extends "base.html" %}
{% block title %}Inventory - Book Scraper{% endblock %}
{% block content %}
<h1>Inventory</h1>

<div class="stat-grid">
    <article class="stat-card"><h2>{{ stats.total }}</h2><small>Total Listings</small></article>
    <article class="stat-card"><h2>{{ stats.active }}</h2><small>Active</small></article>
    <article class="stat-card"><h2>{{ stats.total - stats.active }}</h2><small>Inactive</small></article>
</div>

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-top: 2rem;">
    <article>
        <h3>By Format</h3>
        <canvas id="formatChart" height="200"></canvas>
    </article>
    <article>
        <h3>Data Completeness</h3>
        <canvas id="completenessChart" height="200"></canvas>
    </article>
</div>

<script>
new Chart(document.getElementById('formatChart'), {
    type: 'pie',
    data: {
        labels: {{ stats.by_format | map(attribute='format') | list | tojson }},
        datasets: [{ data: {{ stats.by_format | map(attribute='count') | list | tojson }} }]
    }
});
new Chart(document.getElementById('completenessChart'), {
    type: 'bar',
    data: {
        labels: ['ISBN', 'Author', 'Year', 'Publisher'],
        datasets: [{
            label: 'Listings with field',
            data: [{{ stats.with_isbn }}, {{ stats.with_author }}, {{ stats.with_year }}, {{ stats.with_publisher }}]
        }]
    },
    options: { scales: { y: { beginAtZero: true, max: {{ stats.total }} } } }
});
</script>
{% endblock %}
```

- [ ] **Step 4: Create logs route and template**

```python
# book_scraper/dashboard/routes/logs.py
import asyncio
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from book_scraper.dashboard.app import templates

router = APIRouter()

LOG_FILE = Path("scrapy_errors.log")


@router.get("/logs")
def logs_page(request: Request):
    lines: list[str] = []
    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            lines = f.readlines()[-100:]
    return templates.TemplateResponse(
        "logs.html",
        {"request": request, "active_page": "logs", "lines": lines},
    )


@router.get("/api/logs/stream")
async def log_stream():
    async def generate():
        if not LOG_FILE.exists():
            yield "data: Waiting for log file...\n\n"
            return

        with open(LOG_FILE) as f:
            f.seek(0, 2)  # Seek to end
            while True:
                line = f.readline()
                if line:
                    yield f"data: {line.rstrip()}\n\n"
                else:
                    await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")
```

```html
<!-- book_scraper/dashboard/templates/logs.html -->
{% extends "base.html" %}
{% block title %}Logs - Book Scraper{% endblock %}
{% block content %}
<h1>Logs</h1>

<article>
    <h3>Live Stream</h3>
    <pre id="live-log" style="max-height: 400px; overflow-y: auto; font-size: 0.8rem; background: #1a1a2e; color: #e0e0e0; padding: 1rem;"></pre>
    <button onclick="toggleStream()">Pause/Resume</button>
</article>

<h2>Recent Warnings/Errors</h2>
<pre style="max-height: 400px; overflow-y: auto; font-size: 0.8rem;">{% for line in lines %}{{ line }}{% endfor %}</pre>

<script>
let source = null;
function startStream() {
    source = new EventSource('/api/logs/stream');
    const el = document.getElementById('live-log');
    source.onmessage = function(e) {
        el.textContent += e.data + '\n';
        el.scrollTop = el.scrollHeight;
    };
}
function toggleStream() {
    if (source) { source.close(); source = null; }
    else { startStream(); }
}
startStream();
</script>
{% endblock %}
```

- [ ] **Step 5: Verify all pages work**

Start the dashboard and navigate to each page:
- `http://localhost:8000/validation`
- `http://localhost:8000/prices`
- `http://localhost:8000/inventory`
- `http://localhost:8000/logs`

- [ ] **Step 6: Commit**

```bash
git add book_scraper/dashboard/templates/ book_scraper/dashboard/routes/
git commit -m "feat: add validation, prices, inventory, and logs pages"
```

---

### Task 8: Dockerfile and Docker Compose

**Files:**
- Create: `Dockerfile`
- Create: `cron/scraper-crontab`
- Create: `scripts/entrypoint-scraper.sh`
- Create: `scripts/entrypoint-dashboard.sh`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Create the crontab**

```
# cron/scraper-crontab
# Discover new URLs via sitemap daily at 2am
0 2 * * * cd /app && PYTHONPATH=. DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper uv run scrapy crawl discover -a shop=vaga -a strategy=sitemap >> /var/log/scraper.log 2>&1

# Scan product pages daily at 3am
0 3 * * * cd /app && PYTHONPATH=. DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper uv run scrapy crawl scan -a shop=vaga >> /var/log/scraper.log 2>&1
```

- [ ] **Step 2: Create entrypoint scripts**

```bash
#!/bin/bash
# scripts/entrypoint-scraper.sh
set -e

echo "Running database migrations..."
cd /app
PYTHONPATH=. uv run alembic upgrade head

echo "Installing crontab..."
crontab /app/cron/scraper-crontab

echo "Starting cron..."
touch /var/log/scraper.log
exec cron -f
```

```bash
#!/bin/bash
# scripts/entrypoint-dashboard.sh
set -e

echo "Running database migrations..."
cd /app
PYTHONPATH=. uv run alembic upgrade head

echo "Starting dashboard..."
exec uv run uvicorn book_scraper.dashboard.app:app --host 0.0.0.0 --port 8000
```

- [ ] **Step 3: Create multi-stage Dockerfile**

```dockerfile
# Dockerfile

# --- Base stage ---
FROM python:3.12-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra dashboard

# Copy application code
COPY book_scraper/ book_scraper/
COPY alembic/ alembic/
COPY alembic.ini .
COPY config/ config/
COPY scrapy.cfg .

ENV PYTHONPATH=/app
ENV DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper

# --- Scraper stage ---
FROM base AS scraper

RUN apt-get update && apt-get install -y --no-install-recommends cron && rm -rf /var/lib/apt/lists/*

COPY cron/scraper-crontab /app/cron/scraper-crontab
COPY scripts/entrypoint-scraper.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]

# --- Dashboard stage ---
FROM base AS dashboard

COPY scripts/entrypoint-dashboard.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

CMD ["/entrypoint.sh"]
```

- [ ] **Step 4: Update docker-compose.yml**

Replace `docker-compose.yml` with:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: book_scraper
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  postgres-test:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: book_scraper_test
    ports:
      - "5433:5432"
    volumes:
      - pgdata_test:/var/lib/postgresql/data

  scraper:
    build:
      context: .
      target: scraper
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper
    volumes:
      - scraper_logs:/var/log

  dashboard:
    build:
      context: .
      target: dashboard
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - scraper_logs:/var/log:ro

volumes:
  pgdata:
  pgdata_test:
  scraper_logs:
```

- [ ] **Step 5: Build and test**

Run:
```bash
docker compose build
docker compose up -d
```

Verify:
- `docker compose ps` — all 3 services running
- `http://localhost:8000/` — dashboard loads with data
- `docker compose logs scraper` — shows cron started

- [ ] **Step 6: Commit**

```bash
git add Dockerfile cron/ scripts/ docker-compose.yml
git commit -m "feat: add Docker containerization with scraper cron and dashboard"
```

---

### Task 9: Route tests with FastAPI TestClient

**Files:**
- Create: `tests/unit/test_dashboard_routes.py`

- [ ] **Step 1: Write route tests**

```python
# tests/unit/test_dashboard_routes.py
"""Smoke tests for dashboard routes using FastAPI TestClient."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from book_scraper.dashboard.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_db():
    """Mock the DB dependency for all route tests."""
    mock_session = MagicMock()

    # Default return values for queries
    mock_session.scalar.return_value = 0
    mock_session.scalars.return_value = iter([])
    mock_session.execute.return_value = iter([])
    mock_session.get.return_value = None

    with patch("book_scraper.dashboard.deps._session_factory", return_value=mock_session):
        yield mock_session


def test_overview_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Book Scraper" in resp.text


def test_runs_returns_200(client):
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert "Scrape Runs" in resp.text


def test_run_detail_not_found(client):
    resp = client.get("/runs/99999")
    assert resp.status_code == 404


def test_validation_returns_200(client):
    resp = client.get("/validation")
    assert resp.status_code == 200


def test_prices_returns_200(client):
    resp = client.get("/prices")
    assert resp.status_code == 200


def test_prices_search(client):
    resp = client.get("/prices?q=Python")
    assert resp.status_code == 200


def test_inventory_returns_200(client):
    resp = client.get("/inventory")
    assert resp.status_code == 200


def test_logs_returns_200(client):
    resp = client.get("/logs")
    assert resp.status_code == 200


def test_trigger_unknown_command(client):
    resp = client.post("/runs/trigger?command=invalid")
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/unit/test_dashboard_routes.py -v`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_dashboard_routes.py
git commit -m "test: add dashboard route smoke tests"
```

---

### Task 10: Final verification

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 2: Run linters**

```bash
uv run ruff check book_scraper/ tests/
uv run ruff format --check book_scraper/ tests/
uv run mypy book_scraper/
```

Expected: no errors

- [ ] **Step 3: Docker end-to-end test**

```bash
docker compose down -v
docker compose build
docker compose up -d
# Wait for services
sleep 10
# Check dashboard
curl -s http://localhost:8000/ | head -5
# Check runs page
curl -s http://localhost:8000/runs | head -5
# Trigger a discover run
curl -s -X POST "http://localhost:8000/runs/trigger?command=discover_sitemap"
# Check logs
docker compose logs scraper --tail 5
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final cleanup for Docker + dashboard"
```
