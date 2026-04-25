# Hi-fi React Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the hi-fi JSX design files as a React SPA from FastAPI, wired to real PostgreSQL data via a new `/api/` JSON layer.

**Architecture:** Copy JSX files to `static/hifi/`, serve them via a new `GET /app` route that renders a minimal `index.html`. Add `routes/api.py` with JSON endpoints (reusing existing `queries.py` functions). Modify each JSX page component to `fetch()` from the API on mount instead of using hardcoded data. No build step — Babel standalone handles JSX in-browser.

**Tech Stack:** FastAPI, React 18 (CDN, no build), Babel standalone (CDN), SQLAlchemy, PostgreSQL

---

## File Structure

**Copy (no modification needed):**
- `book_scraper/dashboard/static/hifi/hf-tokens.jsx`
- `book_scraper/dashboard/static/hifi/hf-icons.jsx`
- `book_scraper/dashboard/static/hifi/hf-ui.jsx`
- `book_scraper/dashboard/static/hifi/hf-shell.jsx`
- `book_scraper/dashboard/static/hifi/hf-overlays.jsx`
- `book_scraper/dashboard/static/hifi/hf-parser.jsx`

**Copy then modify (replace hardcoded data with API calls):**
- `book_scraper/dashboard/static/hifi/hf-overview.jsx`
- `book_scraper/dashboard/static/hifi/hf-runs.jsx`
- `book_scraper/dashboard/static/hifi/hf-shopbooks.jsx`
- `book_scraper/dashboard/static/hifi/hf-urls-shops.jsx`
- `book_scraper/dashboard/static/hifi/hf-other.jsx`
- `book_scraper/dashboard/static/hifi/hf-details.jsx`
- `book_scraper/dashboard/static/hifi/hf-more-details.jsx`

**Create new:**
- `book_scraper/dashboard/static/hifi/index.html` — SPA entry point
- `book_scraper/dashboard/routes/api.py` — all JSON API endpoints

**Modify existing:**
- `book_scraper/dashboard/app.py` — add `/app` route + `/api` router
- `book_scraper/dashboard/queries.py` — add `get_scrape_activity_by_day()`
- `tests/integration/test_dashboard_routes.py` — add smoke tests for `/api/` routes

---

## Task 1: Copy JSX files and create SPA entry point

**Files:**
- Create: `book_scraper/dashboard/static/hifi/` (13 JSX files from download)
- Create: `book_scraper/dashboard/static/hifi/index.html`
- Modify: `book_scraper/dashboard/app.py`

- [ ] **Step 1: Copy JSX files to static directory**

```bash
mkdir -p book_scraper/dashboard/static/hifi
cp "/Users/evaldas/Downloads/_download/hifi/"*.jsx book_scraper/dashboard/static/hifi/
ls book_scraper/dashboard/static/hifi/
```

Expected: 13 files listed (hf-tokens.jsx, hf-icons.jsx, hf-ui.jsx, hf-shell.jsx, hf-overview.jsx, hf-runs.jsx, hf-shopbooks.jsx, hf-urls-shops.jsx, hf-other.jsx, hf-details.jsx, hf-more-details.jsx, hf-overlays.jsx, hf-parser.jsx)

- [ ] **Step 2: Create the SPA entry point**

Create `book_scraper/dashboard/static/hifi/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>BookScraper Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<style>
  html, body, #root { height: 100%; margin: 0; background: #f7f8fa; }
  body { font-family: 'Inter', sans-serif; -webkit-font-smoothing: antialiased; color: #111827; overflow: hidden; }
  a { color: inherit; }
  button { font-family: inherit; }
</style>
</head>
<body>
<div id="root"></div>
<script src="https://unpkg.com/react@18.3.1/umd/react.development.js" integrity="sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L" crossorigin="anonymous"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" integrity="sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm" crossorigin="anonymous"></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js" integrity="sha384-m08KidiNqLdpJqLq95G/LEi8Qvjl/xUYll3QILypMoQ65QorJ9Lvtp2RXYGBFj1y" crossorigin="anonymous"></script>
<script type="text/babel" src="/static/hifi/hf-tokens.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-icons.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-ui.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-shell.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-overview.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-runs.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-shopbooks.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-urls-shops.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-other.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-details.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-more-details.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-overlays.jsx"></script>
<script type="text/babel" src="/static/hifi/hf-parser.jsx"></script>
<script type="text/babel">
function App() {
  const [page, setPage] = React.useState(localStorage.getItem('hf_page') || 'overview');
  const [params, setParams] = React.useState({});
  const [collapsed, setCollapsed] = React.useState(false);
  const [accent, setAccent] = React.useState(localStorage.getItem('hf_accent') || 'forest');
  const [density, setDensity] = React.useState(localStorage.getItem('hf_density') || 'ultra');
  const [, force] = React.useReducer(x => x + 1, 0);

  React.useEffect(() => { window.HF_ACCENT = accent; localStorage.setItem('hf_accent', accent); force(); }, [accent]);
  React.useEffect(() => { window.HF_DENSITY = density; localStorage.setItem('hf_density', density); force(); }, [density]);
  React.useEffect(() => { localStorage.setItem('hf_page', page); }, [page]);

  const goto = (p, pms = {}) => { setPage(p); setParams(pms); window.scrollTo(0, 0); };
  const nav = { collapsed, setCollapsed, setPage: goto, activePage: page };

  window.HF_APP = {
    openNewRun: () => {},
    openNewSchedule: () => {},
    openAddURL: () => {},
    openAddBook: () => {},
    openCmdK: () => {},
    openAvatarMenu: () => {},
  };

  const pages = {
    'overview':         () => <HFOverview nav={nav} goto={goto} />,
    'runs':             () => <HFRuns nav={nav} goto={goto} />,
    'run-detail':       () => <HFRunDetail nav={nav} goto={goto} params={params} />,
    'shop-books':       () => <HFShopBooks nav={nav} goto={goto} />,
    'shop-book-detail': () => <HFShopBookDetail nav={nav} goto={goto} params={params} />,
    'urls':             () => <HFUrls nav={nav} goto={goto} />,
    'url-detail':       () => <HFUrlDetail nav={nav} goto={goto} params={params} />,
    'shops':            () => <HFShops nav={nav} goto={goto} />,
    'shop-detail':      () => <HFShopDetail nav={nav} goto={goto} params={params} />,
    'cron':             () => <HFCron nav={nav} goto={goto} />,
    'schedule-detail':  () => <HFScheduleDetail nav={nav} goto={goto} params={params} />,
    'issues':           () => <HFIssues nav={nav} goto={goto} />,
    'issue-detail':     () => <HFIssueDetail nav={nav} goto={goto} params={params} />,
    'prices':           () => <HFPrices nav={nav} goto={goto} />,
    'parser':           () => <HFParserEditor nav={nav} goto={goto} />,
  };

  const renderer = pages[page];
  return renderer ? renderer() : <div style={{padding:40}}>Unknown page: {page}</div>;
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
</script>
</body>
</html>
```

