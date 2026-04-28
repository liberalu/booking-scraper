# Remove Jinja2 Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the entire legacy Jinja2/Pico CSS template-based dashboard, leaving only the React SPA (hifi) and the JSON API layer.

**Architecture:** The React SPA at `static/hifi/` already handles all pages. Old `routes/*.py` files that served `TemplateResponse` are dead code — the SPA routes in `app.py` take first-match priority. We delete templates, strip dead route functions, remove routers from `app.py`, and add two permanent redirects for URLs that changed (`/validation` → `/issues`, `/shops/{name}/not-listed` → `/shops/{name}`).

**Tech Stack:** Python/FastAPI, SQLAlchemy, pytest, Docker Compose

---

## File Map

| Action | Path | Why |
|---|---|---|
| DELETE (12 files) | `book_scraper/dashboard/templates/*.html` | All templates — no longer rendered |
| DELETE | `book_scraper/dashboard/routes/runs.py` | Only had GET template route + dead POST |
| DELETE | `book_scraper/dashboard/routes/urls.py` | Only had GET template routes |
| DELETE | `book_scraper/dashboard/routes/shop_books.py` | Only had GET template routes |
| DELETE | `book_scraper/dashboard/routes/validation.py` | GET template + POST form-redirect routes not used by SPA |
| DELETE | `book_scraper/dashboard/routes/cron.py` | GET template + POST form-redirect routes; SPA uses `/api/cron/*` |
| DELETE | `book_scraper/dashboard/routes/prices.py` | GET was a redirect; chart API unused by SPA |
| DELETE | `tests/unit/test_relative_time.py` | Tests the deleted `_relative_time` Jinja2 filter |
| DELETE | `tests/unit/test_change_diff.py` | Tests the deleted `_change_diff` / `_diff_chunks` / `_render_chunks` / `_render_description` helpers |
| DELETE | `tests/integration/test_cron_routes.py` | Tests deleted form-redirect cron endpoints (`POST /cron`, `POST /cron/{id}/delete`); SPA only uses `GET /api/cron` + `POST /api/cron/{id}/toggle` (both still in `routes/api.py`) |
| DELETE | `tests/integration/test_cron_run_now.py` | Tests deleted `POST /cron/{id}/run` form endpoint; "run now" not exposed via SPA today |
| MODIFY | `book_scraper/dashboard/routes/shops.py` | Keep only `update_rate_settings` + `_upsert_setting` helpers |
| MODIFY | `book_scraper/dashboard/app.py` | Remove dead imports/routers/Jinja2 setup; add redirects (must register **before** SPA catch-all loops) |
| MODIFY | `book_scraper/dashboard/deps.py` | Remove `templates = Jinja2Templates(...)` |
| MODIFY | `tests/integration/test_dashboard_routes.py` | Remove template-route tests; add redirect tests |
| MODIFY | `pyproject.toml` | Remove `jinja2>=3.1` from `[project] dependencies` and the matching `# used by FastAPI's Jinja2Templates` deptry-ignore comment |

**Not touched:** `routes/api.py`, `routes/scrape.py`, `static/hifi/`, `queries.py`, `models.py`

**Functionality dropped (intentional):** `POST /cron` (create job from form), `POST /cron/{id}/delete` (delete job), and `POST /cron/{id}/run` ("run now") are removed without replacement. The SPA never called them. If a future CRUD UI needs them, they should be re-added under `/api/cron/*` and tested via `routes/api.py`, not the deleted form-redirect handlers.

---

### Task 1: Delete Jinja2 template files

**Files:**
- Delete: `book_scraper/dashboard/templates/` (all 12 files)

- [ ] **Step 1: Delete the templates directory**

```bash
rm -rf book_scraper/dashboard/templates/
```

- [ ] **Step 2: Verify Python can still import the app (templates object will fail — expected at this stage)**

