# Issues Page Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the collapsible grouped `/validation` page with a flat, filterable list patterned on `/shop-books`, and drop the info-level `field_missing` issue type from the pipeline.

**Architecture:** The new `/validation` route queries `validation_issues` joined with `scrape_runs` (for shop + started_at) and LEFT JOINed to `shop_books` (for title resolution). A single template renders stat strip, lifecycle tabs, filter bar, data table, and pagination. Bulk acknowledge/delete operate on the active filter, not on row selection.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, SQLAlchemy 2.0, Alembic, Pico CSS. Tests use pytest + real PostgreSQL (Docker on port 5433).

**Spec:** `docs/superpowers/specs/2026-04-17-issues-page-redesign-design.md`

---

## File Structure

**Modify:**
- `book_scraper/pipelines.py` — remove `_report_empty_fields` calls and the `field_missing` issue emission
- `book_scraper/dashboard/queries.py` — add `get_issues_page`, update `get_validation_lifecycle_counts`, remove unused group helpers
- `book_scraper/db/repo.py` — update `acknowledge_validation_issues_bulk` signature + add `delete_validation_issues_matching`
- `book_scraper/dashboard/routes/validation.py` — rewrite the whole router
- `book_scraper/dashboard/templates/validation.html` — rewrite using the shop_books pattern
- `book_scraper/dashboard/templates/overview.html:93` — update legacy `/validation/{type}` link
- `book_scraper/dashboard/templates/run_detail.html:83` — update legacy `/validation/{type}?run_id=` link
- `tests/integration/test_dashboard_routes.py` — add route smoke tests
- `tests/unit/test_pipelines.py` (or equivalent) — add test asserting no `field_missing` emission

**Delete:**
- `book_scraper/dashboard/templates/validation_detail.html`
- `book_scraper/dashboard/templates/validation_rows.html`

**Keep (reused):**
- `book_scraper/dashboard/templates/macros.html` — `sort_header` macro is reused

---

## Task 1: Drop `field_missing` from the pipeline

**Files:**
- Modify: `book_scraper/pipelines.py:486-516` (`_report_empty_fields` method) and `book_scraper/pipelines.py:615-619` (call site)
- Test: `tests/unit/test_pipelines.py` (create or extend)

- [ ] **Step 1: Find or create the test file**

Run: `ls tests/unit/test_pipelines.py 2>/dev/null || echo MISSING`

If missing, create `tests/unit/test_pipelines.py` with the imports:

```python
from scrapy.utils.project import get_project_settings
from book_scraper.items import ShopBookItem
from book_scraper.pipelines import ValidationPipeline
```

- [ ] **Step 2: Write failing test for no `field_missing` emission**

Add to `tests/unit/test_pipelines.py`:

```python
def test_validation_pipeline_does_not_emit_field_missing() -> None:
    """ValidationPipeline no longer tracks field_missing — it was info-level noise."""
    pipeline = ValidationPipeline()
    # Simulate a full scrape where a previously-populated field is now empty.
    # Prior behavior: _report_empty_fields emitted a 'field_missing' issue.
    # New behavior: the method is gone or inert — no issue emitted.
    assert not any(
        issue.get("issue") == "field_missing" for issue in pipeline.drain_issues()
    )
    # Also verify the helper is gone so future regressions fail fast.
    assert not hasattr(pipeline, "_report_empty_fields"), (
        "_report_empty_fields should be removed; field_missing is no longer tracked"
    )
```

- [ ] **Step 3: Run test to confirm it fails**

Run: `uv run pytest tests/unit/test_pipelines.py::test_validation_pipeline_does_not_emit_field_missing -v`

Expected: FAIL — `_report_empty_fields` still exists.

- [ ] **Step 4: Remove the `_report_empty_fields` method**

Open `book_scraper/pipelines.py`. Delete the entire method (including the `_WATCHED_EMPTY_FIELDS` tuple) starting at `_WATCHED_EMPTY_FIELDS = (` through the closing of `_report_empty_fields`. These are roughly lines 476-516.

- [ ] **Step 5: Remove the call site**

In `book_scraper/pipelines.py`, delete this call (around line 615):

```python
                self._report_empty_fields(
                    adapter["url"],
                    adapter,
                    prior_values,
                )
```

Check whether `prior_values` is still used for any other purpose. Run:

```bash
uv run grep -n prior_values book_scraper/pipelines.py
```

If `prior_values` is only used by the deleted call, delete its assignment too. Otherwise leave it.

- [ ] **Step 6: Run the test to confirm it passes**

Run: `uv run pytest tests/unit/test_pipelines.py::test_validation_pipeline_does_not_emit_field_missing -v`

Expected: PASS.

- [ ] **Step 7: Run the full unit suite to confirm nothing regressed**

Run: `uv run pytest tests/unit/ -q`

Expected: PASS (all tests green).

- [ ] **Step 8: Commit**

```bash
git add book_scraper/pipelines.py tests/unit/test_pipelines.py
git commit -m "drop field_missing validation issue (info-level noise)"
```

---

## Task 2: Remove `field_missing` from severity + description maps

**Files:**
- Modify: `book_scraper/dashboard/queries.py` (the `ISSUE_DESCRIPTIONS` and `ISSUE_SEVERITY` dicts added in the previous redesign)
- Test: `tests/unit/test_validation_metadata.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_validation_metadata.py`:

```python
from book_scraper.dashboard.queries import ISSUE_DESCRIPTIONS, ISSUE_SEVERITY


def test_field_missing_removed_from_metadata() -> None:
    assert "field_missing" not in ISSUE_DESCRIPTIONS
    assert "field_missing" not in ISSUE_SEVERITY


def test_all_issue_types_are_critical_or_warning() -> None:
    """No info-level issues remain after the redesign."""
    assert set(ISSUE_SEVERITY.values()) <= {"critical", "warning"}
```