- [ ] **Step 3: Add `/app` route and include API router in app.py**

In `book_scraper/dashboard/app.py`, add after the existing imports:

```python
from fastapi.responses import FileResponse
from book_scraper.dashboard.routes import api as api_routes
```

After the existing `app.mount("/static", ...)` line, add:

```python
app.include_router(api_routes.router, prefix="/api")

@app.get("/app")
async def spa_index() -> FileResponse:
    return FileResponse(str(Path(__file__).parent / "static" / "hifi" / "index.html"))
```

- [ ] **Step 4: Create empty routes/api.py scaffold**

```python
# book_scraper/dashboard/routes/api.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db

router = APIRouter()
```

- [ ] **Step 5: Rebuild and verify `/app` loads**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Visit `http://localhost:8000/app` — expect the React SPA to load (will show JS errors until components are wired, but the shell should render with the page router).

- [ ] **Step 6: Commit**

```bash
git add book_scraper/dashboard/static/hifi/ book_scraper/dashboard/app.py book_scraper/dashboard/routes/api.py
git commit -m "feat(dashboard): add hi-fi React SPA entry point at /app"
```

---

## Task 2: Add helper functions to queries.py

**Files:**
- Modify: `book_scraper/dashboard/queries.py`

The overview chart needs items-per-day from scrape_runs. The API also needs a shared `_relative_time` helper.

- [ ] **Step 1: Add `get_scrape_activity_by_day` to queries.py**

At the end of `book_scraper/dashboard/queries.py`, add:

```python
def get_scrape_activity_by_day(session: Session, days: int = 14) -> list[int]:
    """Return items scraped per day for the last N days (oldest first, zeros filled)."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    sql = text("""
        SELECT
            DATE(started_at AT TIME ZONE 'UTC') AS day,
            SUM(items_added + items_updated) AS items
        FROM scrape_runs
        WHERE started_at >= :cutoff AND status = 'completed'
        GROUP BY day
        ORDER BY day
    """)
    rows = session.execute(sql, {"cutoff": cutoff}).mappings().all()
    day_map: dict[str, int] = {str(r["day"]): int(r["items"]) for r in rows}
    result = []
    for i in range(days):
        day = (datetime.now(UTC) - timedelta(days=days - 1 - i)).date()
        result.append(day_map.get(str(day), 0))
    return result
```

- [ ] **Step 2: Write integration test**

In `tests/integration/test_validation_queries.py` (or create `tests/integration/test_api_queries.py`), add:

```python
def test_get_scrape_activity_by_day_returns_list_of_correct_length(db_session):
    from book_scraper.dashboard.queries import get_scrape_activity_by_day
    result = get_scrape_activity_by_day(db_session, days=7)
    assert len(result) == 7
    assert all(isinstance(v, int) for v in result)
    assert all(v >= 0 for v in result)
```

- [ ] **Step 3: Run test**

```bash
uv run pytest tests/integration/test_api_queries.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/queries.py tests/integration/test_api_queries.py
git commit -m "feat(api): add get_scrape_activity_by_day query"
```

---

## Task 3: API — Overview endpoint

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py`
- Test: `tests/integration/test_api_queries.py`

- [ ] **Step 1: Add shared serialisation helpers to api.py**

At the top of `routes/api.py` after the imports, add:

```python
from book_scraper.db.models import ScrapeRun, Shop
from book_scraper.dashboard.queries import (
    get_overview_stats,
    get_recent_runs,
    get_data_completeness,
    get_validation_summary,
    get_all_shops,
    get_shop_stats,
    get_shop_runs,
    get_scrape_activity_by_day,
    get_shop_books_page,
    get_discovered_urls_page,
    get_discovered_urls_stats,
    get_issues_page,
    get_validation_lifecycle_counts,
    get_price_changes,
    ISSUE_SEVERITY,
    ISSUE_DESCRIPTIONS,
    get_run_detail,
    get_url_detail,
    get_run_issue_summary,
)
from book_scraper.db.repo import list_cron_jobs


