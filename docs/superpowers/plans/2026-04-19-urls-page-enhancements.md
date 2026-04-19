# URLs Page Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `url_classifications` table populated by the scan spider, use it to show a book score column (sortable, filterable) in the URLs list, replace the mixed status filter with a clean type filter, and add a `/urls/<id>` detail page showing metadata and score breakdown.

**Architecture:** A new `url_classifications` table holds one row per scanned URL (upserted by the scan spider unconditionally — for both book and non-book results). The dashboard list LEFT JOINs this table to show score; the detail page reads it directly. Classification data is queued alongside URL status updates and flushed through `ScanService`.

**Tech Stack:** SQLAlchemy 2.0, Alembic, FastAPI, Jinja2, PostgreSQL (JSONB, `ON CONFLICT DO UPDATE`)

---

## File Map

| File | Change |
|---|---|
| `book_scraper/db/models.py` | Add `UrlClassification` model |
| `alembic/versions/<rev>_add_url_classifications.py` | Migration: create table + indexes |
| `book_scraper/db/repo.py` | Add `upsert_url_classification()` |
| `book_scraper/spiders/scan.py` | Queue classification before early return + book path |
| `book_scraper/services/scan.py` | Flush classification updates in `flush_progress` + `finish_scan` |
| `book_scraper/dashboard/queries.py` | Update list query (type filter, score join, score filters, NULLS LAST); add `get_url_detail()` |
| `book_scraper/dashboard/routes/urls.py` | Update list route params; add `GET /urls/{url_id}` |
| `book_scraper/dashboard/templates/discovered_urls.html` | Type dropdown, score column, score filters, stat card links, list row links |
| `book_scraper/dashboard/templates/url_detail.html` | New detail page template |
| `tests/unit/test_url_classifications_repo.py` | Unit test: `upsert_url_classification` |
| `tests/integration/test_url_classifications.py` | Integration test: upsert + query |
| `tests/integration/test_dashboard_routes.py` | Add `/urls/<id>` smoke test |

---

## Task 1: `UrlClassification` Model

**Files:**
- Modify: `book_scraper/db/models.py`

- [ ] **Step 1: Add the model** — append after `DiscoveredUrl` (around line 360):

```python
from sqlalchemy.dialects.postgresql import JSONB  # add to existing imports at top

class UrlClassification(Base):
    __tablename__ = "url_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discovered_url_id: Mapped[int] = mapped_column(
        ForeignKey("discovered_urls.id"), nullable=False, unique=True
    )
    book_score: Mapped[int] = mapped_column(Integer, nullable=False)
    is_book_product: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    discovered_url: Mapped["DiscoveredUrl"] = relationship(
        back_populates="classification"
    )

    __table_args__ = (
        Index("ix_url_classifications_book_score", "book_score"),
        Index("ix_url_classifications_is_book_product", "is_book_product"),
    )
```

- [ ] **Step 2: Add back-reference on `DiscoveredUrl`** — in the `DiscoveredUrl` class, add after `last_seen_run`:

```python
classification: Mapped["UrlClassification | None"] = relationship(
    back_populates="discovered_url", uselist=False
)
```

- [ ] **Step 3: Verify mypy passes**

```bash
PYTHONPATH=. uv run mypy book_scraper/db/models.py
```
Expected: no errors

---

## Task 2: Alembic Migration

**Files:**
- Create: `alembic/versions/<rev>_add_url_classifications.py`

- [ ] **Step 1: Generate migration skeleton**

```bash
PYTHONPATH=. uv run alembic revision --autogenerate -m "add_url_classifications"
```

- [ ] **Step 2: Verify the generated migration** — open the new file in `alembic/versions/`. Confirm it contains `op.create_table("url_classifications", ...)` with all columns and the three indexes. If autogenerate missed anything, edit to match:

```python
def upgrade() -> None:
    op.create_table(
        "url_classifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("discovered_url_id", sa.Integer(), nullable=False),
        sa.Column("book_score", sa.Integer(), nullable=False),
        sa.Column("is_book_product", sa.Boolean(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["discovered_url_id"], ["discovered_urls.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("discovered_url_id"),
    )
    op.create_index("ix_url_classifications_book_score", "url_classifications", ["book_score"])
    op.create_index("ix_url_classifications_is_book_product", "url_classifications", ["is_book_product"])

def downgrade() -> None:
    op.drop_index("ix_url_classifications_is_book_product")
    op.drop_index("ix_url_classifications_book_score")
    op.drop_table("url_classifications")
```

