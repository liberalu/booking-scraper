# Fault Tolerance & Resumable Scraping — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scraping resumable after crashes, track discovered URLs in PostgreSQL, and refactor spiders into generic per-phase classes.

**Architecture:** Two new DB tables (`discovered_urls`, `scrape_runs`), two generic spiders (`discover`, `scan`), dynamic parser loading by shop name. Category discovery extracts prices, eliminating the separate prices spider.

**Tech Stack:** SQLAlchemy 2.0, Alembic, Scrapy, PostgreSQL, TOML config, Python 3.12+

**Spec:** `docs/superpowers/specs/2026-04-06-fault-tolerance-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `book_scraper/db/models.py` (modify) | Add `DiscoveredUrl` and `ScrapeRun` models + enums |
| Create | `alembic/versions/XXXX_add_discovered_urls_and_scrape_runs.py` | Migration for new tables |
| Modify | `book_scraper/db/repo.py` | Add repo functions for discovered URLs and scrape runs |
| Modify | `book_scraper/items.py` | Add `source` field to `DiscoveredUrlItem` |
| Modify | `book_scraper/config.py` | Support new TOML structure with discover strategies |
| Modify | `config/shops/vaga.toml` | Restructure to new format |
| Create | `book_scraper/spiders/registry.py` | `load_parsers()` dynamic parser loader |
| Create | `book_scraper/spiders/discover.py` | Generic discover spider (sitemap + categories + full_crawl) |
| Create | `book_scraper/spiders/scan.py` | Generic scan spider (reads from discovered_urls, resumable) |
| Modify | `book_scraper/pipelines.py` | Handle `DiscoveredUrlItem` persistence, scrape_runs progress |
| Delete | `book_scraper/spiders/vaga/discover.py` | Replaced by generic discover |
| Delete | `book_scraper/spiders/vaga/scan.py` | Replaced by generic scan |
| Delete | `book_scraper/spiders/vaga/prices.py` | Eliminated (category discovery handles prices) |
| Create | `tests/test_discovered_urls_repo.py` | Tests for discovered URL repo functions |
| Create | `tests/test_scrape_runs_repo.py` | Tests for scrape run repo functions |
| Create | `tests/test_registry.py` | Tests for parser registry |
| Create | `tests/test_config_strategies.py` | Tests for new config structure |

---

### Task 1: Add `DiscoveredUrl` and `ScrapeRun` models

**Files:**
- Modify: `book_scraper/db/models.py`

- [ ] **Step 1: Add enums and `DiscoveredUrl` model after the existing `Price` class**

Add these imports at the top of `book_scraper/db/models.py` (the file already imports `Enum as PgEnum` — reuse it):

```python
# Add to existing imports at top of file
from sqlalchemy import Index

# Add after line ~54 (after match_method_enum)
discovery_source_enum = PgEnum(
    "sitemap", "category", "full_crawl",
    name="discovery_source",
    create_type=False,
)

url_type_enum = PgEnum(
    "unknown", "product", "non_product",
    name="url_type",
    create_type=False,
)

scrape_phase_enum = PgEnum(
    "discover_sitemap", "discover_categories", "discover_full_crawl", "scan",
    name="scrape_phase",
    create_type=False,
)