def _rel(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - dt
    s = int(delta.total_seconds())
    if s < 60:
        return "just now"
    m = s // 60
    if m < 60:
        return f"{m}m ago"
    h = m // 60
    if h < 24:
        return f"{h}h ago"
    return f"{h // 24}d ago"


def _elapsed(run: ScrapeRun) -> str:
    start = run.started_at
    end = run.finished_at or datetime.now(UTC)
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if not start:
        return "—"
    secs = max(0, int((end - start).total_seconds()))
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m" if m else f"{h}h"
    if m:
        return f"{m}m {s}s" if s else f"{m}m"
    return f"{s}s"


def _progress(run: ScrapeRun) -> int:
    if run.status == "completed":
        return 100
    if run.urls_total and run.urls_total > 0:
        return min(99, int(run.urls_processed / run.urls_total * 100))
    return 0


def _run_dict(run: ScrapeRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "shop": run.shop.name,
        "phase": run.phase,
        "status": run.status,
        "progress": _progress(run),
        "items": run.items_added + run.items_updated,
        "items_added": run.items_added,
        "items_updated": run.items_updated,
        "errors": run.error_count,
        "errors_4xx": run.errors_4xx,
        "errors_5xx": run.errors_5xx,
        "elapsed": _elapsed(run),
        "started_ago": _rel(run.started_at),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "urls_total": run.urls_total,
        "urls_processed": run.urls_processed,
    }
```

- [ ] **Step 2: Add the overview endpoint**

```python
@router.get("/overview")
def api_overview(session: Session = Depends(get_db)) -> dict[str, Any]:
    stats = get_overview_stats(session)
    completeness = get_data_completeness(session)
    recent_runs = get_recent_runs(session, limit=10)
    issue_clusters = get_validation_summary(session, state="open")
    shops = get_all_shops(session)
    activity = get_scrape_activity_by_day(session, days=14)

    open_issues = sum(c["count"] for c in issue_clusters)

    shop_cards = []
    for s in shops:
        s_stats = get_shop_stats(session, s.id)
        last = get_shop_runs(session, s.id, limit=1)
        last_run = last[0] if last else None
        shop_cards.append({
            "name": s.name,
            "books": s_stats["shop_books"],
            "active": s_stats["active"],
            "issues": 0,  # per-shop issue count not cheap; show 0 for now
            "last_run_ago": _rel(last_run.started_at if last_run else None),
            "last_run_status": last_run.status if last_run else "—",
        })

    return {
        "stats": {**stats, "open_issues": open_issues},
        "completeness": [{"field": c["field"], "pct": c["pct"]} for c in completeness],
        "recent_runs": [_run_dict(r) for r in recent_runs],
        "issue_clusters": issue_clusters[:6],
        "shops": shop_cards,
        "activity": activity,
    }
```

- [ ] **Step 3: Write smoke test**

In `tests/integration/test_api_queries.py`:

```python
def test_api_overview_returns_expected_keys(client):
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "stats" in data
    assert "completeness" in data
    assert "recent_runs" in data
    assert "issue_clusters" in data
    assert "shops" in data
    assert "activity" in data
    assert len(data["activity"]) == 14
```

Note: `client` fixture comes from the existing test conftest. Check `tests/conftest.py` for the fixture name — it may be `test_client` or similar.

- [ ] **Step 4: Run test**

```bash
uv run pytest tests/integration/test_api_queries.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/routes/api.py tests/integration/test_api_queries.py
git commit -m "feat(api): add /api/overview endpoint"
```

---

## Task 4: API — Runs endpoints

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py`

- [ ] **Step 1: Add runs list + run detail endpoints**

```python
@router.get("/runs")
def api_runs(
    shop: str = "",
    phase: str = "",
    status: str = "",
    limit: int = 50,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import func
    from book_scraper.db.models import ScrapeRun as SR, Shop as SH

    query = (
        session.query(SR)
        .join(SH, SR.shop_id == SH.id)
        .order_by(SR.started_at.desc())
    )
    if shop:
        query = query.filter(SH.name == shop)
    if phase:
        query = query.filter(SR.phase == phase)
    if status:
        query = query.filter(SR.status == status)

    runs = query.limit(limit).all()

    # KPIs
    running_now = session.query(func.count(SR.id)).filter(SR.status == "running").scalar() or 0
    today_cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today_total = session.query(func.count(SR.id)).filter(SR.started_at >= today_cutoff).scalar() or 0
    today_ok = session.query(func.count(SR.id)).filter(SR.started_at >= today_cutoff, SR.status == "completed").scalar() or 0
    today_failed = session.query(func.count(SR.id)).filter(SR.started_at >= today_cutoff, SR.status == "failed").scalar() or 0

    return {
        "runs": [_run_dict(r) for r in runs],
        "kpis": {
            "running_now": running_now,
            "today_total": today_total,
            "today_ok": today_ok,
            "today_failed": today_failed,
        },
    }


@router.get("/runs/{run_id}")
def api_run_detail(run_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    run = get_run_detail(session, run_id)
    if not run:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Run not found")
    issues = get_run_issue_summary(session, run_id)
    return {**_run_dict(run), "issues": issues}
```

- [ ] **Step 2: Commit**

```bash
git add book_scraper/dashboard/routes/api.py
git commit -m "feat(api): add /api/runs and /api/runs/{id} endpoints"
```

---

## Task 5: API — Shop Books endpoints

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py`

- [ ] **Step 1: Add shop books serialiser and endpoints**

```python
def _book_dict(sb: Any) -> dict[str, Any]:
    from book_scraper.db.models import ShopBook
    issues_count = 0  # loaded separately where needed
    price_str = f"€{sb.price:.2f}" if sb.price is not None else "—"
    status = "active" if sb.is_active else ("out" if sb.inactive_since else "delisted")
    return {
        "id": sb.id,
        "title": sb.title,
        "author": sb.author or "—",
        "shop": sb.shop.name if sb.shop else "—",
        "isbn": sb.isbn,
        "price": price_str,
        "price_raw": float(sb.price) if sb.price is not None else None,
        "status": status,
        "issues": issues_count,
        "updated": _rel(sb.last_seen_at),
        "url": sb.url,
        "publisher": sb.publisher,
        "year": sb.year,
        "format": sb.format,
        "type": sb.type,
        "in_stock": sb.in_stock,
        "is_active": sb.is_active,
        "first_seen_at": sb.first_seen_at.isoformat() if sb.first_seen_at else None,
        "last_seen_at": sb.last_seen_at.isoformat() if sb.last_seen_at else None,
    }


@router.get("/shop-books")
def api_shop_books(
    page: int = 1,
    per_page: int = 50,
    search: str = "",
    shop: str = "",
    active: str = "",
    missing_field: str = "",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import func
    from book_scraper.db.models import ShopBook
    from book_scraper.dashboard.queries import get_shop_by_name

    shop_id = None
    if shop:
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else None

    books, total = get_shop_books_page(
        session,
        page=page,
        per_page=per_page,
        search=search,
        shop_id=shop_id,
        active_filter=active,
        missing_field=missing_field,
    )

    total_books = session.query(func.count(ShopBook.id)).scalar() or 0
    active_books = session.query(func.count(ShopBook.id)).filter(ShopBook.is_active.is_(True)).scalar() or 0
    missing_isbn = session.query(func.count(ShopBook.id)).filter(ShopBook.isbn.is_(None)).scalar() or 0
    missing_price = session.query(func.count(ShopBook.id)).filter(ShopBook.price.is_(None)).scalar() or 0

    return {
        "books": [_book_dict(b) for b in books],
        "total": total,
        "page": page,
        "per_page": per_page,
        "kpis": {
            "total": total_books,
            "active": active_books,
            "missing_isbn": missing_isbn,
            "missing_price": missing_price,
        },
    }


@router.get("/shop-books/{book_id}")
def api_shop_book_detail(book_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    from book_scraper.db.models import ShopBook
    from book_scraper.dashboard.queries import (
        get_shop_book_issues,
        get_price_history,
        get_shop_book_changes,
    )
    from sqlalchemy.orm import joinedload

    sb = (
        session.query(ShopBook)
        .options(joinedload(ShopBook.shop))
        .filter(ShopBook.id == book_id)
        .first()
    )
    if not sb:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Book not found")

    issues = get_shop_book_issues(session, book_id)
    prices = get_price_history(session, book_id)
    changes = get_shop_book_changes(session, book_id, limit=20)

    price_history = [
        {
            "scraped_at": p.scraped_at.isoformat(),
            "price": float(p.price) if p.price is not None else None,
            "in_stock": p.in_stock,
        }
        for p in prices
    ]
    change_list = [
        {
            "field": c.field,
            "old_value": c.old_value,
            "new_value": c.new_value,
            "changed_at": c.changed_at.isoformat() if c.changed_at else None,
        }
        for c in changes
    ]

    d = _book_dict(sb)
    d["issues"] = len(issues)
    d["issues_list"] = issues
    d["price_history"] = price_history
    d["changes"] = change_list
    d["description"] = sb.description
    d["image_url"] = sb.image_url
    d["categories"] = sb.categories or []
    return d
```

- [ ] **Step 2: Commit**

```bash
git add book_scraper/dashboard/routes/api.py
git commit -m "feat(api): add /api/shop-books endpoints"
```

---

## Task 6: API — URLs endpoints

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py`

- [ ] **Step 1: Add URL serialiser and endpoints**

```python
def _url_dict(u: Any) -> dict[str, Any]:
    cls = getattr(u, "classification", None)
    book = getattr(u, "shop_book", None)
    return {
        "id": u.id,
        "url": u.url,
        "shop": u.shop.name if u.shop else "—",
        "url_type": u.url_type or "unknown",
        "source": u.source or "—",
        "fail_count": u.fail_count,
        "status": "error" if u.fail_count >= 3 else "ok",
        "first_seen_at": u.first_seen_at.isoformat() if u.first_seen_at else None,
        "last_seen_ago": _rel(u.first_seen_at),
        "book_title": book.title if book else "—",
        "book_id": book.id if book else None,
        "book_score": cls.book_score if cls else None,
        "is_book": cls.is_book_product if cls else None,
    }


@router.get("/urls")
def api_urls(
    page: int = 1,
    per_page: int = 50,
    shop: str = "",
    url_type: str = "",
    search: str = "",
    is_book: str = "",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import get_shop_by_name

    shop_id = None
    if shop:
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else None

    urls, total = get_discovered_urls_page(
        session,
        page=page,
        per_page=per_page,
        shop_id=shop_id,
        url_type=url_type,
        search=search,
        is_book=is_book,
    )
    stats = get_discovered_urls_stats(session, shop_id=shop_id)

    return {
        "urls": [_url_dict(u) for u in urls],
        "total": total,
        "page": page,
        "per_page": per_page,
        "stats": stats,
    }


@router.get("/urls/{url_id}")
def api_url_detail(url_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    result = get_url_detail(session, url_id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="URL not found")
    url, cls = result
    d = _url_dict(url)
    if cls:
        d["classification"] = {
            "book_score": cls.book_score,
            "is_book_product": cls.is_book_product,
            "reasons": cls.reasons if hasattr(cls, "reasons") else [],
        }
    return d
```

- [ ] **Step 2: Commit**

```bash
git add book_scraper/dashboard/routes/api.py
git commit -m "feat(api): add /api/urls endpoints"
```

---

## Task 7: API — Shops endpoints

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py`

- [ ] **Step 1: Add shops endpoints**

```python
@router.get("/shops")
def api_shops(session: Session = Depends(get_db)) -> dict[str, Any]:
    shops = get_all_shops(session)
    result = []
    for s in shops:
        stats = get_shop_stats(session, s.id)
        runs = get_shop_runs(session, s.id, limit=1)
        last = runs[0] if runs else None
        result.append({
            "id": s.id,
            "name": s.name,
            "base_url": s.base_url,
            "books": stats["shop_books"],
            "active": stats["active"],
            "discovered_urls": stats["discovered_urls"],
            "prices": stats["prices"],
            "last_run_ago": _rel(last.started_at if last else None),
            "last_run_status": last.status if last else "—",
        })
    return {"shops": result}


@router.get("/shops/{shop_name}")
def api_shop_detail(shop_name: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    from book_scraper.dashboard.queries import get_shop_by_name, get_shop_field_stats
    from fastapi import HTTPException

    shop = get_shop_by_name(session, shop_name)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    stats = get_shop_stats(session, shop.id)
    field_stats = get_shop_field_stats(session, shop.id)
    runs = get_shop_runs(session, shop.id, limit=20)
    return {
        "id": shop.id,
        "name": shop.name,
        "base_url": shop.base_url,
        **stats,
        "field_stats": field_stats,
        "recent_runs": [_run_dict(r) for r in runs],
    }
```

- [ ] **Step 2: Commit**

```bash
git add book_scraper/dashboard/routes/api.py
git commit -m "feat(api): add /api/shops endpoints"
```

---

## Task 8: API — Cron, Issues, Prices endpoints

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py`

- [ ] **Step 1: Add cron endpoint**

```python
@router.get("/cron")
def api_cron(session: Session = Depends(get_db)) -> dict[str, Any]:
    jobs = list_cron_jobs(session)
    result = []
    for j in jobs:
        last_rel = _rel(j.last_run_at)
        result.append({
            "id": j.id,
            "name": f"{j.shop.name}.{j.phase}.{j.strategy or 'default'}",
            "shop": j.shop.name,
            "phase": j.phase,
            "strategy": j.strategy or "",
            "args": j.args or "",
            "cron": j.cron_expression,
            "enabled": j.enabled,
            "last": last_rel,
            "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
            "last_status": "ok",  # last run status not stored on CronJob; show ok as default
        })
    return {"jobs": result}


@router.post("/cron/{job_id}/toggle")
def api_cron_toggle(job_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    from book_scraper.db.repo import get_cron_job, toggle_cron_job
    from fastapi import HTTPException

    job = get_cron_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    toggle_cron_job(session, job_id)
    return {"id": job_id, "enabled": not job.enabled}
```

- [ ] **Step 2: Add issues endpoint**

```python
@router.get("/issues")
def api_issues(
    state: str = "open",
    shop: str = "",
    issue_type: str = "",
    severity: str = "",
    q: str = "",
    page: int = 1,
    per_page: int = 50,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import get_shop_by_name

    shop_id = None
    if shop:
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else None

    rows, total = get_issues_page(
        session,
        state=state,
        shop_id=shop_id,
        issue_type=issue_type,
        severity=severity,
        q=q,
        page=page,
        per_page=per_page,
    )
    counts = get_validation_lifecycle_counts(
        session, shop_id=shop_id, issue_type=issue_type, severity=severity, q=q
    )

    issues = []
    for r in rows:
        issues.append({
            "id": r["id"],
            "url": r["url"],
            "field": r["field"],
            "issue": r["issue"],
            "raw_value": r["raw_value"],
            "scrape_run_id": r["scrape_run_id"],
            "shop_book_id": r["shop_book_id"],
            "shop_book_title": r["shop_book_title"],
            "lifecycle_state": r["lifecycle_state"],
            "severity": r["severity"],
            "added_at": r["added_at"].isoformat() if r["added_at"] else None,
            "added_ago": _rel(r["added_at"]),
            "description": ISSUE_DESCRIPTIONS.get(r["issue"], ""),
        })

    return {
        "issues": issues,
        "total": total,
        "page": page,
        "per_page": per_page,
        "counts": counts,
    }
```

- [ ] **Step 3: Add prices endpoint**

```python
@router.get("/prices")
def api_prices(
    days: int = 7,
    shop: str = "",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import get_shop_by_name

    shop_id = None
    if shop:
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else None

    changes = get_price_changes(session, days=days, shop_id=shop_id)
    return {
        "changes": [
            {
                "shop_book_id": c["shop_book_id"],
                "title": c["title"],
                "prev_price": float(c["prev_price"]) if c["prev_price"] is not None else None,
                "new_price": float(c["new_price"]) if c["new_price"] is not None else None,
                "change": float(c["change"]) if c["change"] is not None else None,
                "scraped_at": c["scraped_at"].isoformat() if c["scraped_at"] else None,
                "scraped_ago": _rel(c["scraped_at"]),
            }
            for c in changes
        ],
        "days": days,
    }
```

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/routes/api.py
git commit -m "feat(api): add /api/cron, /api/issues, /api/prices endpoints"
```

---

## Task 9: Wire hf-overview.jsx to real data

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-overview.jsx`

The current file has all data hardcoded as constants at the top of `HFOverview`. Replace them with an API fetch. Keep all the JSX rendering code exactly the same — only change the data source.

- [ ] **Step 1: Replace hardcoded data with API fetch**

At the top of the `HFOverview` function, replace the hardcoded `kpis`, `spark`, `completeness`, `runs`, `clusters` constants with:

```js
function HFOverview({ nav, goto }) {
  const HF = getHF();
  const { collapsed, setCollapsed } = nav;

  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/overview')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading || !data) {
    return (
      <HFShell collapsed={collapsed} setCollapsed={setCollapsed} activePage="overview"
        title="Overview" subtitle="Loading…" breadcrumb={<span>Overview</span>}>
        <div style={{padding:40, color: HF.ink3, fontSize:13}}>Loading…</div>
      </HFShell>
    );
  }

  const stats = data.stats;
  const kpis = [
    { label: 'Shop books',      value: stats.total_shop_books.toLocaleString(),  delta: <span style={{color:HF.ink3}}>total</span> },
    { label: 'Active listings', value: stats.active_shop_books.toLocaleString(), delta: <span style={{color:HF.ink3}}>{stats.total_shop_books > 0 ? Math.round(stats.active_shop_books/stats.total_shop_books*100) : 0}% of total</span> },
    { label: 'With ISBN',       value: stats.with_isbn.toLocaleString(),          delta: <span style={{color:HF.ink3}}>{stats.total_shop_books > 0 ? Math.round(stats.with_isbn/stats.total_shop_books*100) : 0}% coverage</span> },
    { label: 'Price records',   value: stats.total_prices.toLocaleString(),       delta: <span style={{color:HF.ink3}}>total</span>, tone:'ok' },
    { label: 'Open issues',     value: stats.open_issues.toLocaleString(),        delta: <span style={{color:HF.ink3}}>open</span>, tone: stats.open_issues > 0 ? 'warn' : 'ok' },
  ];

  const spark = data.activity;
  const completeness = data.completeness.map(c => [c.field.charAt(0).toUpperCase() + c.field.slice(1), c.pct]);

  const statusTone = { running: 'ok', completed: 'neutral', failed: 'err' };
  const runs = data.recent_runs;
  const clusters = data.issue_clusters.map(c => ({ type: c.issue_type, n: c.count, tone: c.count > 100 ? 'err' : 'warn' }));
```

Then update the runs table column definitions to use the API field names:

- Change `v => <span>#{v}</span>` for id — same, fine
- Change `key:'items'` cell `v => v.toLocaleString()` — same (items is already a number)
- Change `key:'elapsed'` → `key:'elapsed'` — same string

Update the "By shop" section to use `data.shops`:

```js
  // Replace the hardcoded shop list with:
  const shopCards = data.shops;
```

Then in the JSX, replace the hardcoded shop array literal with `shopCards`, mapping `s.last_run_ago` → `last` and `s.last_run_status` → `tone` logic:

```js
  {shopCards.map((s, i) => (
    <a key={s.name} href="#" style={{...}}>
      <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:10}}>
        <HFDot tone={s.last_run_status === 'failed' ? 'err' : 'ok'} pulse={s.last_run_status === 'failed'}/>
        <span style={{fontSize:14.5, fontWeight:600}}>{s.name}.lt</span>
        <HFPill tone={s.last_run_status === 'failed' ? 'err' : 'ok'}>{s.last_run_status}</HFPill>
        <span style={{flex:1}}/>
        <span style={{fontSize:11.5, color:HF.ink3, fontFamily:HF.mono}}>last run {s.last_run_ago}</span>
      </div>
      <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:10}}>
        {[['Books', s.books], ['Active', s.active], ['Issues', s.issues]].map(([l,v],j) => (
          <div key={l} style={{paddingLeft: j===0?0:12, borderLeft: j===0?'none':`1px solid ${HF.borderFaint}`}}>
            <div style={{fontSize:10.5, color:HF.ink4, textTransform:'uppercase', letterSpacing:0.5, fontWeight:600}}>{l}</div>
            <div style={{fontFamily:HF.mono, fontSize:16, color:HF.ink, marginTop:3, fontWeight:600, fontVariantNumeric:'tabular-nums', letterSpacing:-0.3}}>
              {typeof v === 'number' ? v.toLocaleString() : v}
            </div>
          </div>
        ))}
      </div>
    </a>
  ))}
```

- [ ] **Step 2: Rebuild and verify overview page loads with real data**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Visit `http://localhost:8000/app` — click Overview in sidebar, verify real counts appear.

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-overview.jsx
git commit -m "feat(dashboard): wire overview page to /api/overview"
```

---

## Task 10: Wire hf-runs.jsx to real data

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-runs.jsx`

- [ ] **Step 1: Replace hardcoded `allRows` with API fetch in HFRuns**

In `HFRuns`, replace the hardcoded `allRows` array and KPI strip with:

```js
function HFRuns({ nav, goto }) {
  const HF = getHF();
  const [data, setData] = React.useState({ runs: [], kpis: { running_now: 0, today_total: 0, today_ok: 0, today_failed: 0 } });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/runs?limit=100')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const allRows = data.runs;
  const kpis = data.kpis;
  // ... rest of component unchanged
```

Update the KPI strip to use `kpis` from the API (replace hardcoded values):

```js
  <HFKpiStrip items={[
    { label:'Running now',       value: String(kpis.running_now), delta:<span style={{color:HF.okInk}}>● live</span> },
    { label:'Today',             value: String(kpis.today_total), delta:<span style={{color:HF.ink3}}>{kpis.today_ok} ok · {kpis.today_failed} failed</span> },
  ]}/>
```

The filter logic uses fields: `id, shop, phase, type, status, startedH, by`. Map API fields:
- `type` → not in DB, default to `"full"` in `_run_dict`
- `startedH` → derive from `started_at` for time-based filtering
- `by` → not in DB, default to `"—"` in `_run_dict`

Add to `_run_dict` in api.py:
```python
"type": "full",  # not stored; default
"by": "—",       # trigger not stored; default
"startedH": 0,   # computed below
```

Compute `startedH` (hours ago) in `_run_dict`:
```python
started_h = 0.0
if run.started_at:
    start = run.started_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    started_h = (datetime.now(UTC) - start).total_seconds() / 3600
"startedH": round(started_h, 2),
```

- [ ] **Step 2: Wire run detail page in HFRunDetail**

In `hf-runs.jsx`, find `HFRunDetail` and replace its hardcoded data:

```js
function HFRunDetail({ nav, goto, params }) {
  const HF = getHF();
  const runId = params?.id;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (!runId) return;
    fetch(`/api/runs/${runId}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [runId]);

  if (loading || !data) {
    return (
      <HFShell {...nav} activePage="runs" title="Run detail" subtitle="Loading…"
        breadcrumb={<><a href="#" onClick={e=>{e.preventDefault();goto('runs');}}>Runs</a><span>/</span><span>#{runId}</span></>}>
        <div style={{padding:40, color:HF.ink3}}>Loading…</div>
      </HFShell>
    );
  }
  // Replace hardcoded run vars with data fields
  // data.id, data.shop, data.phase, data.status, data.progress, data.items, data.elapsed, etc.
  // Keep JSX rendering structure intact, just swap variable references
```

- [ ] **Step 3: Rebuild and test**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Visit `/app`, click Runs — verify real runs appear. Click a row to verify run detail loads.

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-runs.jsx book_scraper/dashboard/routes/api.py
git commit -m "feat(dashboard): wire runs page to /api/runs"
```

---

## Task 11: Wire hf-shopbooks.jsx to real data

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-shopbooks.jsx`

- [ ] **Step 1: Replace hardcoded rows in HFShopBooks with API fetch**

In `HFShopBooks`, replace the hardcoded `rows` array:

```js
function HFShopBooks({ nav, goto }) {
  const HF = getHF();
  const [data, setData] = React.useState({ books: [], total: 0, kpis: { total: 0, active: 0, missing_isbn: 0, missing_price: 0 } });
  const [loading, setLoading] = React.useState(true);
  const [apiPage, setApiPage] = React.useState(1);

  React.useEffect(() => {
    setLoading(true);
    fetch(`/api/shop-books?page=${apiPage}&per_page=100`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [apiPage]);

  const rows = data.books;
  // rest of component uses rows through useHFFilters as before
```

Update KPI strip to use `data.kpis`:

```js
  <HFKpiStrip items={[
    { label:'Total books',   value: data.kpis.total.toLocaleString(),         delta:<span style={{color:HF.ink3}}>total</span> },
    { label:'Active',        value: data.kpis.active.toLocaleString(),        delta:<span style={{color:HF.ink3}}>{data.kpis.total > 0 ? Math.round(data.kpis.active/data.kpis.total*100) : 0}%</span> },
    { label:'Missing ISBN',  value: data.kpis.missing_isbn.toLocaleString(),  delta:<span style={{color:HF.warnInk}}>{data.kpis.total > 0 ? Math.round(data.kpis.missing_isbn/data.kpis.total*100) : 0}%</span>, tone:'warn' },
    { label:'Missing price', value: data.kpis.missing_price.toLocaleString(), delta:<span style={{color:HF.warnInk}}>{data.kpis.total > 0 ? Math.round(data.kpis.missing_price/data.kpis.total*100) : 0}%</span>, tone:'warn' },
  ]}/>
```

- [ ] **Step 2: Wire shop book detail (HFShopBookDetail)**

In `hf-shopbooks.jsx` (or `hf-more-details.jsx` — wherever `HFShopBookDetail` is defined), add API fetch:

```js
function HFShopBookDetail({ nav, goto, params }) {
  const HF = getHF();
  const bookId = params?.id;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (!bookId) return;
    fetch(`/api/shop-books/${bookId}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [bookId]);

  if (loading || !data) {
    return (
      <HFShell {...nav} activePage="shop-books" title="Book detail" subtitle="Loading…"
        breadcrumb={<><a href="#" onClick={e=>{e.preventDefault();goto('shop-books');}}>Shop Books</a><span>/</span><span>#{bookId}</span></>}>
        <div style={{padding:40, color:HF.ink3}}>Loading…</div>
      </HFShell>
    );
  }
  // Swap hardcoded vars for data fields
```

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-shopbooks.jsx book_scraper/dashboard/static/hifi/hf-more-details.jsx
git commit -m "feat(dashboard): wire shop books page to /api/shop-books"
```

---

## Task 12: Wire hf-urls-shops.jsx to real data

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-urls-shops.jsx`

- [ ] **Step 1: Wire HFUrls**

```js
function HFUrls({ nav, goto }) {
  const HF = getHF();
  const [data, setData] = React.useState({ urls: [], total: 0, stats: { total: 0, in_shop_books: 0, not_in_shop_books: 0, failed: 0 } });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/urls?per_page=100')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const rows = data.urls;
  const urlStats = data.stats;
```

Update KPI strip:

```js
  <HFKpiStrip items={[
    { label:'Total URLs',   value: urlStats.total.toLocaleString(), delta:<span style={{color:HF.ink3}}>all shops</span> },
    { label:'In catalog',   value: urlStats.in_shop_books.toLocaleString(), delta:<span style={{color:HF.okInk}}>mapped</span>, tone:'ok' },
    { label:'Not scraped',  value: urlStats.not_in_shop_books.toLocaleString(), delta:<span style={{color:HF.warnInk}}>pending</span>, tone:'warn' },
    { label:'Failing',      value: urlStats.failed.toLocaleString(), delta:<span style={{color:HF.errInk}}>3+ fails</span>, tone:'err' },
  ]}/>
```

Map row fields: `u` → `url`, `status` → derive from `fail_count` (>=3 → "error", else "ok"), `code` → not available (show 200/404 placeholder), `book` → `book_title`.

- [ ] **Step 2: Wire HFShops and HFShopDetail**

```js
function HFShops({ nav, goto }) {
  const HF = getHF();
  const [data, setData] = React.useState({ shops: [] });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/shops')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const rows = data.shops;
```

For `HFShopDetail`:

```js
function HFShopDetail({ nav, goto, params }) {
  const HF = getHF();
  const shopName = params?.name;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (!shopName) return;
    fetch(`/api/shops/${shopName}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [shopName]);
```

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-urls-shops.jsx
git commit -m "feat(dashboard): wire URLs and shops pages to API"
```

---

## Task 13: Wire hf-other.jsx (Cron, Issues, Prices)

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-other.jsx`

- [ ] **Step 1: Wire HFCron**

Replace the hardcoded `jobsRaw` array:

```js
function HFCron({ nav, goto }) {
  const HF = getHF();
  const [data, setData] = React.useState({ jobs: [] });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/cron')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const jobsRaw = data.jobs;
  const jobs = jobsRaw.map(j => ({
    ...j,
    state: j.enabled ? 'active' : 'disabled',
    lastStatus: j.last_status || 'ok',
    next: '—',    // next run time not computed server-side yet
    avgDur: '—',  // avg duration not stored on CronJob
  }));
```

- [ ] **Step 2: Wire HFIssues**

Replace the hardcoded `seed` array:

```js
function HFIssues({ nav, goto }) {
  const HF = getHF();
  const [tab, setTab] = React.useState('open');
  const [data, setData] = React.useState({ issues: [], total: 0, counts: { new: 0, recurring: 0, already_seen: 0, open: 0 } });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    const stateParam = tab === 'open' ? 'open' : tab === 'known' ? 'already_seen' : tab === 'all' ? '' : tab;
    fetch(`/api/issues?state=${stateParam}&per_page=100`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [tab]);

  // Map API issue rows to the shape the table expects
  const seed = data.issues.map(i => ({
    id: `ISS-${i.id}`,
    type: i.issue,
    sev: i.severity === 'critical' ? 'high' : i.severity === 'warning' ? 'medium' : 'low',
    shop: i.scrape_run_id ? '—' : '—',  // shop not in flat issues; show '—'
    book: i.shop_book_title || '—',
    url: i.url || '—',
    detail: i.description || i.raw_value || '—',
    age: i.added_ago,
    known: i.lifecycle_state === 'already_seen',
  }));
```

- [ ] **Step 3: Wire HFPrices**

```js
function HFPrices({ nav, goto }) {
  const HF = getHF();
  const [data, setData] = React.useState({ changes: [] });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/prices?days=7')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const rows = data.changes.map(c => ({
    id: c.shop_book_id,
    title: c.title,
    prev: c.prev_price !== null ? `€${c.prev_price.toFixed(2)}` : '—',
    new: c.new_price !== null ? `€${c.new_price.toFixed(2)}` : '—',
    change: c.change !== null ? `${c.change >= 0 ? '+' : ''}€${c.change.toFixed(2)}` : '—',
    when: c.scraped_ago,
    pct: c.prev_price ? Math.round(c.change / c.prev_price * 100) : 0,
  }));
```

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-other.jsx
git commit -m "feat(dashboard): wire cron/issues/prices pages to API"
```

---

## Task 14: Wire URL detail page (hf-details.jsx)

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-details.jsx`

The URL detail page is navigated to via `goto('url-detail', { id: row.id })`. Currently it uses hardcoded `params.u`, `params.shop` etc.

- [ ] **Step 1: Update HFUrlDetail to fetch from API**

In `hf-details.jsx`, find `HFUrlDetail` and replace with:

```js
function HFUrlDetail({ nav, goto, params }) {
  const HF = getHF();
  const urlId = params?.id;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (!urlId) return;
    fetch(`/api/urls/${urlId}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [urlId]);

  if (loading || !data) {
    return (
      <HFShell {...nav} activePage="urls" title="URL detail" subtitle="Loading…"
        breadcrumb={<><a href="#" onClick={e=>{e.preventDefault();goto('urls');}}>URLs</a><span>/</span><span>#{urlId}</span></>}>
        <div style={{padding:40, color:HF.ink3}}>Loading…</div>
      </HFShell>
    );
  }

  const urlPath = data.url;
  const shop = data.shop;
  const status = data.fail_count >= 3 ? 'error' : 'ok';
  // Map data fields to the existing JSX rendering variables
```

- [ ] **Step 2: Update HFUrls to pass `id` to goto**

In `hf-urls-shops.jsx`, ensure the row click passes the URL id:

```js
onRowClick={(r) => goto('url-detail', { id: r.id })}
```

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-details.jsx book_scraper/dashboard/static/hifi/hf-urls-shops.jsx
git commit -m "feat(dashboard): wire URL detail page to /api/urls/{id}"
```

---

## Task 15: Add API smoke tests and rebuild for production

**Files:**
- Modify: `tests/integration/test_dashboard_routes.py`

- [ ] **Step 1: Add API route smoke tests**

In `tests/integration/test_dashboard_routes.py`, add:

```python
def test_api_overview(client):
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "stats" in data
    assert "recent_runs" in data


def test_api_runs(client):
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert "kpis" in data


def test_api_shop_books(client):
    resp = client.get("/api/shop-books")
    assert resp.status_code == 200
    data = resp.json()
    assert "books" in data
    assert "total" in data


def test_api_urls(client):
    resp = client.get("/api/urls")
    assert resp.status_code == 200
    data = resp.json()
    assert "urls" in data


def test_api_shops(client):
    resp = client.get("/api/shops")
    assert resp.status_code == 200
    data = resp.json()
    assert "shops" in data


def test_api_cron(client):
    resp = client.get("/api/cron")
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data


def test_api_issues(client):
    resp = client.get("/api/issues")
    assert resp.status_code == 200
    data = resp.json()
    assert "issues" in data


def test_api_prices(client):
    resp = client.get("/api/prices")
    assert resp.status_code == 200
    data = resp.json()
    assert "changes" in data


def test_spa_entry_point(client):
    resp = client.get("/app")
    assert resp.status_code == 200
    assert b"<html" in resp.content
```

- [ ] **Step 2: Run all smoke tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all PASS

- [ ] **Step 3: Full rebuild + deploy**

```bash
docker compose build dashboard && docker compose up -d dashboard
uv run pytest tests/integration/test_dashboard_routes.py -v
```

- [ ] **Step 4: Manual walkthrough**

Visit `http://localhost:8000/app` and verify:
- Overview page loads with real counts
- Runs page shows real scrape runs
- Shop Books page shows real books
- URLs page shows real URLs
- Shops page shows real shop cards
- Cron page shows real scheduled jobs
- Issues page shows real validation issues
- Prices page shows real price changes
- Navigation between pages works

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_dashboard_routes.py
git commit -m "test(api): add smoke tests for all /api/ endpoints"
```

---

## Notes

**Field gaps (not in DB model):**
- `ScrapeRun.type` (full/sitemap/discovered) — not stored; `_run_dict` returns `"full"` as a default
- `ScrapeRun.triggered_by` — not stored; `_run_dict` returns `"—"` as a default
- `CronJob.last_run_status` — only `last_run_at` is stored, not the status of that run; API returns `"ok"` as default
- `CronJob.next_run` / `avg_duration` — not computed; API returns `"—"` until computed

**Performance note:** `GET /api/overview` makes N+1 calls to `get_shop_stats` per shop. For a personal project with 2-3 shops this is fine.

**Detail pages not wired:** `HFIssueDetail` and `HFScheduleDetail` still use hardcoded data. They can be wired in a follow-up once the list pages are working.