- [ ] **Step 3: Run migration against test DB**

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/book_scraper_test PYTHONPATH=. uv run alembic upgrade head
```
Expected: `Running upgrade ... -> <rev>, add_url_classifications`

- [ ] **Step 4: Run migration against main DB**

```bash
PYTHONPATH=. uv run alembic upgrade head
```
Expected: same message

- [ ] **Step 5: Commit**

```bash
git add book_scraper/db/models.py alembic/versions/*add_url_classifications*.py
git commit -m "feat(db): add url_classifications model and migration"
```

---

## Task 3: `upsert_url_classification` Repo Function

**Files:**
- Modify: `book_scraper/db/repo.py`
- Create: `tests/unit/test_url_classifications_repo.py`

- [ ] **Step 1: Write the failing unit test**

```python
# tests/unit/test_url_classifications_repo.py
from unittest.mock import MagicMock, patch
from datetime import datetime, UTC

import pytest

from book_scraper.db.repo import upsert_url_classification
from book_scraper.db.models import UrlClassification


def _make_session():
    session = MagicMock()
    session.get.return_value = None
    return session


def test_upsert_creates_new_row():
    session = _make_session()
    session.execute.return_value.scalar_one_or_none.return_value = None
    upsert_url_classification(
        session,
        discovered_url_id=42,
        book_score=7,
        is_book_product=True,
        reasons=["+3 valid ISBN", "+2 author present"],
    )
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, UrlClassification)
    assert added.discovered_url_id == 42
    assert added.book_score == 7
    assert added.is_book_product is True
    assert added.reasons == ["+3 valid ISBN", "+2 author present"]
    session.flush.assert_called_once()


def test_upsert_updates_existing_row():
    existing = UrlClassification(
        discovered_url_id=42,
        book_score=3,
        is_book_product=True,
        reasons=["+3 valid ISBN"],
        classified_at=datetime.now(UTC),
    )
    session = _make_session()
    session.execute.return_value.scalar_one_or_none.return_value = existing

    upsert_url_classification(
        session,
        discovered_url_id=42,
        book_score=-2,
        is_book_product=False,
        reasons=["-4 non-book categories"],
    )
    assert existing.book_score == -2
    assert existing.is_book_product is False
    assert existing.reasons == ["-4 non-book categories"]
    session.flush.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_url_classifications_repo.py -v
```
Expected: `FAILED` — `upsert_url_classification` not defined

- [ ] **Step 3: Add `upsert_url_classification` to `repo.py`** — add after `update_discovered_url_status` (around line 533):

```python
def upsert_url_classification(
    session: Session,
    discovered_url_id: int,
    book_score: int,
    is_book_product: bool,
    reasons: list[str],
) -> None:
    """Upsert the book classification for a discovered URL.

    Called unconditionally after parse_product_page() — covers both book
    and non-book results so every scanned URL has a classification row.
    """
    stmt = select(UrlClassification).where(
        UrlClassification.discovered_url_id == discovered_url_id
    )
    existing = session.execute(stmt).scalar_one_or_none()
    now = datetime.now(UTC)
    if existing is not None:
        existing.book_score = book_score
        existing.is_book_product = is_book_product
        existing.reasons = reasons
        existing.classified_at = now
    else:
        record = UrlClassification(
            discovered_url_id=discovered_url_id,
            book_score=book_score,
            is_book_product=is_book_product,
            reasons=reasons,
            classified_at=now,
        )
        session.add(record)
    session.flush()
```

Also add `UrlClassification` to the imports at the top of `repo.py`:

```python
from book_scraper.db.models import (
    Category,
    CronJob,
    DiscoveredUrl,
    Price,
    ScrapeRun,
    ScrapeUrlItem,
    Shop,
    ShopAuthor,
    ShopBook,
    ShopBookAttribute,
    ShopBookAuthor,
    ShopBookFieldUpdate,
    UrlClassification,
    ValidationIssue,
)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_url_classifications_repo.py -v
```
Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add book_scraper/db/repo.py tests/unit/test_url_classifications_repo.py
git commit -m "feat(db): add upsert_url_classification repo function"
```

---

## Task 4: Scan Spider — Write Classification on Every Scraped Page

**Files:**
- Modify: `book_scraper/spiders/scan.py`
- Modify: `book_scraper/services/scan.py`

The spider queues URL status updates via `_queue_url_status_update`. We extend this to also carry classification data and flush it in `ScanService.flush_progress` / `finish_scan`.

- [ ] **Step 1: Extend `_queue_url_status_update` in `scan.py`** to accept optional classification kwargs (around line 375):

```python
def _queue_url_status_update(
    self,
    url_id: int | None,
    http_status: int | None = None,
    url_type: str | None = None,
    increment_fail: bool = False,
    scrape_url_item_id: int | None = None,
    success: bool = False,
    book_score: int | None = None,
    is_book_product: bool | None = None,
    book_score_reasons: list[str] | None = None,
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
    if book_score is not None and is_book_product is not None:
        update["book_score"] = book_score
        update["is_book_product"] = is_book_product
        update["book_score_reasons"] = book_score_reasons or []
    self._url_status_updates.append(update)
    self._urls_responded += 1
    if self._urls_responded % self._flush_every == 0:
        self._flush_progress()
```

- [ ] **Step 2: Pass classification data in the non-book early return** — in `parse` callback around line 262, change the `_queue_url_status_update` call to:

```python
if not data.get("is_book_product"):
    self._queue_url_status_update(
        discovered_url_id,
        http_status=200,
        url_type="non_product",
        scrape_url_item_id=scrape_url_item_id,
        success=False,
        book_score=data.get("book_score", 0),
        is_book_product=False,
        book_score_reasons=data.get("book_score_reasons", []),
    )
    return
```

- [ ] **Step 3: Pass classification data in the book success path** — find the `_queue_url_status_update` call at the end of the book processing path (around line 299) and add the classification kwargs:

```python
self._queue_url_status_update(
    discovered_url_id,
    http_status=200,
    url_type="product",
    scrape_url_item_id=scrape_url_item_id,
    success=True,
    book_score=data.get("book_score", 0),
    is_book_product=True,
    book_score_reasons=data.get("book_score_reasons", []),
)
```

- [ ] **Step 4: Update `ScanService.flush_progress` in `services/scan.py`** to extract and apply classification data:

```python
def flush_progress(
    self,
    run_id: int,
    urls_processed: int,
    url_status_updates: list[dict[str, Any]],
) -> None:
    """Flush queued URL status updates and progress to DB mid-run."""
    for update in url_status_updates:
        scrape_item_id = update.pop("scrape_url_item_id", None)
        scrape_item_success = update.pop("scrape_url_item_success", False)
        book_score = update.pop("book_score", None)
        is_book_product = update.pop("is_book_product", None)
        book_score_reasons = update.pop("book_score_reasons", None)
        update_discovered_url_status(self.session, **update)
        if (
            book_score is not None
            and is_book_product is not None
            and update.get("url_id") is not None
        ):
            upsert_url_classification(
                self.session,
                discovered_url_id=update["url_id"],
                book_score=book_score,
                is_book_product=is_book_product,
                reasons=book_score_reasons or [],
            )
        if scrape_item_id is not None:
            if scrape_item_success:
                mark_scrape_url_item_done(self.session, scrape_item_id)
            else:
                mark_scrape_url_item_failed(self.session, scrape_item_id)
    update_scrape_run_progress(self.session, run_id, urls_processed)
    self.session.commit()
```

- [ ] **Step 5: Apply the same extraction to `finish_scan`** — same pattern as `flush_progress`, both `for` loops need the classification extraction block above.

- [ ] **Step 6: Add `upsert_url_classification` to imports in `services/scan.py`**:

```python
from book_scraper.db.repo import (
    ...,
    upsert_url_classification,
)
```

- [ ] **Step 7: Run unit tests to catch regressions**

```bash
uv run pytest tests/unit/test_spiders.py -v
```
Expected: all pass

- [ ] **Step 8: Run all unit tests**

```bash
uv run pytest tests/unit/ -v
```
Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add book_scraper/spiders/scan.py book_scraper/services/scan.py
git commit -m "feat(scan): write url_classifications on every scanned page"
```

---

## Task 5: Integration Test — Classification Write Path

**Files:**
- Create: `tests/integration/test_url_classifications.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_url_classifications.py
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from book_scraper.db.models import DiscoveredUrl, Shop, UrlClassification
from book_scraper.db.repo import upsert_discovered_url, upsert_url_classification


@pytest.fixture()
def shop(db_session: Session) -> Shop:
    from book_scraper.db.repo import upsert_shop
    return upsert_shop(db_session, "test_shop", "https://example.com")


@pytest.fixture()
def discovered_url(db_session: Session, shop: Shop) -> DiscoveredUrl:
    url = upsert_discovered_url(db_session, shop.id, "https://example.com/p/1", "sitemap")
    db_session.commit()
    return url


def test_upsert_creates_classification(db_session: Session, discovered_url: DiscoveredUrl):
    upsert_url_classification(
        db_session,
        discovered_url_id=discovered_url.id,
        book_score=7,
        is_book_product=True,
        reasons=["+3 valid ISBN", "+2 author present"],
    )
    db_session.commit()

    row = db_session.query(UrlClassification).filter_by(
        discovered_url_id=discovered_url.id
    ).one()
    assert row.book_score == 7
    assert row.is_book_product is True
    assert row.reasons == ["+3 valid ISBN", "+2 author present"]


def test_upsert_overwrites_on_rescan(db_session: Session, discovered_url: DiscoveredUrl):
    upsert_url_classification(db_session, discovered_url.id, 7, True, ["+3 valid ISBN"])
    db_session.commit()

    upsert_url_classification(db_session, discovered_url.id, -2, False, ["-4 non-book categories"])
    db_session.commit()

    rows = db_session.query(UrlClassification).filter_by(discovered_url_id=discovered_url.id).all()
    assert len(rows) == 1
    assert rows[0].book_score == -2
    assert rows[0].is_book_product is False


def test_relationship_accessible(db_session: Session, discovered_url: DiscoveredUrl):
    upsert_url_classification(db_session, discovered_url.id, 5, True, ["+3 valid ISBN"])
    db_session.commit()
    db_session.refresh(discovered_url)
    assert discovered_url.classification is not None
    assert discovered_url.classification.book_score == 5
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/integration/test_url_classifications.py -v
```
Expected: `FAILED` (table doesn't exist yet in test DB — or if migration already ran, passes immediately)

- [ ] **Step 3: Ensure test DB migration is up to date**

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/book_scraper_test PYTHONPATH=. uv run alembic upgrade head
```

- [ ] **Step 4: Run integration tests again**

```bash
uv run pytest tests/integration/test_url_classifications.py -v
```
Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_url_classifications.py
git commit -m "test(integration): url_classifications upsert and relationship"
```

---

## Task 6: Dashboard Queries — Type Filter, Score Column, Detail Query

**Files:**
- Modify: `book_scraper/dashboard/queries.py`

- [ ] **Step 1: Import `UrlClassification`** at the top of `queries.py` alongside other model imports:

```python
from book_scraper.db.models import (
    ...,
    UrlClassification,
)
```

- [ ] **Step 2: Update `DISCOVERED_URL_SORT_COLUMNS`** (around line 1140):

```python
DISCOVERED_URL_SORT_COLUMNS = {
    "url": DiscoveredUrl.url,
    "fails": DiscoveredUrl.fail_count,
    "discovered": DiscoveredUrl.first_seen_at,
    "score": UrlClassification.book_score,
}
```

- [ ] **Step 3: Replace `get_discovered_urls_page`** — full replacement with the new signature and logic:

```python
def get_discovered_urls_page(
    session: Session,
    page: int = 1,
    per_page: int = 50,
    shop_id: int | None = None,
    source: str = "",
    url_type: str = "",
    search: str = "",
    score_min: int | None = None,
    is_book: str = "",
    sort_by: str = "discovered",
    sort_order: str = "desc",
) -> tuple[list, int]:
    """Return paginated discovered URLs with filters."""
    query = (
        session.query(DiscoveredUrl)
        .options(joinedload(DiscoveredUrl.shop))
        .outerjoin(UrlClassification, UrlClassification.discovered_url_id == DiscoveredUrl.id)
    )
    if shop_id:
        query = query.filter(DiscoveredUrl.shop_id == shop_id)
    if source:
        query = query.filter(DiscoveredUrl.source == source)
    if url_type:
        query = query.filter(DiscoveredUrl.url_type == url_type)
    if search:
        query = query.filter(DiscoveredUrl.url.ilike(f"%{search}%"))
    if score_min is not None:
        query = query.filter(UrlClassification.book_score >= score_min)
    if is_book == "book":
        query = query.filter(UrlClassification.is_book_product.is_(True))
    elif is_book == "not_book":
        query = query.filter(UrlClassification.is_book_product.is_(False))
    total = query.count()
    order_col = DISCOVERED_URL_SORT_COLUMNS.get(sort_by, DiscoveredUrl.first_seen_at)
    if sort_order == "asc":
        query = query.order_by(order_col.asc().nulls_last())
    else:
        query = query.order_by(order_col.desc().nulls_last())
    urls = query.offset((page - 1) * per_page).limit(per_page).all()
    return urls, total
```

- [ ] **Step 4: Add `get_url_detail` query function** — append at the end of `queries.py`:

```python
def get_url_detail(
    session: Session, url_id: int
) -> tuple[DiscoveredUrl, UrlClassification | None] | None:
    """Fetch a DiscoveredUrl with its shop, shop_book, and classification.

    Returns None if not found.
    """
    from sqlalchemy import select as _select

    stmt = (
        _select(DiscoveredUrl)
        .options(
            joinedload(DiscoveredUrl.shop),
            joinedload(DiscoveredUrl.shop_book),
            joinedload(DiscoveredUrl.classification),
        )
        .where(DiscoveredUrl.id == url_id)
    )
    url = session.execute(stmt).unique().scalar_one_or_none()
    if url is None:
        return None
    return url, url.classification
```

- [ ] **Step 5: Run mypy**

```bash
PYTHONPATH=. uv run mypy book_scraper/dashboard/queries.py
```
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add book_scraper/dashboard/queries.py
git commit -m "feat(dashboard): update URLs query — type filter, score join, detail query"
```

---

## Task 7: Dashboard Routes — Update List Route, Add Detail Route

**Files:**
- Modify: `book_scraper/dashboard/routes/urls.py`

- [ ] **Step 1: Replace the file** with the updated list route and new detail route:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_all_shops,
    get_discovered_urls_page,
    get_discovered_urls_stats,
    get_shop_by_name,
    get_url_detail,
)

router = APIRouter()


@router.get("/urls")
def discovered_urls_page(
    request: Request,
    page: int = 1,
    q: str = "",
    shop: str = "",
    source: str = "",
    url_type: str = "",
    score_min: str = "",
    is_book: str = "",
    sort: str = "discovered",
    order: str = "desc",
    session: Session = Depends(get_db),
):
    shop_obj = get_shop_by_name(session, shop) if shop else None
    shop_id = shop_obj.id if shop_obj else None
    stats = get_discovered_urls_stats(session, shop_id=shop_id)
    score_min_int: int | None = None
    if score_min.strip().lstrip("-").isdigit():
        score_min_int = int(score_min)
    urls, total = get_discovered_urls_page(
        session,
        page=page,
        shop_id=shop_id,
        source=source,
        url_type=url_type,
        search=q,
        score_min=score_min_int,
        is_book=is_book,
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
            "type_filter": url_type,
            "score_min_filter": score_min,
            "is_book_filter": is_book,
            "sort": sort,
            "order": order,
            "shops": shops,
        },
    )


@router.get("/urls/{url_id}")
def url_detail_page(
    request: Request,
    url_id: int,
    session: Session = Depends(get_db),
):
    result = get_url_detail(session, url_id)
    if result is None:
        raise HTTPException(status_code=404, detail="URL not found")
    discovered_url, classification = result
    return templates.TemplateResponse(
        request,
        "url_detail.html",
        {
            "active_page": "urls",
            "url": discovered_url,
            "classification": classification,
        },
    )
```

- [ ] **Step 2: Run mypy**

```bash
PYTHONPATH=. uv run mypy book_scraper/dashboard/routes/urls.py
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/routes/urls.py
git commit -m "feat(dashboard): update URLs list route, add /urls/<id> detail route"
```

---

## Task 8: Update `discovered_urls.html` Template

**Files:**
- Modify: `book_scraper/dashboard/templates/discovered_urls.html`

- [ ] **Step 1: Replace stat card links** — "Not in Shop Books", "Failed 3+", and "In Shop Books" cards become display-only `<div>` instead of `<a>`. Update lines 8–26:

```html
<div class="stat-grid">
    <a href="/urls?{% if shop_filter %}shop={{ shop_filter|urlencode }}&{% endif %}" class="stat-card">
        <div class="stat-label">Total URLs</div>
        <div class="stat-value">{{ "{:,}".format(stats.total) }}</div>
    </a>
    <div class="stat-card">
        <div class="stat-label">In Shop Books</div>
        <div class="stat-value">{{ "{:,}".format(stats.in_shop_books) }}</div>
        <div class="stat-sub">{{ "%.1f"|format(stats.in_shop_books / stats.total * 100) if stats.total else 0 }}%</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Not in Shop Books</div>
        <div class="stat-value" style="color: var(--badge-warning-fg);">{{ "{:,}".format(stats.not_in_shop_books) }}</div>
        <div class="stat-sub">{{ "%.1f"|format(stats.not_in_shop_books / stats.total * 100) if stats.total else 0 }}%</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Failed 3+</div>
        <div class="stat-value" style="color: var(--badge-error-fg);">{{ "{:,}".format(stats.failed) }}</div>
    </div>
</div>
```

- [ ] **Step 2: Replace filter form** — replace lines 28–53 with:

```html
<form method="get" action="/urls">
    <div class="filter-bar">
        <select name="shop">
            <option value="">All shops</option>
            {% for s in shops %}
            <option value="{{ s.name }}" {{ 'selected' if shop_filter == s.name else '' }}>{{ s.name }}</option>
            {% endfor %}
        </select>
        <select name="source">
            <option value="">All sources</option>
            <option value="sitemap" {{ 'selected' if source_filter == 'sitemap' else '' }}>sitemap</option>
            <option value="category" {{ 'selected' if source_filter == 'category' else '' }}>category</option>
            <option value="full_crawl" {{ 'selected' if source_filter == 'full_crawl' else '' }}>full_crawl</option>
        </select>
        <select name="url_type">
            <option value="">All types</option>
            <option value="unknown" {{ 'selected' if type_filter == 'unknown' else '' }}>unknown</option>
            <option value="product" {{ 'selected' if type_filter == 'product' else '' }}>product</option>
            <option value="non_product" {{ 'selected' if type_filter == 'non_product' else '' }}>non_product</option>
        </select>
        <select name="is_book">
            <option value="">All scores</option>
            <option value="book" {{ 'selected' if is_book_filter == 'book' else '' }}>book</option>
            <option value="not_book" {{ 'selected' if is_book_filter == 'not_book' else '' }}>not book</option>
        </select>
        <input type="number" name="score_min" placeholder="Score ≥" value="{{ score_min_filter }}" style="width:7rem;">
        <input type="search" name="q" placeholder="Search URL..." value="{{ query }}">
        <button type="submit">Filter</button>
    </div>
</form>
```

- [ ] **Step 3: Update `filter_params` and filter badges** — replace line 55 and the badges block (lines 55–72):

```html
{% set filter_params = "q=" ~ query|urlencode ~ "&shop=" ~ shop_filter|urlencode ~ "&source=" ~ source_filter|urlencode ~ "&url_type=" ~ type_filter|urlencode ~ "&score_min=" ~ score_min_filter|urlencode ~ "&is_book=" ~ is_book_filter|urlencode %}

{% if shop_filter or source_filter or type_filter or query or score_min_filter or is_book_filter %}
<div style="margin-bottom: 1rem; display: flex; flex-wrap: wrap; gap: 0.5rem;">
    {% if shop_filter %}
    <span class="filter-badge">Shop: {{ shop_filter }} <a href="/urls?{{ filter_params|replace('shop=' ~ shop_filter|urlencode, 'shop=') }}">✕</a></span>
    {% endif %}
    {% if source_filter %}
    <span class="filter-badge">Source: {{ source_filter }} <a href="/urls?{{ filter_params|replace('&source=' ~ source_filter|urlencode, '') }}">✕</a></span>
    {% endif %}
    {% if type_filter %}
    <span class="filter-badge">Type: {{ type_filter }} <a href="/urls?{{ filter_params|replace('&url_type=' ~ type_filter|urlencode, '') }}">✕</a></span>
    {% endif %}
    {% if is_book_filter %}
    <span class="filter-badge">Book: {{ is_book_filter }} <a href="/urls?{{ filter_params|replace('&is_book=' ~ is_book_filter|urlencode, '') }}">✕</a></span>
    {% endif %}
    {% if score_min_filter %}
    <span class="filter-badge">Score ≥ {{ score_min_filter }} <a href="/urls?{{ filter_params|replace('&score_min=' ~ score_min_filter|urlencode, '') }}">✕</a></span>
    {% endif %}
    {% if query %}
    <span class="filter-badge">Search: {{ query }} <a href="/urls?{{ filter_params|replace('q=' ~ query|urlencode, 'q=') }}">✕</a></span>
    {% endif %}
</div>
{% endif %}
```

- [ ] **Step 4: Add Score column header** — update the `<thead>` row (around line 82):

```html
<tr>
    <th>{{ sort_header('url', 'URL', sort, order, filter_params) }}</th>
    <th>Shop</th>
    <th>Shop Book</th>
    <th>Source</th>
    <th>Type</th>
    <th>{{ sort_header('score', 'Score', sort, order, filter_params) }}</th>
    <th class="text-right">{{ sort_header('fails', 'Fails', sort, order, filter_params) }}</th>
    <th class="text-right">HTTP</th>
    <th>{{ sort_header('discovered', 'Discovered', sort, order, filter_params) }}</th>
</tr>
```

- [ ] **Step 5: Update URL cell to link to detail page** and add Score cell — update the `<tbody>` row (starting around line 94):

```html
{% for u in urls %}
<tr>
    <td class="cell-truncate">
        <a href="/urls/{{ u.id }}">{{ u.url }}</a>
        <a href="{{ u.url }}" target="_blank" rel="noopener noreferrer" style="margin-left:0.3rem; color:var(--text-muted); font-size:0.8rem;">↗</a>
    </td>
    <td class="text-muted">{{ u.shop.name if u.shop else '—' }}</td>
    <td>
        {% if u.shop_book_id %}
        <a href="/shop-books/{{ u.shop_book_id }}">#{{ u.shop_book_id }}</a>
        {% else %}
        <span class="text-muted">—</span>
        {% endif %}
    </td>
    <td class="text-muted">{{ u.source or '—' }}</td>
    <td>
        {% if u.url_type == 'product' %}
        <span class="badge badge-completed">product</span>
        {% elif u.url_type == 'non_product' %}
        <span class="badge badge-neutral">non_product</span>
        {% else %}
        <span class="badge badge-warning">unknown</span>
        {% endif %}
    </td>
    <td>
        {% if u.classification %}
            {% if u.classification.is_book_product %}
            <span class="badge badge-completed">book</span>
            {% else %}
            <span class="badge badge-warning">not book</span>
            {% endif %}
            <strong>{{ u.classification.book_score }}</strong>
        {% else %}
        <span class="text-muted">—</span>
        {% endif %}
    </td>
    <td class="text-right">
        {% if u.fail_count %}
        <span class="{{ 'http-error' if u.fail_count >= 3 else '' }}">{{ u.fail_count }}</span>
        {% else %}
        <span class="text-muted">0</span>
        {% endif %}
    </td>
    <td class="text-right">
        {% if u.last_http_status %}
        <span class="{{ 'http-error' if u.last_http_status >= 400 else 'text-muted' }}">{{ u.last_http_status }}</span>
        {% else %}
        <span class="text-muted">—</span>
        {% endif %}
    </td>
    <td class="text-muted">
        {% if u.first_seen_at %}
        {{ u.first_seen_at.strftime('%b %-d') }}
        {% else %}—{% endif %}
    </td>
</tr>
{% endfor %}
```

- [ ] **Step 6: Update pagination links** — ensure they use `url_type` instead of `status`:

The pagination `<a>` links already use `{{ filter_params }}` which now includes `url_type`. No change needed as long as `filter_params` is correct.

- [ ] **Step 7: Commit**

```bash
git add book_scraper/dashboard/templates/discovered_urls.html
git commit -m "feat(dashboard): type filter, score column, updated stat cards and links"
```

---

## Task 9: URL Detail Page Template

**Files:**
- Create: `book_scraper/dashboard/templates/url_detail.html`

- [ ] **Step 1: Create the template**

```html
{% extends "base.html" %}
{% block title %}URL #{{ url.id }}{% endblock %}
{% block content %}
<div style="display:flex; align-items:center; gap:1rem; margin-bottom:1.5rem;">
    <a href="/urls" class="text-muted" style="font-size:0.85rem;">← Discovered URLs</a>
    <h1 class="page-title" style="margin:0;">URL #{{ url.id }}</h1>
</div>

<div class="card" style="margin-bottom:1.5rem;">
    <h3 style="margin-top:0;">URL</h3>
    <p style="font-family:monospace; word-break:break-all; margin-bottom:0.75rem;">
        {{ url.url }}
        <a href="{{ url.url }}" target="_blank" rel="noopener noreferrer" style="margin-left:0.5rem; font-size:0.85rem;">↗ open</a>
    </p>
    <div style="display:flex; gap:0.75rem; flex-wrap:wrap; margin-bottom:1rem;">
        {% if url.url_type == 'product' %}
        <span class="badge badge-completed">product</span>
        {% elif url.url_type == 'non_product' %}
        <span class="badge badge-neutral">non_product</span>
        {% else %}
        <span class="badge badge-warning">unknown</span>
        {% endif %}
        <span class="badge badge-neutral">{{ url.source or '—' }}</span>
    </div>
    <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap:0.5rem 1.5rem;">
        <div><span class="text-muted" style="font-size:0.8rem;">Discovered</span><br>
            {{ url.first_seen_at.strftime('%Y-%m-%d') if url.first_seen_at else '—' }}</div>
        <div><span class="text-muted" style="font-size:0.8rem;">Last checked</span><br>
            {{ url.last_checked_at.strftime('%Y-%m-%d') if url.last_checked_at else '—' }}</div>
        <div><span class="text-muted" style="font-size:0.8rem;">HTTP status</span><br>
            {% if url.last_http_status %}
            <span class="{{ 'http-error' if url.last_http_status >= 400 else '' }}">{{ url.last_http_status }}</span>
            {% else %}—{% endif %}</div>
        <div><span class="text-muted" style="font-size:0.8rem;">Fail count</span><br>
            <span class="{{ 'http-error' if url.fail_count >= 3 else '' }}">{{ url.fail_count }}</span></div>
    </div>
</div>

{% if url.shop_book %}
<div class="card" style="margin-bottom:1.5rem;">
    <h3 style="margin-top:0;">Linked Shop Book</h3>
    <div style="display:grid; grid-template-columns: max-content 1fr; gap:0.3rem 1.5rem; margin-bottom:0.75rem;">
        <span class="text-muted">Title</span><span>{{ url.shop_book.title or '—' }}</span>
        <span class="text-muted">Author</span><span>{{ url.shop_book.author or '—' }}</span>
        <span class="text-muted">Type</span>
        <span><span class="badge badge-neutral">{{ url.shop_book.type or '—' }}</span></span>
        <span class="text-muted">Active</span><span>{{ 'Yes' if url.shop_book.is_active else 'No' }}</span>
        <span class="text-muted">Price</span><span>{{ url.shop_book.price ~ ' €' if url.shop_book.price else '—' }}</span>
    </div>
    <a href="/shop-books/{{ url.shop_book.id }}" style="font-size:0.85rem;">→ Open shop book #{{ url.shop_book.id }}</a>
</div>
{% endif %}

<div class="card">
    <h3 style="margin-top:0;">Book Score</h3>
    {% if classification %}
    <div style="display:flex; align-items:center; gap:1rem; margin-bottom:1rem;">
        <span style="font-size:2rem; font-weight:700; color:{{ 'var(--badge-success-fg)' if classification.is_book_product else 'var(--badge-warning-fg)' }};">
            {{ classification.book_score }}
        </span>
        {% if classification.is_book_product %}
        <span class="badge badge-completed">✓ Classified as book</span>
        {% else %}
        <span class="badge badge-warning">✗ Not a book</span>
        {% endif %}
    </div>
    {% if classification.reasons %}
    <ul style="list-style:none; padding:0; margin:0;">
        {% for reason in classification.reasons %}
        <li style="padding:0.2rem 0; font-size:0.9rem;
            color:{{ 'var(--badge-success-fg)' if reason.startswith('+') else ('var(--badge-error-fg)' if reason.startswith('-') else 'inherit') }};">
            {{ reason }}
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <p class="text-muted">No reasons recorded.</p>
    {% endif %}
    <p class="text-muted" style="font-size:0.8rem; margin-top:0.75rem;">
        Classified {{ classification.classified_at.strftime('%Y-%m-%d %H:%M') if classification.classified_at else '' }}
    </p>
    {% else %}
    <p class="text-muted">Not yet classified — this URL has not been scanned.</p>
    {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add book_scraper/dashboard/templates/url_detail.html
git commit -m "feat(dashboard): add url_detail.html template"
```

---

## Task 10: Smoke Tests + Deploy

**Files:**
- Modify: `tests/integration/test_dashboard_routes.py`

- [ ] **Step 1: Add a smoke test for `/urls/<id>`** — open the file and add:

```python
def test_url_detail_page_404(client):
    """Non-existent URL ID returns 404."""
    response = client.get("/urls/999999")
    assert response.status_code == 404


def test_url_detail_page_exists(client, db_session):
    """An existing DiscoveredUrl returns 200 on its detail page."""
    from book_scraper.db.repo import upsert_discovered_url, upsert_shop
    shop = upsert_shop(db_session, "smoke_shop", "https://smoke.example.com")
    url = upsert_discovered_url(db_session, shop.id, "https://smoke.example.com/p/1", "sitemap")
    db_session.commit()

    response = client.get(f"/urls/{url.id}")
    assert response.status_code == 200
    assert "Not yet classified" in response.text
```

- [ ] **Step 2: Run the smoke tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```
Expected: all pass (including the two new tests)

- [ ] **Step 3: Rebuild and restart dashboard container**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

- [ ] **Step 4: Run smoke tests against running container**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_dashboard_routes.py
git commit -m "test(integration): smoke tests for url_detail route"
```

---

## Task 11: Final Checks

- [ ] **Run full test suite**

```bash
uv run pytest -v
```
Expected: all pass

- [ ] **Run linter and formatter**

```bash
uv run ruff check book_scraper/ tests/
uv run ruff format book_scraper/ tests/
```

- [ ] **Run mypy**

```bash
PYTHONPATH=. uv run mypy book_scraper/
```
Expected: no errors

- [ ] **Verify in browser** — open `http://localhost:8000/urls` and confirm:
  - Type dropdown works (unknown/product/non_product)
  - Score column shows `—` for unclassified, badge+number for classified
  - Score ≥ filter and Book filter work
  - Score column is sortable
  - Clicking a URL opens `/urls/<id>` detail page
  - Stat cards are display-only (no link on "Not in Shop Books", "Failed 3+", "In Shop Books")

- [ ] **Final commit** (if any formatting changes)

```bash
git add -u
git commit -m "style: ruff format after URLs enhancements"
```