scrape_status_enum = PgEnum(
    "running", "completed", "failed",
    name="scrape_status",
    create_type=False,
)
```

Then add the two model classes after the `Price` class:

```python
class DiscoveredUrl(Base):
    __tablename__ = "discovered_urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(discovery_source_enum, nullable=False)
    url_type: Mapped[str] = mapped_column(
        url_type_enum, nullable=False, server_default="unknown"
    )
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    shop: Mapped["Shop"] = relationship()

    __table_args__ = (
        UniqueConstraint("shop_id", "url", name="uq_discovered_urls_shop_url"),
        Index("ix_discovered_urls_shop_type_fail", "shop_id", "url_type", "fail_count"),
    )


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    phase: Mapped[str] = mapped_column(scrape_phase_enum, nullable=False)
    status: Mapped[str] = mapped_column(scrape_status_enum, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    urls_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urls_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    shop: Mapped["Shop"] = relationship()
```

Also add `UniqueConstraint` and `Index` to the existing imports from `sqlalchemy`:

```python
from sqlalchemy import UniqueConstraint, Index
```

- [ ] **Step 2: Add missing imports**

Ensure `UTC` is imported:
```python
from datetime import UTC, datetime
```

And `Text` is in the sqlalchemy imports (it's already used for Listing, so it should be there).

- [ ] **Step 3: Run mypy to verify**

Run: `uv run mypy book_scraper/db/models.py`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 4: Commit**

```bash
git add book_scraper/db/models.py
git commit -m "feat: add DiscoveredUrl and ScrapeRun models"
```

---

### Task 2: Alembic migration for new tables

**Files:**
- Create: `alembic/versions/XXXX_add_discovered_urls_and_scrape_runs.py`

- [ ] **Step 1: Generate migration**

Run: `PYTHONPATH=. uv run alembic revision --autogenerate -m "add discovered_urls and scrape_runs tables"`

- [ ] **Step 2: Review the generated migration**

Open the generated file in `alembic/versions/`. Verify it creates:
- Enum types: `discovery_source`, `url_type`, `scrape_phase`, `scrape_status`
- Table `discovered_urls` with all columns, unique constraint, and index
- Table `scrape_runs` with all columns

If autogenerate missed the enum creation, add manually in `upgrade()`:

```python
discovery_source = sa.Enum("sitemap", "category", "full_crawl", name="discovery_source")
discovery_source.create(op.get_bind())

url_type = sa.Enum("unknown", "product", "non_product", name="url_type")
url_type.create(op.get_bind())

scrape_phase = sa.Enum(
    "discover_sitemap", "discover_categories", "discover_full_crawl", "scan",
    name="scrape_phase",
)
scrape_phase.create(op.get_bind())

scrape_status = sa.Enum("running", "completed", "failed", name="scrape_status")
scrape_status.create(op.get_bind())
```

And in `downgrade()`:
```python
sa.Enum(name="discovery_source").drop(op.get_bind())
sa.Enum(name="url_type").drop(op.get_bind())
sa.Enum(name="scrape_phase").drop(op.get_bind())
sa.Enum(name="scrape_status").drop(op.get_bind())
```

- [ ] **Step 3: Run migration on main DB**

Run: `PYTHONPATH=. uv run alembic upgrade head`
Expected: Migration applies successfully

- [ ] **Step 4: Run migration on test DB**

Run: `DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test PYTHONPATH=. uv run alembic upgrade head`

If test DB uses a different env var, check `alembic/env.py` for how it reads the URL. The test conftest creates tables via `Base.metadata.create_all(engine)` so the migration may not be needed for tests, but verify.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat: migration for discovered_urls and scrape_runs tables"
```

---

### Task 3: Repo functions for `discovered_urls`

**Files:**
- Modify: `book_scraper/db/repo.py`
- Create: `tests/test_discovered_urls_repo.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_discovered_urls_repo.py`:

```python
from datetime import UTC, datetime, timedelta

from book_scraper.db.models import DiscoveredUrl, Shop
from book_scraper.db.repo import (
    get_pending_scan_urls,
    upsert_discovered_url,
    update_discovered_url_status,
)


def test_upsert_discovered_url_creates_new(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    result = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="sitemap"
    )
    assert result.url == "https://test.lt/book-1"
    assert result.source == "sitemap"
    assert result.url_type == "unknown"
    assert result.fail_count == 0


def test_upsert_discovered_url_ignores_duplicate(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    first = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="sitemap"
    )
    second = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="category"
    )
    assert first.id == second.id
    # Source should NOT be updated (keep original)
    assert second.source == "sitemap"


def test_update_discovered_url_status_success(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    url_record = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="sitemap"
    )
    update_discovered_url_status(
        db_session, url_id=url_record.id, http_status=200, url_type="product"
    )
    db_session.refresh(url_record)
    assert url_record.last_http_status == 200
    assert url_record.url_type == "product"
    assert url_record.fail_count == 0
    assert url_record.last_checked_at is not None


def test_update_discovered_url_status_failure(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    url_record = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="sitemap"
    )
    update_discovered_url_status(
        db_session, url_id=url_record.id, http_status=404, increment_fail=True
    )
    db_session.refresh(url_record)
    assert url_record.last_http_status == 404
    assert url_record.fail_count == 1


def test_get_pending_scan_urls_filters_non_product(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="sitemap"
    )
    non_product = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/about", source="sitemap"
    )
    update_discovered_url_status(
        db_session, url_id=non_product.id, http_status=200, url_type="non_product"
    )

    pending = get_pending_scan_urls(db_session, shop_id=shop.id)
    urls = [u.url for u in pending]
    assert "https://test.lt/book-1" in urls
    assert "https://test.lt/about" not in urls


def test_get_pending_scan_urls_filters_high_fail_count(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    url_record = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/dead", source="sitemap"
    )
    # Simulate 3 failures with recent last_checked_at
    for _ in range(3):
        update_discovered_url_status(
            db_session, url_id=url_record.id, http_status=404, increment_fail=True
        )

    pending = get_pending_scan_urls(db_session, shop_id=shop.id)
    urls = [u.url for u in pending]
    assert "https://test.lt/dead" not in urls
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_discovered_urls_repo.py -v`
Expected: ImportError — functions don't exist yet

- [ ] **Step 3: Implement repo functions**

Add to `book_scraper/db/repo.py`:

```python
from datetime import UTC, datetime, timedelta

from book_scraper.db.models import DiscoveredUrl


def upsert_discovered_url(
    session: Session,
    shop_id: int,
    url: str,
    source: str,
) -> DiscoveredUrl:
    """Insert a discovered URL or return existing. Source is not updated on conflict."""
    existing = session.query(DiscoveredUrl).filter_by(shop_id=shop_id, url=url).first()
    if existing:
        return existing
    record = DiscoveredUrl(
        shop_id=shop_id,
        url=url,
        source=source,
    )
    session.add(record)
    session.flush()
    return record


def update_discovered_url_status(
    session: Session,
    url_id: int,
    http_status: int | None = None,
    url_type: str | None = None,
    increment_fail: bool = False,
) -> None:
    """Update status fields on a discovered URL after a scan attempt."""
    record = session.get(DiscoveredUrl, url_id)
    if record is None:
        return
    now = datetime.now(UTC)
    record.last_checked_at = now
    if http_status is not None:
        record.last_http_status = http_status
    if url_type is not None:
        record.url_type = url_type
    if increment_fail:
        record.fail_count += 1
    else:
        record.fail_count = 0


def get_pending_scan_urls(
    session: Session,
    shop_id: int,
    max_fail_count: int = 3,
    retry_after_days: int = 7,
) -> list[DiscoveredUrl]:
    """Get URLs that need scanning: not non_product, and either low fail count
    or enough time has passed to retry."""
    cutoff = datetime.now(UTC) - timedelta(days=retry_after_days)
    return (
        session.query(DiscoveredUrl)
        .filter(
            DiscoveredUrl.shop_id == shop_id,
            DiscoveredUrl.url_type != "non_product",
            (
                (DiscoveredUrl.fail_count < max_fail_count)
                | (DiscoveredUrl.last_checked_at < cutoff)
                | (DiscoveredUrl.last_checked_at.is_(None))
            ),
        )
        .all()
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_discovered_urls_repo.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add book_scraper/db/repo.py tests/test_discovered_urls_repo.py
git commit -m "feat: repo functions for discovered_urls table"
```

---

### Task 4: Repo functions for `scrape_runs`

**Files:**
- Modify: `book_scraper/db/repo.py`
- Create: `tests/test_scrape_runs_repo.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_scrape_runs_repo.py`:

```python
from book_scraper.db.models import Shop, ScrapeRun
from book_scraper.db.repo import (
    create_scrape_run,
    finish_scrape_run,
    get_latest_completed_run,
    mark_stale_runs_failed,
    update_scrape_run_progress,
)


def test_create_scrape_run(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    run = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    assert run.status == "running"
    assert run.started_at is not None
    assert run.finished_at is None
    assert run.urls_processed == 0


def test_finish_scrape_run_completed(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    run = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    finish_scrape_run(db_session, run_id=run.id, status="completed")
    db_session.refresh(run)
    assert run.status == "completed"
    assert run.finished_at is not None


def test_mark_stale_runs_failed(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    stale = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    db_session.flush()

    count = mark_stale_runs_failed(db_session, shop_id=shop.id, phase="scan")
    assert count == 1
    db_session.refresh(stale)
    assert stale.status == "failed"
    assert stale.finished_at is not None


def test_get_latest_completed_run(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    run = create_scrape_run(db_session, shop_id=shop.id, phase="discover_sitemap")
    finish_scrape_run(db_session, run_id=run.id, status="completed")

    latest = get_latest_completed_run(
        db_session, shop_id=shop.id, phase="discover_sitemap"
    )
    assert latest is not None
    assert latest.id == run.id


def test_get_latest_completed_run_returns_none(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    latest = get_latest_completed_run(
        db_session, shop_id=shop.id, phase="discover_sitemap"
    )
    assert latest is None


def test_update_scrape_run_progress(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    run = create_scrape_run(
        db_session, shop_id=shop.id, phase="scan", urls_total=100
    )
    update_scrape_run_progress(db_session, run_id=run.id, urls_processed=50)
    db_session.refresh(run)
    assert run.urls_processed == 50
    assert run.urls_total == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scrape_runs_repo.py -v`
Expected: ImportError — functions don't exist yet

- [ ] **Step 3: Implement repo functions**

Add to `book_scraper/db/repo.py`:

```python
from book_scraper.db.models import ScrapeRun


def create_scrape_run(
    session: Session,
    shop_id: int,
    phase: str,
    urls_total: int | None = None,
) -> ScrapeRun:
    """Create a new scrape run entry with status=running."""
    run = ScrapeRun(
        shop_id=shop_id,
        phase=phase,
        status="running",
        urls_total=urls_total,
    )
    session.add(run)
    session.flush()
    return run


def finish_scrape_run(
    session: Session,
    run_id: int,
    status: str,
) -> None:
    """Mark a scrape run as completed or failed."""
    run = session.get(ScrapeRun, run_id)
    if run is None:
        return
    run.status = status
    run.finished_at = datetime.now(UTC)


def mark_stale_runs_failed(
    session: Session,
    shop_id: int,
    phase: str,
) -> int:
    """Mark all running (stale/crashed) runs for this shop+phase as failed.
    Returns count of marked runs."""
    now = datetime.now(UTC)
    stale = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == shop_id,
            ScrapeRun.phase == phase,
            ScrapeRun.status == "running",
        )
        .all()
    )
    for run in stale:
        run.status = "failed"
        run.finished_at = now
    return len(stale)


def get_latest_completed_run(
    session: Session,
    shop_id: int,
    phase: str,
) -> ScrapeRun | None:
    """Get the most recent completed run for a shop+phase."""
    return (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == shop_id,
            ScrapeRun.phase == phase,
            ScrapeRun.status == "completed",
        )
        .order_by(ScrapeRun.finished_at.desc())
        .first()
    )


def update_scrape_run_progress(
    session: Session,
    run_id: int,
    urls_processed: int,
) -> None:
    """Update the urls_processed counter on a scrape run."""
    run = session.get(ScrapeRun, run_id)
    if run is None:
        return
    run.urls_processed = urls_processed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scrape_runs_repo.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add book_scraper/db/repo.py tests/test_scrape_runs_repo.py
git commit -m "feat: repo functions for scrape_runs table"
```

---

### Task 5: Update config and TOML structure

**Files:**
- Modify: `config/shops/vaga.toml`
- Modify: `book_scraper/config.py`
- Create: `tests/test_config_strategies.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_config_strategies.py`:

```python
from book_scraper.config import load_shop_config


def test_vaga_config_has_discover_strategies():
    config = load_shop_config("vaga")
    assert "discover" in config
    assert "sitemap" in config["discover"]
    assert config["discover"]["sitemap"]["url"] == "https://vaga.lt/sitemap.xml"


def test_vaga_config_has_category_strategy():
    config = load_shop_config("vaga")
    assert "categories" in config["discover"]
    assert "url" in config["discover"]["categories"]


def test_vaga_config_has_max_age_hours():
    config = load_shop_config("vaga")
    assert "max_age_hours" in config["discover"]["sitemap"]
    assert config["discover"]["sitemap"]["max_age_hours"] == 168


def test_vaga_config_no_prices_section():
    config = load_shop_config("vaga")
    assert "prices" not in config
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_strategies.py -v`
Expected: FAIL — current TOML uses old structure

- [ ] **Step 3: Update vaga.toml**

Rewrite `config/shops/vaga.toml`:

```toml
[shop]
name = "vaga"
base_url = "https://vaga.lt"

[scraping]
download_delay = 0.5
concurrent_requests_per_domain = 3

[discover]
url_include_pattern = '^https://vaga\.lt/[a-z0-9-]+-\d+$'

[discover.sitemap]
url = "https://vaga.lt/sitemap.xml"
max_age_hours = 168

[discover.categories]
url = "https://vaga.lt/knygos?limit=100&page={page}"
max_age_hours = 672

[discover.full_crawl]
start_url = "https://vaga.lt"

[scan]
# Reads from discovered_urls table, no URL needed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_strategies.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add config/shops/vaga.toml tests/test_config_strategies.py
git commit -m "feat: restructure vaga.toml with discover strategies"
```

---

### Task 6: Update `DiscoveredUrlItem` with `source` field

**Files:**
- Modify: `book_scraper/items.py`

- [ ] **Step 1: Add source field to DiscoveredUrlItem**

In `book_scraper/items.py`, update `DiscoveredUrlItem` (currently lines 38-42):

```python
class DiscoveredUrlItem(scrapy.Item):
    url = scrapy.Field()
    shop_name = scrapy.Field()
    source = scrapy.Field()  # "sitemap", "category", or "full_crawl"
```

- [ ] **Step 2: Commit**

```bash
git add book_scraper/items.py
git commit -m "feat: add source field to DiscoveredUrlItem"
```

---

### Task 7: Handle `DiscoveredUrlItem` in pipeline

**Files:**
- Modify: `book_scraper/pipelines.py`
- Modify: `tests/test_items.py` (or create new test file)

- [ ] **Step 1: Write failing test**

Add to `tests/test_items.py` (or create `tests/test_pipeline_discovered.py`):

```python
from unittest.mock import MagicMock

from book_scraper.items import DiscoveredUrlItem
from book_scraper.pipelines import PostgresPipeline


def test_pipeline_processes_discovered_url_item(db_session, engine):
    """DiscoveredUrlItem should be upserted into discovered_urls."""
    from book_scraper.db.models import DiscoveredUrl, Shop

    # Setup: create shop
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.commit()

    # Create pipeline with real session
    pipeline = PostgresPipeline.__new__(PostgresPipeline)
    pipeline.session = db_session
    pipeline.shop_cache = {}
    pipeline.items_since_commit = 0

    item = DiscoveredUrlItem(
        url="https://vaga.lt/book-1", shop_name="vaga", source="sitemap"
    )

    spider = MagicMock()
    pipeline.process_item(item, spider)

    result = db_session.query(DiscoveredUrl).filter_by(url="https://vaga.lt/book-1").first()
    assert result is not None
    assert result.source == "sitemap"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_items.py::test_pipeline_processes_discovered_url_item -v`
Expected: FAIL — pipeline doesn't handle DiscoveredUrlItem yet

- [ ] **Step 3: Add DiscoveredUrlItem handling to PostgresPipeline**

In `book_scraper/pipelines.py`, modify the `process_item` method. Add an import at the top:

```python
from book_scraper.db.repo import upsert_discovered_url
```

Add a new branch in `process_item` for `DiscoveredUrlItem`:

```python
elif isinstance(item, DiscoveredUrlItem):
    shop_id = self._get_shop_id(item["shop_name"])
    upsert_discovered_url(
        self.session,
        shop_id=shop_id,
        url=item["url"],
        source=item["source"],
    )
    self.items_since_commit += 1
    if self.items_since_commit >= 100:
        self.session.commit()
        self.items_since_commit = 0
    return item
```

Also add `DiscoveredUrlItem` to the imports from items:

```python
from book_scraper.items import DiscoveredUrlItem, ListingItem, PriceItem
```

Note: The existing pipeline uses `spider._item_count` for batching (see `pipelines.py:149-154`). The `DiscoveredUrlItem` branch increments the same counter, so commits happen every 100 items across all item types.

Also add scrape_runs progress tracking to the pipeline. After the existing commit block (lines 148-154), add progress update logic. Modify the `process_item` method to also call `update_scrape_run_progress` every 100 items if the spider has a `_run_id`:

```python
# After the existing commit block (lines 148-154 in current code):
if spider._item_count % 100 == 0:
    self.session.commit()
    # Update scrape_run progress if spider tracks it
    if hasattr(spider, "_run_id") and spider._run_id:
        update_scrape_run_progress(
            self.session, spider._run_id, spider._urls_processed
        )
```

Add `update_scrape_run_progress` to the import from `book_scraper.db.repo`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_items.py::test_pipeline_processes_discovered_url_item -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add book_scraper/pipelines.py tests/test_items.py
git commit -m "feat: pipeline handles DiscoveredUrlItem persistence"
```

---

### Task 8: Parser registry (`load_parsers`)

**Files:**
- Create: `book_scraper/spiders/registry.py`
- Create: `tests/test_registry.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_registry.py`:

```python
import pytest

from book_scraper.spiders.registry import load_parsers


def test_load_parsers_returns_vaga_module():
    parsers = load_parsers("vaga")
    assert hasattr(parsers, "parse_sitemap_urls")
    assert hasattr(parsers, "parse_category_page")
    assert hasattr(parsers, "parse_product_page")


def test_load_parsers_unknown_shop_raises():
    with pytest.raises(ImportError):
        load_parsers("nonexistent_shop")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_registry.py -v`
Expected: ImportError — module doesn't exist

- [ ] **Step 3: Implement registry**

Create `book_scraper/spiders/registry.py`:

```python
import importlib
from types import ModuleType


def load_parsers(shop_name: str) -> ModuleType:
    """Dynamically load the parsers module for a shop.

    Looks for book_scraper.spiders.<shop_name>.parsers
    Raises ImportError if the shop's parser module doesn't exist.
    """
    module_path = f"book_scraper.spiders.{shop_name}.parsers"
    return importlib.import_module(module_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_registry.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add book_scraper/spiders/registry.py tests/test_registry.py
git commit -m "feat: parser registry for dynamic shop parser loading"
```

---

### Task 9: Generic `discover` spider

**Files:**
- Create: `book_scraper/spiders/discover.py`

- [ ] **Step 1: Implement generic discover spider**

Create `book_scraper/spiders/discover.py`:

```python
import re
from typing import Any, Generator

import scrapy

from book_scraper.config import load_shop_config
from book_scraper.items import DiscoveredUrlItem, PriceItem
from book_scraper.spiders.registry import load_parsers


class DiscoverSpider(scrapy.Spider):
    name = "discover"

    def __init__(self, shop: str | None = None, strategy: str = "sitemap", **kwargs: Any):
        super().__init__(**kwargs)
        if not shop:
            raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
        self.shop_name = shop
        self.strategy = strategy
        self.conf = load_shop_config(shop)
        self.parsers = load_parsers(shop)
        self.allowed_domains = [
            self.conf["shop"]["base_url"]
            .replace("https://", "")
            .replace("http://", "")
        ]

        # Load URL filter pattern
        discover_conf = self.conf.get("discover", {})
        pattern = discover_conf.get("url_include_pattern")
        self.url_pattern = re.compile(pattern) if pattern else None

        # Load strategy-specific config
        strategy_conf = discover_conf.get(strategy)
        if strategy_conf is None:
            raise ValueError(
                f"Strategy '{strategy}' not configured for shop '{shop}'"
            )
        self.strategy_conf = strategy_conf

        # Apply scraping settings
        scraping = self.conf.get("scraping", {})
        self.custom_settings = {
            "CONCURRENT_REQUESTS_PER_DOMAIN": scraping.get(
                "concurrent_requests_per_domain", 1
            ),
            "DOWNLOAD_DELAY": scraping.get("download_delay", 1.0),
        }

    def _url_passes_filter(self, url: str) -> bool:
        if self.url_pattern is None:
            return True
        return bool(self.url_pattern.match(url))

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        if self.strategy == "sitemap":
            yield scrapy.Request(
                self.strategy_conf["url"], callback=self.parse_sitemap
            )
        elif self.strategy == "categories":
            url = self.strategy_conf["url"].format(page=1)
            yield scrapy.Request(url, callback=self.parse_categories, meta={"page": 1})
        elif self.strategy == "full_crawl":
            yield scrapy.Request(
                self.strategy_conf["start_url"], callback=self.parse_full_crawl
            )

    def parse_sitemap(self, response: scrapy.http.Response) -> Generator[DiscoveredUrlItem, None, None]:
        urls = self.parsers.parse_sitemap_urls(response.text)
        for url in urls:
            if self._url_passes_filter(url):
                yield DiscoveredUrlItem(
                    url=url, shop_name=self.shop_name, source="sitemap"
                )

    def parse_categories(self, response: scrapy.http.Response) -> Generator[DiscoveredUrlItem | PriceItem, None, None]:
        products = self.parsers.parse_category_page(response.text)
        if not products:
            return  # No more pages

        base_url = self.conf["shop"]["base_url"]
        for product in products:
            url = product["url"]
            if not url.startswith("http"):
                url = base_url + url

            if self._url_passes_filter(url):
                yield DiscoveredUrlItem(
                    url=url, shop_name=self.shop_name, source="category"
                )

                # Also yield price data if available
                if product.get("price"):
                    yield PriceItem(
                        url=url,
                        shop_name=self.shop_name,
                        title=product.get("title", ""),
                        price=product.get("price"),
                        price_original=product.get("price_original"),
                        in_stock=True,
                    )

        # Paginate
        page = response.meta["page"] + 1
        next_url = self.strategy_conf["url"].format(page=page)
        yield scrapy.Request(
            next_url, callback=self.parse_categories, meta={"page": page}
        )

    def parse_full_crawl(self, response: scrapy.http.Response) -> Generator[DiscoveredUrlItem | scrapy.Request, None, None]:
        """Follow all internal links, yield product URLs."""
        base_url = self.conf["shop"]["base_url"]
        seen = getattr(self, "_seen_urls", set())
        self._seen_urls = seen

        for link in response.css("a::attr(href)").getall():
            if not link.startswith("http"):
                link = response.urljoin(link)

            if not link.startswith(base_url):
                continue
            if link in seen:
                continue
            seen.add(link)

            if self._url_passes_filter(link):
                yield DiscoveredUrlItem(
                    url=link, shop_name=self.shop_name, source="full_crawl"
                )

            # Follow all internal links for further crawling
            yield scrapy.Request(
                link, callback=self.parse_full_crawl, dont_filter=False
            )
```

- [ ] **Step 2: Run mypy**

Run: `uv run mypy book_scraper/spiders/discover.py`
Expected: No errors

- [ ] **Step 3: Smoke test with dry run**

Run: `uv run scrapy crawl discover -a shop=vaga -a strategy=sitemap -s CLOSESPIDER_ITEMCOUNT=5 --nolog 2>&1 | head -20`
Expected: Spider starts without errors (may fail on DB if not running, that's OK — we're checking import/config wiring)

- [ ] **Step 4: Commit**

```bash
git add book_scraper/spiders/discover.py
git commit -m "feat: generic discover spider with sitemap/categories/full_crawl strategies"
```

---

### Task 10: Generic `scan` spider with resume support

**Files:**
- Create: `book_scraper/spiders/scan.py` (new file at `book_scraper/spiders/scan.py`, NOT in vaga/)

- [ ] **Step 1: Implement generic scan spider**

Create `book_scraper/spiders/scan.py`:

```python
from datetime import UTC, datetime, timedelta
from typing import Any, Generator

import scrapy
from sqlalchemy.orm import Session

from book_scraper.config import load_shop_config
from book_scraper.db.models import Listing
from book_scraper.db.repo import (
    create_scrape_run,
    finish_scrape_run,
    get_latest_completed_run,
    get_pending_scan_urls,
    mark_stale_runs_failed,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory
from book_scraper.items import ListingItem
from book_scraper.spiders.registry import load_parsers


class ScanSpider(scrapy.Spider):
    name = "scan"

    def __init__(self, shop: str | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        if not shop:
            raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
        self.shop_name = shop
        self.conf = load_shop_config(shop)
        self.parsers = load_parsers(shop)
        self.allowed_domains = [
            self.conf["shop"]["base_url"]
            .replace("https://", "")
            .replace("http://", "")
        ]

        scraping = self.conf.get("scraping", {})
        self.custom_settings = {
            "CONCURRENT_REQUESTS_PER_DOMAIN": scraping.get(
                "concurrent_requests_per_domain", 1
            ),
            "DOWNLOAD_DELAY": scraping.get("download_delay", 1.0),
        }

        self._run_id: int | None = None
        self._urls_processed = 0
        self._url_id_map: dict[str, int] = {}  # url -> discovered_url.id

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        database_url = self.settings.get("DATABASE_URL")
        session_factory = get_session_factory(database_url)
        session: Session = session_factory()

        try:
            shop = upsert_shop(
                session, self.shop_name, self.conf["shop"]["base_url"]
            )

            # Mark stale/crashed runs as failed
            stale_count = mark_stale_runs_failed(session, shop.id, "scan")
            if stale_count:
                self.logger.info(f"Marked {stale_count} stale scan run(s) as failed")

            # Auto-discover if needed
            self._auto_discover_if_needed(session, shop.id)

            # Create new run
            pending_urls = get_pending_scan_urls(session, shop.id)

            # Filter out already-scraped URLs (resume logic)
            run_start = datetime.now(UTC)
            urls_to_scrape = self._filter_already_done(
                session, shop.id, pending_urls, run_start
            )

            run = create_scrape_run(
                session, shop.id, "scan", urls_total=len(urls_to_scrape)
            )
            self._run_id = run.id
            session.commit()

            self.logger.info(
                f"Scan starting: {len(urls_to_scrape)} URLs to scrape "
                f"({len(pending_urls) - len(urls_to_scrape)} skipped as already done)"
            )

            # Build URL -> discovered_url.id map for status updates
            for url_record in pending_urls:
                self._url_id_map[url_record.url] = url_record.id

            for url_record in urls_to_scrape:
                yield scrapy.Request(
                    url_record.url,
                    callback=self.parse_product,
                    errback=self.handle_error,
                    meta={"discovered_url_id": url_record.id},
                )
        finally:
            session.close()

    def _auto_discover_if_needed(self, session: Session, shop_id: int) -> None:
        """Check if discovery is fresh enough. If stale or missing, run discover
        inline using CrawlerRunner before scan proceeds.

        Note: Inline discover is complex in Scrapy (requires CrawlerRunner in
        the same reactor). For simplicity, this implementation logs a warning
        and raises an error if no discovered URLs exist at all, forcing the user
        to run discover first. If URLs exist but are stale, it warns but proceeds.
        """
        discover_conf = self.conf.get("discover", {})
        from book_scraper.db.models import DiscoveredUrl

        has_any_urls = (
            session.query(DiscoveredUrl)
            .filter(DiscoveredUrl.shop_id == shop_id)
            .first()
            is not None
        )

        if not has_any_urls:
            raise RuntimeError(
                f"No discovered URLs for shop '{self.shop_name}'. "
                f"Run discover first: scrapy crawl discover -a shop={self.shop_name} -a strategy=sitemap"
            )

        # Check freshness — warn if stale but don't block
        for strategy in ("sitemap", "categories"):
            strategy_conf = discover_conf.get(strategy)
            if strategy_conf is None:
                continue
            max_age = strategy_conf.get("max_age_hours")
            if max_age is None:
                continue

            phase = f"discover_{strategy}"
            latest = get_latest_completed_run(session, shop_id, phase)

            if latest is None:
                self.logger.warning(
                    f"No completed {phase} run found. "
                    f"Run: scrapy crawl discover -a shop={self.shop_name} -a strategy={strategy}"
                )
                continue

            age_hours = (
                datetime.now(UTC) - latest.finished_at
            ).total_seconds() / 3600
            if age_hours > max_age:
                self.logger.warning(
                    f"Last {phase} is {age_hours:.0f}h old (max: {max_age}h). "
                    f"Run: scrapy crawl discover -a shop={self.shop_name} -a strategy={strategy}"
                )

    def _filter_already_done(
        self,
        session: Session,
        shop_id: int,
        pending_urls: list,
        run_start: datetime,
    ) -> list:
        """Filter out URLs that were already scraped in a recent (possibly crashed) run."""
        # Find the most recent run's start time (could be a crashed run we just marked failed)
        from book_scraper.db.models import ScrapeRun

        recent_run = (
            session.query(ScrapeRun)
            .filter(
                ScrapeRun.shop_id == shop_id,
                ScrapeRun.phase == "scan",
                ScrapeRun.status.in_(["completed", "failed"]),
            )
            .order_by(ScrapeRun.started_at.desc())
            .first()
        )

        if recent_run is None:
            return pending_urls

        # Get URLs that have been scraped since the recent run started
        cutoff = recent_run.started_at
        scraped_urls = set(
            row[0]
            for row in session.query(Listing.url)
            .filter(
                Listing.shop_id == shop_id,
                Listing.last_seen_at >= cutoff,
            )
            .all()
        )

        return [u for u in pending_urls if u.url not in scraped_urls]

    def parse_product(self, response: scrapy.http.Response) -> Generator[ListingItem, None, None]:
        discovered_url_id = response.meta.get("discovered_url_id")

        if response.status in (404, 410):
            self._update_url_status(
                discovered_url_id, http_status=response.status, increment_fail=True
            )
            return

        data = self.parsers.parse_product_page(response.text)

        if not data.get("title"):
            # Page returned 200 but no product data — mark as non_product
            self._update_url_status(
                discovered_url_id, http_status=200, url_type="non_product"
            )
            return

        # Build properties dict from format-specific fields
        properties = {}
        for key in ("pages", "cover_type", "duration", "narrator", "translator"):
            if data.get(key):
                properties[key] = data[key]

        item = ListingItem(
            url=response.url,
            shop_name=self.shop_name,
            title=data.get("title"),
            author=data.get("author"),
            sku=data.get("sku"),
            isbn=data.get("isbn"),
            publisher=data.get("publisher"),
            year=data.get("year"),
            format=data.get("format"),
            description=data.get("description"),
            image_url=data.get("image_url"),
            categories=data.get("categories"),
            properties=properties if properties else None,
            price=data.get("price"),
            price_original=data.get("price_original"),
            in_stock=data.get("in_stock", True),
        )

        # Mark URL as successfully scraped
        self._update_url_status(
            discovered_url_id, http_status=200, url_type="product"
        )

        self._urls_processed += 1

        yield item

    def handle_error(self, failure: Any) -> None:
        """Handle request failures (timeouts, connection errors, etc.)."""
        request = failure.request
        discovered_url_id = request.meta.get("discovered_url_id")

        status = getattr(failure.value, "response", None)
        http_status = status.status if status else None

        self._update_url_status(
            discovered_url_id,
            http_status=http_status,
            increment_fail=True,
        )

    def _update_url_status(
        self,
        url_id: int | None,
        http_status: int | None = None,
        url_type: str | None = None,
        increment_fail: bool = False,
    ) -> None:
        """Update discovered_url status. Uses the pipeline's session via a signal."""
        if url_id is None:
            return
        # Store for batch processing in pipeline
        if not hasattr(self, "_url_status_updates"):
            self._url_status_updates = []
        self._url_status_updates.append(
            {
                "url_id": url_id,
                "http_status": http_status,
                "url_type": url_type,
                "increment_fail": increment_fail,
            }
        )

    def closed(self, reason: str) -> None:
        """Called when spider closes. Update scrape_run status."""
        if self._run_id is None:
            return

        database_url = self.settings.get("DATABASE_URL")
        session_factory = get_session_factory(database_url)
        session = session_factory()

        try:
            # Process any remaining URL status updates
            for update in getattr(self, "_url_status_updates", []):
                update_discovered_url_status(session, **update)

            status = "completed" if reason == "finished" else "failed"
            update_scrape_run_progress(session, self._run_id, self._urls_processed)
            finish_scrape_run(session, self._run_id, status)
            session.commit()
        finally:
            session.close()
```

- [ ] **Step 2: Run mypy**

Run: `uv run mypy book_scraper/spiders/scan.py`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 3: Commit**

```bash
git add book_scraper/spiders/scan.py
git commit -m "feat: generic scan spider with resume support and auto-discover check"
```

---

### Task 11: Remove old per-shop spiders

**Files:**
- Delete: `book_scraper/spiders/vaga/discover.py`
- Delete: `book_scraper/spiders/vaga/scan.py`
- Delete: `book_scraper/spiders/vaga/prices.py`

- [ ] **Step 1: Verify new spiders are discoverable by Scrapy**

Run: `uv run scrapy list`
Expected: Should include `discover` and `scan` (and NOT `vaga_discover`, `vaga_scan`, `vaga_prices` since we haven't deleted them yet — they'll show too, that's fine for now)

- [ ] **Step 2: Delete old spider files**

```bash
rm book_scraper/spiders/vaga/discover.py
rm book_scraper/spiders/vaga/scan.py
rm book_scraper/spiders/vaga/prices.py
```

- [ ] **Step 3: Update `book_scraper/spiders/vaga/__init__.py`**

Ensure `book_scraper/spiders/vaga/__init__.py` is empty or just has a comment — it's now just a parsers package:

```python
# vaga shop parsers package
```

- [ ] **Step 4: Verify only new spiders are listed**

Run: `uv run scrapy list`
Expected: `discover` and `scan` only (no `vaga_*` spiders)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove per-shop spiders, replaced by generic discover and scan"
```

---

### Task 12: Update existing tests

**Files:**
- Modify: `tests/test_vaga_parsers.py` (should still pass — parsers are unchanged)
- Modify: `tests/test_items.py` (may need updates if pipeline imports changed)
- Modify: `tests/test_db_repo.py` (should still pass)

- [ ] **Step 1: Run all existing tests**

Run: `uv run pytest -v`
Expected: All existing tests pass. If any fail due to import changes, fix them.

- [ ] **Step 2: Run linter and type checker**

Run: `uv run ruff check book_scraper/ tests/` and `uv run mypy book_scraper/`
Expected: No new errors. Fix any that appear.

- [ ] **Step 3: Run formatter**

Run: `uv run ruff format book_scraper/ tests/`

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: update tests and fix lint/type issues after refactor"
```

---

### Task 13: Integration smoke test

**Files:** No new files

- [ ] **Step 1: Ensure Docker DBs are running**

Run: `docker compose up -d postgres postgres-test`

- [ ] **Step 2: Run migrations**

Run: `PYTHONPATH=. uv run alembic upgrade head`

- [ ] **Step 3: Smoke test discover with sitemap (limit to 10 items)**

Run: `uv run scrapy crawl discover -a shop=vaga -a strategy=sitemap -s CLOSESPIDER_ITEMCOUNT=10`
Expected: Spider runs, discovers URLs, no errors

- [ ] **Step 4: Verify URLs are in DB**

Run: `PYTHONPATH=. uv run python -c "from book_scraper.db.session import get_session_factory; from book_scraper.db.models import DiscoveredUrl; s = get_session_factory('postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper')(); print(f'Discovered URLs: {s.query(DiscoveredUrl).count()}'); s.close()"`
Expected: Count > 0

- [ ] **Step 5: Smoke test scan (limit to 3 items)**

Run: `uv run scrapy crawl scan -a shop=vaga -s CLOSESPIDER_ITEMCOUNT=3`
Expected: Spider runs, scrapes product pages from discovered URLs, no errors

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 7: Commit if any fixes needed**

```bash
git add -A
git commit -m "fix: integration test fixes"
```