- [ ] **Step 2: Run it to confirm failure**

Run: `uv run pytest tests/unit/test_validation_metadata.py -v`

Expected: FAIL — `field_missing` still present.

- [ ] **Step 3: Remove `field_missing` from both maps**

In `book_scraper/dashboard/queries.py`, delete these two entries:

From `ISSUE_DESCRIPTIONS`:

```python
    "field_missing": (
        "A field that previously had a value is now empty."
        " Data disappeared or was removed from the shop page."
    ),
```

From `ISSUE_SEVERITY`:

```python
    "field_missing": "info",
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `uv run pytest tests/unit/test_validation_metadata.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/queries.py tests/unit/test_validation_metadata.py
git commit -m "remove field_missing from severity + description maps"
```

---

## Task 3: Add `get_issues_page` query function

**Files:**
- Modify: `book_scraper/dashboard/queries.py`
- Test: `tests/integration/test_validation_queries.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_validation_queries.py`:

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from book_scraper.dashboard.queries import get_issues_page
from book_scraper.db.models import ScrapeRun, Shop, ShopBook, ValidationIssue


def _seed(db_session: Session) -> tuple[int, int]:
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    run = ScrapeRun(
        shop_id=shop.id,
        phase="scan",
        status="completed",
        started_at=datetime(2026, 4, 17, 15, 0, 0, tzinfo=UTC),
    )
    db_session.add(run)
    db_session.flush()
    book = ShopBook(
        shop_id=shop.id,
        url="https://vaga.lt/x",
        title="Test Book",
    )
    db_session.add(book)
    db_session.flush()
    db_session.add_all(
        [
            ValidationIssue(
                scrape_run_id=run.id,
                url="https://vaga.lt/x",
                field="title",
                issue="suspicious_title",
                raw_value="short",
                shop_book_id=book.id,
                lifecycle_state="new",
            ),
            ValidationIssue(
                scrape_run_id=run.id,
                url="https://vaga.lt/y",
                field="price",
                issue="missing_price",
                raw_value=None,
                shop_book_id=None,
                lifecycle_state="recurring",
            ),
        ]
    )
    db_session.flush()
    return shop.id, run.id


@pytest.mark.integration
def test_get_issues_page_returns_paginated_rows(db_session: Session) -> None:
    shop_id, run_id = _seed(db_session)
    rows, total = get_issues_page(
        db_session, state="open", page=1, per_page=50
    )
    assert total == 2
    assert len(rows) == 2
    # Newest-first by scrape_runs.started_at then by id
    assert rows[0]["issue"] in {"suspicious_title", "missing_price"}
    assert rows[0]["added_at"] is not None


@pytest.mark.integration
def test_get_issues_page_filters_by_shop(db_session: Session) -> None:
    shop_id, _ = _seed(db_session)
    rows, total = get_issues_page(
        db_session, state="open", shop_id=shop_id, page=1, per_page=50
    )
    assert total == 2


@pytest.mark.integration
def test_get_issues_page_filters_by_issue_type(db_session: Session) -> None:
    _seed(db_session)
    rows, total = get_issues_page(
        db_session,
        state="open",
        issue_type="missing_price",
        page=1,
        per_page=50,
    )
    assert total == 1
    assert rows[0]["issue"] == "missing_price"


@pytest.mark.integration
def test_get_issues_page_filters_by_run_id(db_session: Session) -> None:
    _, run_id = _seed(db_session)
    rows, total = get_issues_page(
        db_session, state="open", run_id=run_id, page=1, per_page=50
    )
    assert total == 2
    assert all(r["scrape_run_id"] == run_id for r in rows)


@pytest.mark.integration
def test_get_issues_page_search_matches_title_or_url(db_session: Session) -> None:
    _seed(db_session)
    # Match by book title
    rows, total = get_issues_page(
        db_session, state="open", q="Test Book", page=1, per_page=50
    )
    assert total == 1
    assert rows[0]["shop_book_title"] == "Test Book"
    # Match by URL substring for unresolved book
    rows, total = get_issues_page(
        db_session, state="open", q="vaga.lt/y", page=1, per_page=50
    )
    assert total == 1
    assert rows[0]["url"] == "https://vaga.lt/y"


@pytest.mark.integration
def test_get_issues_page_sort_order(db_session: Session) -> None:
    _seed(db_session)
    rows_desc, _ = get_issues_page(
        db_session, state="open", order="desc", page=1, per_page=50
    )
    rows_asc, _ = get_issues_page(
        db_session, state="open", order="asc", page=1, per_page=50
    )
    # Both return same set, but reversed
    assert [r["id"] for r in rows_desc] == list(reversed([r["id"] for r in rows_asc]))
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `uv run pytest tests/integration/test_validation_queries.py -v`

Expected: FAIL — `get_issues_page` does not exist.

- [ ] **Step 3: Add `get_issues_page` to `queries.py`**

In `book_scraper/dashboard/queries.py`, add this function after `get_validation_lifecycle_counts`:

```python
def get_issues_page(
    session: Session,
    state: str | None = "open",
    shop_id: int | None = None,
    issue_type: str = "",
    run_id: int | None = None,
    q: str = "",
    order: str = "desc",
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Return paginated flat list of validation issues with filters.

    Rows are sorted by scrape_runs.started_at (then ValidationIssue.id) to
    approximate per-issue creation time without adding a column.

    Returns (rows, total).
    """
    from sqlalchemy import or_

    query = (
        session.query(ValidationIssue, ScrapeRun, ShopBook)
        .join(ScrapeRun, ValidationIssue.scrape_run_id == ScrapeRun.id)
        .outerjoin(ShopBook, ValidationIssue.shop_book_id == ShopBook.id)
    )

    if state in {"new", "recurring", "already_seen"}:
        query = query.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        query = query.filter(ValidationIssue.lifecycle_state != "already_seen")

    if shop_id is not None:
        query = query.filter(ScrapeRun.shop_id == shop_id)
    if issue_type:
        query = query.filter(ValidationIssue.issue == issue_type)
    if run_id is not None:
        query = query.filter(ValidationIssue.scrape_run_id == run_id)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(ValidationIssue.url.ilike(pattern), ShopBook.title.ilike(pattern))
        )

    total = query.count()

    if order == "asc":
        query = query.order_by(
            ScrapeRun.started_at.asc().nulls_last(), ValidationIssue.id.asc()
        )
    else:
        query = query.order_by(
            ScrapeRun.started_at.desc().nulls_last(), ValidationIssue.id.desc()
        )

    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    result: list[dict[str, Any]] = []
    for issue, run, shop_book in rows:
        result.append(
            {
                "id": issue.id,
                "url": issue.url,
                "field": issue.field,
                "issue": issue.issue,
                "raw_value": issue.raw_value,
                "scrape_run_id": issue.scrape_run_id,
                "shop_book_id": issue.shop_book_id,
                "shop_book_title": shop_book.title if shop_book else None,
                "lifecycle_state": issue.lifecycle_state,
                "added_at": run.started_at,
                "severity": ISSUE_SEVERITY.get(issue.issue, "warning"),
            }
        )
    return result, total
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `uv run pytest tests/integration/test_validation_queries.py -v`

Expected: PASS (all six tests).

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/queries.py tests/integration/test_validation_queries.py
git commit -m "add get_issues_page flat query (filters + pagination)"
```

---

## Task 4: Update `get_validation_lifecycle_counts` to accept full filter set

**Files:**
- Modify: `book_scraper/dashboard/queries.py` (`get_validation_lifecycle_counts`)
- Test: extend `tests/integration/test_validation_queries.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_validation_queries.py`:

```python
from book_scraper.dashboard.queries import get_validation_lifecycle_counts


@pytest.mark.integration
def test_lifecycle_counts_filters_by_issue_type_and_run(db_session: Session) -> None:
    _, run_id = _seed(db_session)
    counts = get_validation_lifecycle_counts(
        db_session,
        issue_type="missing_price",
        run_id=run_id,
    )
    assert counts["recurring"] == 1
    assert counts["new"] == 0
    assert counts["open"] == 1
```

- [ ] **Step 2: Run the test to confirm failure**

Run: `uv run pytest tests/integration/test_validation_queries.py::test_lifecycle_counts_filters_by_issue_type_and_run -v`

Expected: FAIL — `get_validation_lifecycle_counts` does not accept those kwargs.

- [ ] **Step 3: Widen the signature**

In `book_scraper/dashboard/queries.py`, replace `get_validation_lifecycle_counts` with:

```python
def get_validation_lifecycle_counts(
    session: Session,
    shop_id: int | None = None,
    issue_type: str = "",
    run_id: int | None = None,
    q: str = "",
) -> dict[str, int]:
    from sqlalchemy import or_

    query = session.query(
        ValidationIssue.lifecycle_state,
        func.count(ValidationIssue.id).label("count"),
    )
    if shop_id is not None or q:
        query = query.join(ScrapeRun, ValidationIssue.scrape_run_id == ScrapeRun.id)
    if shop_id is not None:
        query = query.filter(ScrapeRun.shop_id == shop_id)
    if issue_type:
        query = query.filter(ValidationIssue.issue == issue_type)
    if run_id is not None:
        query = query.filter(ValidationIssue.scrape_run_id == run_id)
    if q:
        pattern = f"%{q}%"
        query = query.outerjoin(
            ShopBook, ValidationIssue.shop_book_id == ShopBook.id
        ).filter(
            or_(ValidationIssue.url.ilike(pattern), ShopBook.title.ilike(pattern))
        )

    rows = query.group_by(ValidationIssue.lifecycle_state).all()
    counts = {"new": 0, "recurring": 0, "already_seen": 0}
    for r in rows:
        counts[r.lifecycle_state] = r.count
    counts["open"] = counts["new"] + counts["recurring"]
    return counts
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `uv run pytest tests/integration/test_validation_queries.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/queries.py tests/integration/test_validation_queries.py
git commit -m "extend lifecycle counts to accept full issue filter set"
```

---

## Task 5: Widen `acknowledge_validation_issues_bulk` + add `delete_validation_issues_matching`

**Files:**
- Modify: `book_scraper/db/repo.py` (`acknowledge_validation_issues_bulk`)
- Test: `tests/integration/test_validation_repo.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/integration/test_validation_repo.py`:

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from book_scraper.db.models import ScrapeRun, Shop, ValidationIssue
from book_scraper.db.repo import (
    acknowledge_validation_issues_bulk,
    delete_validation_issues_matching,
)


def _make_two_issues(db_session: Session) -> tuple[int, int, int]:
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    run = ScrapeRun(
        shop_id=shop.id, phase="scan", status="completed",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            ValidationIssue(
                scrape_run_id=run.id, url="https://vaga.lt/a",
                field="title", issue="suspicious_title",
                lifecycle_state="new",
            ),
            ValidationIssue(
                scrape_run_id=run.id, url="https://vaga.lt/b",
                field="price", issue="missing_price",
                lifecycle_state="new",
            ),
        ]
    )
    db_session.flush()
    return shop.id, run.id, db_session.query(ValidationIssue).count()


@pytest.mark.integration
def test_ack_bulk_respects_issue_type_filter(db_session: Session) -> None:
    _make_two_issues(db_session)
    updated = acknowledge_validation_issues_bulk(
        db_session, issue_type="missing_price"
    )
    assert updated == 1
    remaining_open = (
        db_session.query(ValidationIssue)
        .filter(ValidationIssue.lifecycle_state != "already_seen")
        .count()
    )
    assert remaining_open == 1


@pytest.mark.integration
def test_ack_bulk_respects_run_id_filter(db_session: Session) -> None:
    _, run_id, _ = _make_two_issues(db_session)
    updated = acknowledge_validation_issues_bulk(db_session, run_id=run_id)
    assert updated == 2


@pytest.mark.integration
def test_delete_matching_hard_deletes(db_session: Session) -> None:
    _, _, total = _make_two_issues(db_session)
    assert total == 2
    deleted = delete_validation_issues_matching(
        db_session, issue_type="missing_price"
    )
    assert deleted == 1
    remaining = db_session.query(ValidationIssue).count()
    assert remaining == 1


@pytest.mark.integration
def test_delete_matching_requires_at_least_one_filter(db_session: Session) -> None:
    _make_two_issues(db_session)
    with pytest.raises(ValueError):
        delete_validation_issues_matching(db_session)
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `uv run pytest tests/integration/test_validation_repo.py -v`

Expected: FAIL — `delete_validation_issues_matching` does not exist, and `acknowledge_validation_issues_bulk` does not accept `run_id`.

- [ ] **Step 3: Replace `acknowledge_validation_issues_bulk` in `book_scraper/db/repo.py`**

Find the existing function (grep `def acknowledge_validation_issues_bulk`) and replace it with:

```python
def acknowledge_validation_issues_bulk(
    session: Session,
    issue_type: str | None = None,
    state: str | None = None,
    shop_id: int | None = None,
    run_id: int | None = None,
    q: str = "",
) -> int:
    """Bulk-acknowledge open issues matching the filter set. Returns count updated.

    Any combination of filters is allowed. Passing no filters at all
    acknowledges every open issue (callers wanting the global 'ack all
    open' behaviour rely on this).
    """
    from sqlalchemy import or_

    from book_scraper.db.models import ShopBook

    now = datetime.now(UTC)
    query = session.query(ValidationIssue).filter(
        ValidationIssue.lifecycle_state != "already_seen"
    )
    if issue_type is not None:
        query = query.filter(ValidationIssue.issue == issue_type)
    if state in {"new", "recurring"}:
        query = query.filter(ValidationIssue.lifecycle_state == state)
    if shop_id is not None or q:
        query = query.join(ScrapeRun, ValidationIssue.scrape_run_id == ScrapeRun.id)
    if shop_id is not None:
        query = query.filter(ScrapeRun.shop_id == shop_id)
    if run_id is not None:
        query = query.filter(ValidationIssue.scrape_run_id == run_id)
    if q:
        pattern = f"%{q}%"
        query = query.outerjoin(
            ShopBook, ValidationIssue.shop_book_id == ShopBook.id
        ).filter(
            or_(ValidationIssue.url.ilike(pattern), ShopBook.title.ilike(pattern))
        )
    issues = query.all()
    for issue in issues:
        issue.lifecycle_state = "already_seen"
        issue.acknowledged_at = now
    session.flush()
    return len(issues)
```

- [ ] **Step 4: Add `delete_validation_issues_matching`**

Append this to `book_scraper/db/repo.py` directly after `acknowledge_validation_issues_bulk`:

```python
def delete_validation_issues_matching(
    session: Session,
    issue_type: str | None = None,
    state: str | None = None,
    shop_id: int | None = None,
    run_id: int | None = None,
    q: str = "",
) -> int:
    """Hard-delete validation issues matching the filter. Returns count deleted.

    At least one filter must be set — a guardrail to prevent the UI
    from wiping the whole table with an unintended empty request.
    """
    from sqlalchemy import or_

    from book_scraper.db.models import ShopBook

    if not (issue_type or state or shop_id or run_id or q):
        raise ValueError(
            "delete_validation_issues_matching requires at least one filter"
        )

    query = session.query(ValidationIssue)
    if issue_type is not None:
        query = query.filter(ValidationIssue.issue == issue_type)
    if state in {"new", "recurring", "already_seen"}:
        query = query.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        query = query.filter(ValidationIssue.lifecycle_state != "already_seen")
    if shop_id is not None or q:
        query = query.join(ScrapeRun, ValidationIssue.scrape_run_id == ScrapeRun.id)
    if shop_id is not None:
        query = query.filter(ScrapeRun.shop_id == shop_id)
    if run_id is not None:
        query = query.filter(ValidationIssue.scrape_run_id == run_id)
    if q:
        pattern = f"%{q}%"
        query = query.outerjoin(
            ShopBook, ValidationIssue.shop_book_id == ShopBook.id
        ).filter(
            or_(ValidationIssue.url.ilike(pattern), ShopBook.title.ilike(pattern))
        )
    ids = [i.id for i in query.all()]
    if not ids:
        return 0
    session.query(ValidationIssue).filter(ValidationIssue.id.in_(ids)).delete(
        synchronize_session=False
    )
    session.flush()
    return len(ids)
```

- [ ] **Step 5: Run tests to confirm pass**

Run: `uv run pytest tests/integration/test_validation_repo.py -v`

Expected: PASS (all four tests).

- [ ] **Step 6: Commit**

```bash
git add book_scraper/db/repo.py tests/integration/test_validation_repo.py
git commit -m "widen bulk-ack filter + add delete_validation_issues_matching"
```

---

## Task 6: Remove unused group helpers from `queries.py`

**Files:**
- Modify: `book_scraper/dashboard/queries.py`

- [ ] **Step 1: Delete `get_validation_groups`**

In `book_scraper/dashboard/queries.py`, find and delete the entire `def get_validation_groups(...)` function and its body (roughly 30 lines).

- [ ] **Step 2: Delete `get_validation_issues_for_group`**

In the same file, delete the entire `def get_validation_issues_for_group(...)` function and its body (roughly 45 lines).

- [ ] **Step 3: Verify no references remain**

Run:

```bash
uv run grep -rn "get_validation_groups\|get_validation_issues_for_group" book_scraper tests
```

Expected: no output.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/queries.py
git commit -m "remove unused validation-group helpers"
```

---

## Task 7: Rewrite `routes/validation.py`

**Files:**
- Modify: `book_scraper/dashboard/routes/validation.py` (full rewrite)
- Test: extend `tests/integration/test_dashboard_routes.py`

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/integration/test_dashboard_routes.py`:

```python
VALIDATION_ROUTES = [
    "/validation",
    "/validation?state=open",
    "/validation?state=new",
    "/validation?state=recurring",
    "/validation?state=already_seen",
    "/validation?state=all",
    "/validation?shop=vaga",
    "/validation?issue_type=missing_price",
    "/validation?run_id=1",
    "/validation?q=test",
    "/validation?shop=vaga&issue_type=missing_price&run_id=1&q=a",
    "/validation?order=asc",
    "/validation?page=2",
    "/validation?page=9999",  # out-of-range page clamps silently
]


@pytest.mark.integration
@pytest.mark.parametrize("route", VALIDATION_ROUTES)
def test_validation_routes_return_200(client: TestClient, route: str) -> None:
    response = client.get(route)
    assert response.status_code == 200, f"{route} returned {response.status_code}"


@pytest.mark.integration
def test_legacy_validation_detail_route_is_gone(client: TestClient) -> None:
    response = client.get("/validation/missing_price")
    assert response.status_code == 404


@pytest.mark.integration
def test_acknowledge_all_accepts_full_filter_set(client: TestClient) -> None:
    response = client.post(
        "/validation-issues/acknowledge-all",
        data={
            "issue_type": "missing_price",
            "state": "open",
            "shop": "",
            "run_id": "",
            "q": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.mark.integration
def test_delete_matching_requires_filter(client: TestClient) -> None:
    # state='all' + every other filter empty = truly unfiltered → repo raises, route 400s
    response = client.post(
        "/validation-issues/delete-matching",
        data={"issue_type": "", "state": "all", "shop": "", "run_id": "", "q": ""},
        follow_redirects=False,
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `uv run pytest tests/integration/test_dashboard_routes.py -v -k validation`

Expected: FAIL — new routes don't exist.

- [ ] **Step 3: Rewrite the validation router**

Replace the entire contents of `book_scraper/dashboard/routes/validation.py` with:

```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse, Response

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    ISSUE_DESCRIPTIONS,
    ISSUE_SEVERITY,
    get_all_shops,
    get_issues_page,
    get_shop_by_name,
    get_validation_lifecycle_counts,
)
from book_scraper.db.repo import (
    acknowledge_validation_issue,
    acknowledge_validation_issues_bulk,
    delete_validation_issues_matching,
)

router = APIRouter()

_VALID_STATES = {"open", "new", "recurring", "already_seen", "all"}
_PER_PAGE = 50


def _normalize_state(state: str | None) -> str:
    return state if state in _VALID_STATES else "open"


def _resolve_shop_id(session: Session, shop: str) -> int | None:
    if not shop:
        return None
    obj = get_shop_by_name(session, shop)
    return obj.id if obj else None


def _filter_params(
    state: str, shop: str, issue_type: str, run_id: str, q: str, order: str
) -> str:
    """Render a query string for paginate/ack/delete links preserving filters."""
    parts: list[str] = []
    if state:
        parts.append(f"state={state}")
    if shop:
        parts.append(f"shop={shop}")
    if issue_type:
        parts.append(f"issue_type={issue_type}")
    if run_id:
        parts.append(f"run_id={run_id}")
    if q:
        parts.append(f"q={q}")
    if order:
        parts.append(f"order={order}")
    return "&".join(parts)


@router.get("/validation")
def validation_list(
    request: Request,
    state: str = "open",
    shop: str = "",
    issue_type: str = "",
    run_id: int | None = None,
    q: str = "",
    order: str = "desc",
    page: int = 1,
    session: Session = Depends(get_db),
) -> Response:
    state = _normalize_state(state)
    lifecycle_state = None if state == "all" else state
    shop_id = _resolve_shop_id(session, shop)

    rows, total = get_issues_page(
        session,
        state=lifecycle_state,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id,
        q=q,
        order=order,
        page=max(page, 1),
        per_page=_PER_PAGE,
    )
    total_pages = max((total + _PER_PAGE - 1) // _PER_PAGE, 1)
    counts = get_validation_lifecycle_counts(
        session,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id,
        q=q,
    )
    shops = get_all_shops(session)

    # All known issue types — feed the filter dropdown grouped by severity.
    critical_types = sorted(k for k, v in ISSUE_SEVERITY.items() if v == "critical")
    warning_types = sorted(k for k, v in ISSUE_SEVERITY.items() if v == "warning")

    return templates.TemplateResponse(
        request,
        "validation.html",
        {
            "active_page": "issues",
            "rows": rows,
            "total": total,
            "page": max(page, 1),
            "per_page": _PER_PAGE,
            "total_pages": total_pages,
            "lifecycle_state": state,
            "lifecycle_counts": counts,
            "shops": shops,
            "selected_shop": shop,
            "selected_issue_type": issue_type,
            "selected_run_id": run_id,
            "q": q,
            "order": order,
            "critical_types": critical_types,
            "warning_types": warning_types,
            "issue_descriptions": ISSUE_DESCRIPTIONS,
            "filter_params": _filter_params(
                state, shop, issue_type, str(run_id) if run_id else "", q, order
            ),
        },
    )


@router.post("/validation-issues/{issue_id}/acknowledge")
def acknowledge_issue(
    issue_id: int,
    request: Request,
    session: Session = Depends(get_db),
) -> Response:
    if not acknowledge_validation_issue(session, issue_id):
        raise HTTPException(status_code=404, detail="Issue not found")
    session.commit()
    back = request.headers.get("referer") or "/validation"
    return RedirectResponse(url=back, status_code=303)


@router.post("/validation-issues/acknowledge-all")
def acknowledge_all(
    request: Request,
    issue_type: str = Form(""),
    state: str = Form("open"),
    shop: str = Form(""),
    run_id: str = Form(""),
    q: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    state_normalized = _normalize_state(state)
    lifecycle_state = None if state_normalized == "all" else state_normalized
    shop_id = _resolve_shop_id(session, shop)
    run_id_int = int(run_id) if run_id.strip() else None

    acknowledge_validation_issues_bulk(
        session,
        issue_type=issue_type or None,
        state=lifecycle_state,
        shop_id=shop_id,
        run_id=run_id_int,
        q=q,
    )
    session.commit()
    back = request.headers.get("referer") or "/validation"
    return RedirectResponse(url=back, status_code=303)


@router.post("/validation-issues/delete-matching")
def delete_matching(
    request: Request,
    issue_type: str = Form(""),
    state: str = Form("open"),
    shop: str = Form(""),
    run_id: str = Form(""),
    q: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    state_normalized = _normalize_state(state)
    lifecycle_state = None if state_normalized == "all" else state_normalized
    shop_id = _resolve_shop_id(session, shop)
    run_id_int = int(run_id) if run_id.strip() else None

    # Delegate the "at least one filter" guard to the repo (ValueError → 400).
    try:
        delete_validation_issues_matching(
            session,
            issue_type=issue_type or None,
            state=lifecycle_state,
            shop_id=shop_id,
            run_id=run_id_int,
            q=q,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    session.commit()
    back = request.headers.get("referer") or "/validation"
    return RedirectResponse(url=back, status_code=303)
```

- [ ] **Step 4: Run validation route tests to confirm pass**

Run: `uv run pytest tests/integration/test_dashboard_routes.py -v -k validation`

Expected: PASS on all newly-added routes. `test_legacy_validation_detail_route_is_gone` passes because the old `/validation/{issue_type}` handler is no longer registered.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/routes/validation.py tests/integration/test_dashboard_routes.py
git commit -m "rewrite /validation router as flat-list with filter + delete-matching"
```

---

## Task 8: Rewrite `validation.html` template

**Files:**
- Rewrite: `book_scraper/dashboard/templates/validation.html`

- [ ] **Step 1: Replace the template**

Overwrite `book_scraper/dashboard/templates/validation.html` with:

```html
{% extends "base.html" %}
{% from "macros.html" import sort_header %}
{% block title %}Issues{% endblock %}
{% block content %}
<h1 class="page-title">Issues</h1>

{% set state = lifecycle_state or 'open' %}

{# ── Stat strip ──────────────────────────────────────────────── #}
<div class="stat-strip">
    <div class="stat-chip"><span class="sc-label">Open</span>
        <span class="sc-value" style="color:var(--badge-error-fg)">{{ lifecycle_counts.open }}</span></div>
    <div class="stat-chip"><span class="sc-label">New</span>
        <span class="sc-value" style="color:var(--badge-warning-fg)">{{ lifecycle_counts.new }}</span></div>
    <div class="stat-chip"><span class="sc-label">Recurring</span>
        <span class="sc-value">{{ lifecycle_counts.recurring }}</span></div>
    <div class="stat-chip"><span class="sc-label">Acknowledged</span>
        <span class="sc-value" style="color:var(--text-secondary)">{{ lifecycle_counts.already_seen }}</span></div>
</div>

{# ── Lifecycle tabs ─────────────────────────────────────────── #}
{% set base = 'shop=' ~ selected_shop|urlencode ~ '&issue_type=' ~ selected_issue_type|urlencode ~ ('&run_id=' ~ selected_run_id if selected_run_id else '') ~ '&q=' ~ q|urlencode ~ '&order=' ~ order %}
<div class="tab-row">
    {% for label, val in [('Open','open'),('New','new'),('Recurring','recurring'),('Acknowledged','already_seen'),('All','all')] %}
    <a href="/validation?state={{ val }}&{{ base }}"
       class="{{ 'tab-active' if state == val else 'tab-inactive' }}">
        {{ label }}{% if val in lifecycle_counts %} ({{ lifecycle_counts[val] }}){% endif %}
    </a>
    {% endfor %}
</div>

{# ── Filter bar ──────────────────────────────────────────────── #}
<form method="get" action="/validation">
    <input type="hidden" name="state" value="{{ state }}">
    <input type="hidden" name="order" value="{{ order }}">
    <div class="filter-bar">
        <label>Shop</label>
        <select name="shop">
            <option value="">All shops</option>
            {% for s in shops %}
            <option value="{{ s.name }}" {{ 'selected' if s.name == selected_shop }}>{{ s.name }}</option>
            {% endfor %}
        </select>

        <label>Issue</label>
        <select name="issue_type">
            <option value="">All types</option>
            <optgroup label="Critical">
                {% for t in critical_types %}
                <option value="{{ t }}" {{ 'selected' if t == selected_issue_type }}>{{ t }}</option>
                {% endfor %}
            </optgroup>
            <optgroup label="Warning">
                {% for t in warning_types %}
                <option value="{{ t }}" {{ 'selected' if t == selected_issue_type }}>{{ t }}</option>
                {% endfor %}
            </optgroup>
        </select>

        <label>Run</label>
        <input type="number" name="run_id" placeholder="#" style="width:90px"
               value="{{ selected_run_id or '' }}">

        <label>Search</label>
        <input type="search" name="q" placeholder="Book or URL..." value="{{ q }}">

        <button type="submit">Filter</button>
        {% if selected_shop or selected_issue_type or selected_run_id or q %}
        <a href="/validation?state={{ state }}" role="button" class="secondary">Reset</a>
        {% endif %}
    </div>
</form>

{# ── Action bar ──────────────────────────────────────────────── #}
<div class="action-bar">
    <span class="result-count">
        {% if total == 0 %}
            No issues match the current filter.
        {% else %}
            Showing <b>{{ (page - 1) * per_page + 1 }}–{{ page * per_page if page * per_page < total else total }}</b> of <b>{{ "{:,}".format(total) }}</b>
            {{ state }}{% if selected_shop %} · shop: <b>{{ selected_shop }}</b>{% endif %}{% if selected_issue_type %} · type: <b>{{ selected_issue_type }}</b>{% endif %}{% if selected_run_id %} · run: <b>#{{ selected_run_id }}</b>{% endif %}
        {% endif %}
    </span>
    {% if total > 0 and state != 'already_seen' %}
    <div class="bulk-actions">
        <form method="post" action="/validation-issues/acknowledge-all" style="display:inline;"
              onsubmit="return confirm('Acknowledge {{ total }} matching issue(s)?');">
            <input type="hidden" name="issue_type" value="{{ selected_issue_type }}">
            <input type="hidden" name="state" value="{{ state }}">
            <input type="hidden" name="shop" value="{{ selected_shop }}">
            <input type="hidden" name="run_id" value="{{ selected_run_id or '' }}">
            <input type="hidden" name="q" value="{{ q }}">
            <button type="submit" class="bulk-btn">Acknowledge {{ total }} matching</button>
        </form>
        <form method="post" action="/validation-issues/delete-matching" style="display:inline;"
              onsubmit="return confirm('Permanently delete {{ total }} matching issue(s)? This cannot be undone.');">
            <input type="hidden" name="issue_type" value="{{ selected_issue_type }}">
            <input type="hidden" name="state" value="{{ state }}">
            <input type="hidden" name="shop" value="{{ selected_shop }}">
            <input type="hidden" name="run_id" value="{{ selected_run_id or '' }}">
            <input type="hidden" name="q" value="{{ q }}">
            <button type="submit" class="bulk-btn danger">Delete {{ total }} matching</button>
        </form>
    </div>
    {% endif %}
</div>

{# ── Table ──────────────────────────────────────────────────── #}
{% if rows %}
<div class="card" style="padding:0; overflow:hidden;">
<table class="data-table">
    <thead>
        <tr>
            <th style="width:28px"><input type="checkbox" disabled title="Row selection coming in v2"></th>
            <th>
                <a href="/validation?state={{ state }}&shop={{ selected_shop }}&issue_type={{ selected_issue_type }}&run_id={{ selected_run_id or '' }}&q={{ q }}&order={{ 'asc' if order == 'desc' else 'desc' }}">
                    Added <span class="sort-arrow">{{ '▼' if order == 'desc' else '▲' }}</span>
                </a>
            </th>
            <th>State</th>
            <th>Issue</th>
            <th>Field</th>
            <th>Book / URL</th>
            <th>Raw value</th>
            <th>Run</th>
            <th></th>
        </tr>
    </thead>
    <tbody>
        {% for r in rows %}
        <tr>
            <td><input type="checkbox" disabled></td>
            <td class="text-muted" style="white-space:nowrap;font-size:0.75rem;">
                {{ r.added_at.strftime('%Y-%m-%d %H:%M:%S') if r.added_at else '—' }}
            </td>
            <td>
                {% if r.lifecycle_state == 'new' %}
                    <span class="badge badge-error">new</span>
                {% elif r.lifecycle_state == 'recurring' %}
                    <span class="badge badge-warning">recurring</span>
                {% else %}
                    <span class="badge badge-neutral">seen</span>
                {% endif %}
            </td>
            <td>
                <span class="sev-dot sev-{{ r.severity }}"
                      title="{{ issue_descriptions.get(r.issue, '') }}"></span>
                <span class="issue-name">{{ r.issue }}</span>
            </td>
            <td class="text-muted">{{ r.field }}</td>
            <td>
                {% if r.shop_book_id %}
                    <a href="/shop-books/{{ r.shop_book_id }}" class="cell-truncate"
                       style="display:inline-block;max-width:240px;">
                        {{ r.shop_book_title or '—' }}
                    </a>
                {% else %}
                    <a href="{{ r.url }}" target="_blank" class="cell-truncate"
                       style="display:inline-block;max-width:240px;">{{ r.url }}</a>
                {% endif %}
            </td>
            <td>
                {% if r.raw_value %}
                    <span class="raw-trunc" title="{{ r.raw_value }}">
                        {{ r.raw_value[:60] }}{{ '…' if r.raw_value|length > 60 else '' }}
                    </span>
                {% else %}
                    <span class="text-muted">—</span>
                {% endif %}
            </td>
            <td><a href="/runs/{{ r.scrape_run_id }}" class="text-muted">#{{ r.scrape_run_id }}</a></td>
            <td>
                {% if r.lifecycle_state != 'already_seen' %}
                <form method="post" action="/validation-issues/{{ r.id }}/acknowledge" style="display:inline;">
                    <button type="submit" class="bulk-btn" style="padding:0.15rem 0.5rem">Ack</button>
                </form>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>

{# ── Pagination ─────────────────────────────────────────────── #}
{% if total_pages > 1 %}
<div class="pagination">
    {% if page > 1 %}
    <a href="/validation?page={{ page - 1 }}&{{ filter_params }}">← Prev</a>
    {% else %}
    <span class="disabled">← Prev</span>
    {% endif %}
    <span class="current">Page {{ page }} of {{ total_pages }}</span>
    {% if page < total_pages %}
    <a href="/validation?page={{ page + 1 }}&{{ filter_params }}">Next →</a>
    {% else %}
    <span class="disabled">Next →</span>
    {% endif %}
</div>
{% endif %}

{% else %}
<p class="text-muted" style="margin-top:1rem;">No issues match the current filter.</p>
{% endif %}

<style>
.stat-strip { display:flex; gap:1rem; margin-bottom:1rem; flex-wrap:wrap; }
.stat-chip  { background:var(--card-bg); border:1px solid var(--border); border-radius:8px;
              padding:0.55rem 0.9rem; display:flex; flex-direction:column; gap:0.1rem; min-width:90px; }
.sc-label   { font-size:0.68rem; font-weight:600; text-transform:uppercase;
              letter-spacing:0.05em; color:var(--text-secondary); }
.sc-value   { font-size:1.25rem; font-weight:700; line-height:1.1; }

.tab-row { display:flex; gap:0.25rem; margin-bottom:1rem; flex-wrap:wrap; }
.tab-row a { padding:0.35rem 0.8rem; font-size:0.8rem; color:var(--text-secondary);
             text-decoration:none; border-radius:4px; }
.tab-active   { background:var(--badge-running-bg); color:var(--badge-running-fg)!important; font-weight:600; }
.tab-inactive:hover { background:var(--table-hover); color:var(--text-primary); }

.action-bar { display:flex; align-items:center; justify-content:space-between; margin-bottom:0.5rem; flex-wrap:wrap; gap:0.5rem; }
.result-count { font-size:0.85rem; color:var(--text-secondary); }
.bulk-actions { display:flex; gap:0.4rem; }
.bulk-btn { font-size:0.8rem; padding:0.3rem 0.75rem; border-radius:4px; border:1px solid var(--border); background:var(--card-bg); cursor:pointer; color:var(--text-primary); }
.bulk-btn.danger { color:var(--badge-error-fg); border-color:var(--badge-error-fg); }

.sev-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:0.35rem; vertical-align:middle; }
.sev-critical { background:var(--badge-error-fg); }
.sev-warning  { background:var(--badge-warning-fg); }
.issue-name { font-family:monospace; font-size:0.8rem; }
.raw-trunc  { font-family:monospace; font-size:0.75rem; color:var(--text-secondary);
              max-width:220px; display:inline-block; overflow:hidden;
              text-overflow:ellipsis; white-space:nowrap; vertical-align:middle; }
</style>
{% endblock %}
```

- [ ] **Step 2: Run smoke tests**

Run: `uv run pytest tests/integration/test_dashboard_routes.py -v -k validation`

Expected: PASS on all 14 new validation routes.

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/templates/validation.html
git commit -m "rewrite validation.html as flat list with filter bar + pagination"
```

---

## Task 9: Update legacy `/validation/{type}` links to new filter query

**Files:**
- Modify: `book_scraper/dashboard/templates/overview.html:93`
- Modify: `book_scraper/dashboard/templates/run_detail.html:83`

- [ ] **Step 1: Update overview.html**

Open `book_scraper/dashboard/templates/overview.html`. Find line 93:

```html
<a href="/validation/{{ v.issue_type }}" class="validation-inline-item">
```

Replace with:

```html
<a href="/validation?issue_type={{ v.issue_type|urlencode }}" class="validation-inline-item">
```

- [ ] **Step 2: Update run_detail.html**

Open `book_scraper/dashboard/templates/run_detail.html`. Find line 83:

```html
<td><a href="/validation/{{ s.issue | urlencode }}?run_id={{ run.id }}">View all &rarr;</a></td>
```

Replace with:

```html
<td><a href="/validation?issue_type={{ s.issue | urlencode }}&run_id={{ run.id }}">View all &rarr;</a></td>
```

- [ ] **Step 3: Run smoke tests**

Run: `uv run pytest tests/integration/test_dashboard_routes.py -q`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/templates/overview.html book_scraper/dashboard/templates/run_detail.html
git commit -m "update legacy /validation/{type} links to filtered query"
```

---

## Task 10: Delete dead templates

**Files:**
- Delete: `book_scraper/dashboard/templates/validation_detail.html`
- Delete: `book_scraper/dashboard/templates/validation_rows.html`

- [ ] **Step 1: Confirm no references**

Run:

```bash
uv run grep -rn "validation_detail.html\|validation_rows.html" book_scraper tests
```

Expected: no output.

- [ ] **Step 2: Delete the files**

```bash
rm book_scraper/dashboard/templates/validation_detail.html
rm book_scraper/dashboard/templates/validation_rows.html
```

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 4: Lint and type-check**

Run:

```bash
uv run ruff check book_scraper/ tests/
uv run ruff format --check book_scraper/ tests/
```

Expected: both clean. If format fails, run `uv run ruff format book_scraper/ tests/` and re-commit.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "delete dead validation_detail and validation_rows templates"
```

---

## Task 11: Rebuild and deploy

**Files:** none (Docker)

- [ ] **Step 1: Rebuild scraper + dashboard**

Run:

```bash
docker compose build dashboard scraper
```

Expected: both images build cleanly.

- [ ] **Step 2: Restart containers**

Run:

```bash
docker compose up -d dashboard scraper
```

Expected: containers come up healthy.

- [ ] **Step 3: Post-deploy smoke test**

Run:

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all routes PASS.

- [ ] **Step 4: Manual verification**

Open `http://localhost:8000/validation` in a browser and confirm:
- Stat strip shows counts
- Lifecycle tabs switch state
- Shop / Issue / Run / Search filters work independently and together
- Sort toggles between newest and oldest first
- Pagination navigates
- Single-row `Ack` button works and the row disappears from Open
- `Acknowledge N matching` bulk button works (confirm dialog, then rows disappear)
- `Delete N matching` bulk button works (confirm dialog, then rows removed permanently)

- [ ] **Step 5: Trigger a short scan to confirm the scraper picked up the pipeline change**

Pick any existing product URL in the DB:

```bash
docker compose exec scraper uv run scrapy crawl scan -a shop=vaga -a max_urls=1
```

Expected: scan completes without errors, no `field_missing` entries appear in the resulting run on `/validation`.

- [ ] **Step 6: Final commit (if anything caught)**

If the rebuild or smoke test surfaced small fixes, commit them now. Otherwise the plan is complete.