```bash
uv run python -c "import book_scraper.dashboard.routes.api"
```
Expected: OK (api.py doesn't import templates)

- [ ] **Step 3: Commit**

```bash
git add -A book_scraper/dashboard/templates/
git commit -m "chore: delete legacy Jinja2 templates"
```

---

### Task 2: Delete six dead route files

**Files:**
- Delete: `book_scraper/dashboard/routes/runs.py`
- Delete: `book_scraper/dashboard/routes/urls.py`
- Delete: `book_scraper/dashboard/routes/shop_books.py`
- Delete: `book_scraper/dashboard/routes/validation.py`
- Delete: `book_scraper/dashboard/routes/cron.py`
- Delete: `book_scraper/dashboard/routes/prices.py`

- [ ] **Step 1: Delete the files**

```bash
rm book_scraper/dashboard/routes/runs.py \
   book_scraper/dashboard/routes/urls.py \
   book_scraper/dashboard/routes/shop_books.py \
   book_scraper/dashboard/routes/validation.py \
   book_scraper/dashboard/routes/cron.py \
   book_scraper/dashboard/routes/prices.py
```

- [ ] **Step 2: Commit**

```bash
git add -A book_scraper/dashboard/routes/
git commit -m "chore: delete dead template-serving route files"
```

---

### Task 3: Slim shops.py to rate-settings only

**Files:**
- Modify: `book_scraper/dashboard/routes/shops.py`

The file currently has ~310 lines. After this task it will have ~60 lines — only the `_upsert_setting` helper and the `update_rate_settings` POST route that the React SPA still calls.

- [ ] **Step 1: Replace the entire file**

```python
# book_scraper/dashboard/routes/shops.py
from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import get_shop_by_name
from book_scraper.db.models import ShopSettings

router = APIRouter()


def _upsert_setting(
    session: Session, shop_id: int, key: str, value: str, dtype: str
) -> None:
    existing = (
        session.query(ShopSettings)
        .filter(ShopSettings.shop_id == shop_id, ShopSettings.key == key)
        .first()
    )
    if existing:
        existing.value = value
        existing.dtype = dtype
    else:
        session.add(ShopSettings(shop_id=shop_id, key=key, value=value, dtype=dtype))


@router.post("/shops/{shop_name}/rate-settings")
def update_rate_settings(
    shop_name: str,
    download_delay: float = Form(...),
    concurrent_requests_per_domain: int = Form(...),
    session: Session = Depends(get_db),
) -> HTMLResponse:
    shop = get_shop_by_name(session, shop_name)
    if shop is None:
        return HTMLResponse('<p class="error">Shop not found</p>', status_code=404)
    if not (0.1 <= download_delay <= 60.0):
        return HTMLResponse(
            '<p class="error">download_delay must be 0.1–60 s</p>', status_code=400
        )
    if not (1 <= concurrent_requests_per_domain <= 16):
        return HTMLResponse(
            '<p class="error">concurrent_requests_per_domain must be 1–16</p>',
            status_code=400,
        )
    _upsert_setting(session, shop.id, "download_delay", str(download_delay), "float")
    _upsert_setting(
        session,
        shop.id,
        "concurrent_requests_per_domain",
        str(concurrent_requests_per_domain),
        "int",
    )
    session.commit()
    return HTMLResponse('<p class="success">Saved.</p>')
```

- [ ] **Step 2: Commit**

```bash
git add book_scraper/dashboard/routes/shops.py
git commit -m "chore: strip shops.py to rate-settings endpoint only"
```

---

### Task 4: Clean up deps.py

**Files:**
- Modify: `book_scraper/dashboard/deps.py`

Remove the `Jinja2Templates` import and `templates` object. Nothing else in the app imports `templates` after the route files are deleted.

- [ ] **Step 1: Replace the file**

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
    try:
        import docker  # type: ignore[import-untyped]

        return docker.from_env()
    except Exception:
        return None
```

- [ ] **Step 2: Commit**

```bash
git add book_scraper/dashboard/deps.py
git commit -m "chore: remove Jinja2Templates from deps"
```

---

### Task 5: Rewrite app.py — remove dead code, add redirects

**Files:**
- Modify: `book_scraper/dashboard/app.py`

Remove:
- Imports for deleted routers (`cron`, `prices`, `runs`, `shop_books`, `urls`, `validation`)
- `from book_scraper.dashboard.deps import templates` (no longer needed)
- `import markdown as _markdown` and `import difflib` (only used by deleted template filters)
- Functions `_render_description` (lines ~65–88), `_relative_time` (lines ~36–63), `_change_diff` (lines ~191–225)
- Lines `templates.env.filters[...] = ...` (3 lines ~228–230)
- `app.include_router(runs.router)` and all other deleted routers
- Keep: `app.include_router(shops.router)` (rate-settings), `scrape.router`, `prices.router` → **prices is deleted**, so also remove that include

Add two redirects in app.py after the SPA routes are registered:
- `GET /validation` → `GET /issues` (preserve query string)
- `GET /shops/{shop_name}/not-listed` → `GET /shops/{shop_name}`

- [ ] **Step 1: Read the current app.py to get exact line counts before editing**

```bash
wc -l book_scraper/dashboard/app.py
grep -n "def _relative_time\|def _render_description\|def _change_diff\|templates.env\|include_router" book_scraper/dashboard/app.py
```

- [ ] **Step 2: Remove the three template-filter functions and their registrations**

The functions `_relative_time`, `_render_description`, and `_change_diff` are only used as Jinja2 template filters. Delete them entirely (the `import difflib`, `import markdown as _markdown`, and `from markupsafe import Markup, escape` at the top are only needed by those functions — remove them too if no other code uses them).

After deletion, also remove lines:
```python
templates.env.filters["markdown"] = _render_description
templates.env.filters["relative_time"] = _relative_time
templates.env.globals["change_diff"] = _change_diff
```

- [ ] **Step 3: Remove deleted router imports and include_router calls**

Remove from the imports block at the top:
```python
# REMOVE these lines:
from book_scraper.dashboard.routes import (
    cron,
    prices,
    runs,
    shop_books,
    urls,
    validation,
)
```

Replace with just the remaining routers:
```python
from book_scraper.dashboard.routes import scrape
```
(Keep `api as api_routes` and `shops` separately since they were already separate imports.)

Remove these include_router calls:
```python
# REMOVE:
app.include_router(runs.router)
app.include_router(urls.router)
app.include_router(shop_books.router)
app.include_router(validation.router)
app.include_router(prices.router)
app.include_router(cron.router)
```

Keep:
```python
app.include_router(api_routes.router, prefix="/api")
app.include_router(shops.router)
app.include_router(scrape.router)
```

- [ ] **Step 4: Remove `from book_scraper.dashboard.deps import templates`**

This import is at the top of app.py. Remove it.

- [ ] **Step 5: Add the two permanent redirects (BEFORE the SPA route loops)**

Register **before** the `_SPA_FLAT_PATHS` / `_SPA_DETAIL_PATHS` registration loops. FastAPI/Starlette resolve in registration order, so `/shops/{rest:path}` from `_SPA_DETAIL_PATHS` would otherwise shadow `/shops/{shop_name}/not-listed` and the redirect test would fail (users would get the SPA shell instead of a 301). The same caution applies to any future redirect overlapping a SPA path.

```python
from fastapi import Request
from fastapi.responses import RedirectResponse


@app.get("/validation")
async def _redirect_validation(request: Request) -> RedirectResponse:
    qs = request.url.query
    target = "/issues" + (f"?{qs}" if qs else "")
    return RedirectResponse(url=target, status_code=301)


@app.get("/shops/{shop_name}/not-listed")
async def _redirect_not_listed(shop_name: str) -> RedirectResponse:
    return RedirectResponse(url=f"/shops/{shop_name}", status_code=301)


for _spa_path in _SPA_FLAT_PATHS:
    app.add_api_route(_spa_path, _spa_index_flat, methods=["GET"])
for _spa_path in _SPA_DETAIL_PATHS:
    app.add_api_route(_spa_path, _spa_index_detail, methods=["GET"])
```

Note: `Request` and `RedirectResponse` are likely already imported — check before adding imports.

- [ ] **Step 6: Verify app imports cleanly**

```bash
uv run python -c "from book_scraper.dashboard.app import app; print('OK')"
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add book_scraper/dashboard/app.py
git commit -m "chore: remove Jinja2 wiring and dead routers from app.py, add /validation and /not-listed redirects"
```

---

### Task 6: Update tests

**Files:**
- Modify: `tests/integration/test_dashboard_routes.py`
- Delete: `tests/unit/test_relative_time.py`
- Delete: `tests/unit/test_change_diff.py`
- Delete: `tests/integration/test_cron_routes.py`
- Delete: `tests/integration/test_cron_run_now.py`

Remove tests that hit old Jinja2 template routes (they no longer exist). Delete the unit tests for helpers removed in Task 5 — they import `_relative_time` / `_change_diff` / `_diff_chunks` / `_render_chunks` / `_render_description` from `book_scraper.dashboard.app`, which now fails at collection time. Delete the cron integration tests that exercise the deleted form-redirect endpoints (`GET /cron`, `POST /cron`, `POST /cron/{id}/delete`, `POST /cron/{id}/run`) — these endpoints are being dropped without API replacement (see File Map note). Add two tests for the new redirects.

- [ ] **Step 0: Delete the stale test files**

```bash
rm tests/unit/test_relative_time.py \
   tests/unit/test_change_diff.py \
   tests/integration/test_cron_routes.py \
   tests/integration/test_cron_run_now.py
```

- [ ] **Step 1: Remove template route tests**

Delete the following from the test file:

1. The entire `ROUTES` list and `test_route_returns_200` parametrized test (currently lines ~40–73). These hit `/shops`, `/shops/vaga`, etc. which used to return Jinja2 HTML but now return the SPA HTML (or will after the router cleanup). The SPA entry point is already covered by `test_spa_entry_point`.

2. The entire `VALIDATION_ROUTES` list and `test_validation_routes_return_200` parametrized test (currently lines ~75–105). The `/validation` route now returns a 301 redirect; individual filter combinations are tested via the API.

3. `test_nonexistent_shop_returns_404` — this hit the old Jinja2 route. The SPA returns 200 (serves the shell) for unknown shops.

Also remove these now-unused imports at the top if no other test uses them:
- `ShopBook` (check if used by other tests before removing)

- [ ] **Step 2: Add redirect tests**

Add after `test_spa_entry_point`:

```python
@pytest.mark.integration
def test_validation_redirects_to_issues(client: TestClient) -> None:
    resp = client.get("/validation", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/issues"


@pytest.mark.integration
def test_validation_redirects_preserves_query_string(client: TestClient) -> None:
    resp = client.get("/validation?run_id=42&state=new", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/issues?run_id=42&state=new"


@pytest.mark.integration
def test_not_listed_redirects_to_shop_detail(client: TestClient) -> None:
    resp = client.get("/shops/vaga/not-listed", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/shops/vaga"
```

- [ ] **Step 3: Run the updated test file**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```
Expected: All tests pass. The removed tests are gone; new redirect tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_dashboard_routes.py
git commit -m "test: replace Jinja2 route tests with SPA/redirect coverage"
```

---

### Task 7: Drop the `jinja2` dependency from `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

After Task 4, nothing in our code imports Jinja2. FastAPI's `Jinja2Templates` was the only consumer, and it's gone. Remove the explicit dependency and the deptry-ignore comment so dependency hygiene reflects reality. Starlette will not pull Jinja2 in transitively unless `Jinja2Templates` is imported, so dropping it is safe.

- [ ] **Step 1: Remove the dependency**

In `pyproject.toml`'s `[project] dependencies` array, delete the line:
```toml
    "jinja2>=3.1",
```

Also delete the matching deptry-ignore comment further down the file:
```toml
    "jinja2",              # used by FastAPI's Jinja2Templates (starlette dependency)
```
(Find it via `grep -n "jinja2" pyproject.toml` — both occurrences.)

- [ ] **Step 2: Resync the lockfile and verify**

```bash
uv sync --all-extras
uv run python -c "from book_scraper.dashboard.app import app; print('OK')"
make deps
```
Expected: `OK`, and `make deps` does not flag `jinja2` as missing or unused.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: drop jinja2 dependency now that the dashboard is React-only"
```

---

### Task 8: Rebuild dashboard and run full smoke test

**Files:** None (Docker)

- [ ] **Step 1: Rebuild dashboard image**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

- [ ] **Step 2: Verify new code is in the container**

```bash
docker exec book-scraper-dashboard-1 python -c "from book_scraper.dashboard.app import app; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Smoke-test the redirects live**

```bash
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:8000/validation
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:8000/validation?run_id=42
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:8000/shops/vaga/not-listed
```
Expected:
```
301 http://localhost:8000/issues
301 http://localhost:8000/issues?run_id=42
301 http://localhost:8000/shops/vaga
```

- [ ] **Step 4: Smoke-test key SPA + API routes**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/runs
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/issues
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/runs
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/issues
```
Expected: all 200.

- [ ] **Step 5: Run full integration test suite**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
uv run pytest tests/unit tests/integration -q
```
Expected: all pass. The second command catches lingering import errors from the deleted unit/cron tests if any were missed.

- [ ] **Step 6: Final commit if any fixups were needed**

```bash
git add -A
git commit -m "chore: post-cleanup fixups after Jinja2 dashboard removal"
```

---

## Acceptance Criteria

- `book_scraper/dashboard/templates/` directory is gone
- `routes/runs.py`, `routes/urls.py`, `routes/shop_books.py`, `routes/validation.py`, `routes/cron.py`, `routes/prices.py` are gone
- `routes/shops.py` has ≤60 lines, only `_upsert_setting` and `update_rate_settings`
- `deps.py` has no `Jinja2Templates` reference
- `app.py` has no `templates.env.*` lines and no `include_router` for deleted modules
- `GET /validation` → 301 to `/issues` (query string preserved)
- `GET /shops/{name}/not-listed` → 301 to `/shops/{name}` (registered before SPA catch-all loops)
- `tests/unit/test_relative_time.py`, `tests/unit/test_change_diff.py`, `tests/integration/test_cron_routes.py`, `tests/integration/test_cron_run_now.py` are gone
- `pyproject.toml` no longer lists `jinja2>=3.1` and the deptry-ignore comment for it is removed
- All SPA pages still load (`/`, `/runs`, `/issues`, `/shop-books`, `/shops`, `/cron`)
- All API routes still respond 200 (`/api/runs`, `/api/issues`, `/api/shops`, `/api/shop-books`)
- `POST /shops/{name}/rate-settings` still works (SPA rate-settings dialog)
- `uv run pytest tests/unit tests/integration` passes — no collection errors, no failures from deleted helpers/endpoints
