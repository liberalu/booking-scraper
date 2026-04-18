# Scrape URL Items Pipeline — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the scan pipeline fully match the design in the Notion spec "Scraping pipeline queue — scrape_url_items": add a `url_type` column, delete staging rows on run completion, allow crash-killed runs to resume instead of being marked failed, and second-pass new product URLs discovered mid-scan during rescrape.

**Architecture:** The `scrape_url_items` table already exists and is used by the scan spider for crash-resume within a single run. This plan extends it: (1) adds a type discriminator column, (2) cleans up staging rows when a run finishes, (3) changes `prepare_scan` to resume an existing "running" run with pending items instead of creating a new one, and (4) makes the scan spider queue newly-discovered product URLs into `scrape_url_items` mid-run so they are processed in the same run as a second pass. Extending the queue to discover spiders (`discover_sitemap`, `discover_categories`, `discover_full_crawl`) is deferred to a separate plan because it requires reworking those spiders' start methods.

**Tech Stack:** Python 3.12, Scrapy, SQLAlchemy 2.0, Alembic, PostgreSQL, pytest (integration tests hit real Postgres on port 5433).

---

## File Structure

**Modified:**
- `book_scraper/db/models.py` — add `url_type` column to `ScrapeUrlItem`
- `book_scraper/db/repo.py` — add `cleanup_scrape_url_items`, `find_resumable_run`, `insert_scrape_url_item`; update `prepare_scrape_url_items` to set `url_type`
- `book_scraper/services/scan.py` — `prepare_scan` returns resume vs new run; `finish_scan` deletes staging rows; add `enqueue_new_url` for mid-run inserts
- `book_scraper/spiders/scan.py` — queue newly-discovered product URLs during rescrape, yield follow-up requests
- `book_scraper/pipelines.py` — when a `ShopBookItem` is a new product URL, call `enqueue_new_url` during rescrape

**Created:**
- `alembic/versions/<new>_add_url_type_to_scrape_url_items.py` — migration adding `url_type` column
- `tests/integration/test_scrape_url_items_cleanup.py` — new integration tests
- `tests/integration/test_resumable_runs.py` — new integration tests
- `tests/integration/test_scan_second_pass.py` — new integration tests

---

## Task 1: Add `url_type` column to `scrape_url_items`

**Files:**
- Modify: `book_scraper/db/models.py` (ScrapeUrlItem)
- Modify: `book_scraper/db/repo.py` (prepare_scrape_url_items)
- Create: `alembic/versions/<timestamp>_add_url_type_to_scrape_url_items.py`
- Test: `tests/integration/test_scan_service.py` (extend existing)

- [ ] **Step 1: Write the failing test for `url_type` persistence**

Append to `tests/integration/test_scan_service.py`:

```python
def test_prepare_scan_persists_url_type_on_items(db_session, sample_shop_config):
    from book_scraper.db.models import DiscoveredUrl, ScrapeUrlItem
    from book_scraper.db.repo import upsert_shop
    from book_scraper.services.scan import ScanService

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/foo",
            normalized_url="https://vaga.lt/foo",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", sample_shop_config, rescrape=True)

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    assert items[0].url_type == "product"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_scan_service.py::test_prepare_scan_persists_url_type_on_items -v`
Expected: FAIL — `AttributeError: type object 'ScrapeUrlItem' has no attribute 'url_type'`

- [ ] **Step 3: Generate the migration**

Run (from repo root):
```bash
PYTHONPATH=. uv run alembic revision -m "add_url_type_to_scrape_url_items"
```

Replace the generated file contents with:

```python
"""add_url_type_to_scrape_url_items

Revision ID: <keep-generated-id>
Revises: bd5719da484f
Create Date: <keep-generated-date>

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "<keep-generated-id>"
down_revision: Union[str, Sequence[str], None] = "bd5719da484f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scrape_url_items",
        sa.Column(
            "url_type",
            sa.Text(),
            nullable=False,
            server_default="product",
        ),
    )


def downgrade() -> None:
    op.drop_column("scrape_url_items", "url_type")
```

- [ ] **Step 4: Update the model**

In `book_scraper/db/models.py`, inside `class ScrapeUrlItem`, add the new column after `url`:

```python
url_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="product")
```

Keep all existing columns unchanged.

- [ ] **Step 5: Update `prepare_scrape_url_items` to populate `url_type`**

In `book_scraper/db/repo.py`, replace the body of `prepare_scrape_url_items` with:

```python
def prepare_scrape_url_items(
    session: Session,
    shop_id: int,
    run_id: int,
    url_records: "list[DiscoveredUrl]",
) -> None:
    """Batch-insert pending scrape_url_items for a new scan run.

    Persists the work queue to DB so the spider can resume after a crash.
    Uses each DiscoveredUrl.url_type as the item's url_type (defaults to 'product').
    """
    for rec in url_records:
        session.add(
            ScrapeUrlItem(
                run_id=run_id,
                shop_id=shop_id,
                discovered_url_id=rec.id,
                url=rec.url,
                url_type=rec.url_type or "product",
                status="pending",
            )
        )
    session.flush()
```

- [ ] **Step 6: Apply the migration**

Run: `PYTHONPATH=. uv run alembic upgrade head`
Expected: migration applies cleanly, no errors.

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/integration/test_scan_service.py::test_prepare_scan_persists_url_type_on_items -v`
Expected: PASS

- [ ] **Step 8: Run full test suite to check nothing broke**

Run: `uv run pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add alembic/versions/ book_scraper/db/models.py book_scraper/db/repo.py tests/integration/test_scan_service.py
git commit -m "feat(scrape-queue): add url_type column to scrape_url_items"
```

---

## Task 2: Delete staging rows when a run finishes

**Files:**
- Modify: `book_scraper/db/repo.py` (add `cleanup_scrape_url_items`)
- Modify: `book_scraper/services/scan.py` (`finish_scan` calls cleanup)
- Create: `tests/integration/test_scrape_url_items_cleanup.py`

- [ ] **Step 1: Write the failing cleanup test**

Create `tests/integration/test_scrape_url_items_cleanup.py`:

```python
"""Cleanup of scrape_url_items when a run finishes."""

from book_scraper.db.models import DiscoveredUrl, ScrapeUrlItem
from book_scraper.db.repo import upsert_shop
from book_scraper.services.scan import ScanService


def test_finish_scan_deletes_staging_rows(db_session, sample_shop_config):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/a",
            normalized_url="https://vaga.lt/a",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", sample_shop_config, rescrape=True)
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 1

    service.finish_scan(plan.run_id, urls_processed=0, url_status_updates=[], reason="finished")

    remaining = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count()
    assert remaining == 0, "scrape_url_items for a finished run must be deleted"


def test_finish_scan_failed_run_also_deletes_rows(db_session, sample_shop_config):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/b",
            normalized_url="https://vaga.lt/b",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", sample_shop_config, rescrape=True)
    service.finish_scan(plan.run_id, urls_processed=0, url_status_updates=[], reason="cancelled")

    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_scrape_url_items_cleanup.py -v`
Expected: FAIL — `assert 1 == 0, "scrape_url_items for a finished run must be deleted"`.

- [ ] **Step 3: Add `cleanup_scrape_url_items` to repo**

Append to `book_scraper/db/repo.py` (after `reset_processing_scrape_url_items`):

```python
def cleanup_scrape_url_items(session: Session, run_id: int) -> int:
    """Delete all scrape_url_items for a finished run.

    scrape_url_items is a staging table — rows are deleted when the run
    ends (completed or failed). Progress is already persisted to
    discovered_urls, shop_books, and prices via pipelines.

    Returns the number of rows deleted.
    """
    deleted = (
        session.query(ScrapeUrlItem)
        .filter(ScrapeUrlItem.run_id == run_id)
        .delete(synchronize_session=False)
    )
    session.flush()
    return deleted
```

- [ ] **Step 4: Call cleanup from `finish_scan`**

In `book_scraper/services/scan.py`, update the import and the `finish_scan` method:

Replace the top-of-file import block with:

```python
from book_scraper.db.repo import (
    check_discover_freshness,
    cleanup_scrape_url_items,
    create_scrape_run,
    finish_scrape_run,
    get_pending_scan_urls,
    get_urls_already_scraped,
    mark_scrape_url_item_done,
    mark_scrape_url_item_failed,
    mark_stale_runs_failed,
    prepare_scrape_url_items,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_shop,
)
```

Replace the existing `finish_scan` method with:

```python
def finish_scan(
    self,
    run_id: int,
    urls_processed: int,
    url_status_updates: list[dict[str, Any]],
    reason: str,
) -> None:
    """Finalize a scan run: process URL status updates, update progress,
    mark run as completed/failed, delete staging rows."""
    for update in url_status_updates:
        scrape_item_id = update.pop("scrape_url_item_id", None)
        scrape_item_success = update.pop("scrape_url_item_success", False)
        update_discovered_url_status(self.session, **update)
        if scrape_item_id is not None:
            if scrape_item_success:
                mark_scrape_url_item_done(self.session, scrape_item_id)
            else:
                mark_scrape_url_item_failed(self.session, scrape_item_id)

    status = "completed" if reason == "finished" else "failed"
    update_scrape_run_progress(self.session, run_id, urls_processed)
    finish_scrape_run(self.session, run_id, status)
    cleanup_scrape_url_items(self.session, run_id)
    self.session.commit()
```

- [ ] **Step 5: Run the cleanup tests to verify they pass**

Run: `uv run pytest tests/integration/test_scrape_url_items_cleanup.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: all tests pass. If `test_scan_service.py` tests that inspect `scrape_url_items` after `finish_scan` now fail, remove those assertions (the data is intentionally deleted now).

- [ ] **Step 7: Commit**

```bash
git add book_scraper/db/repo.py book_scraper/services/scan.py tests/integration/test_scrape_url_items_cleanup.py
git commit -m "feat(scrape-queue): delete scrape_url_items on run completion"
```

---

## Task 3: Resume an existing "running" run with pending items instead of failing it

**Files:**
- Modify: `book_scraper/db/repo.py` (add `find_resumable_run`)
- Modify: `book_scraper/services/scan.py` (`prepare_scan` resume path)
- Create: `tests/integration/test_resumable_runs.py`

- [ ] **Step 1: Write the failing resume test**

Create `tests/integration/test_resumable_runs.py`:

```python
"""A 'running' scrape run with pending scrape_url_items is resumable."""

from book_scraper.db.models import DiscoveredUrl, ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import upsert_shop
from book_scraper.services.scan import ScanService


def _seed_one_url(db_session, shop_id):
    db_session.add(
        DiscoveredUrl(
            shop_id=shop_id,
            url="https://vaga.lt/a",
            normalized_url="https://vaga.lt/a",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()


def test_resume_running_run_with_pending_items(db_session, sample_shop_config):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id)

    service = ScanService(db_session)
    first = service.prepare_scan("vaga", "https://vaga.lt", sample_shop_config, rescrape=True)
    first_run_id = first.run_id

    assert db_session.query(ScrapeUrlItem).filter_by(run_id=first_run_id).count() == 1

    # Second prepare_scan: simulates a restart. Should resume, not create a new run.
    second = service.prepare_scan("vaga", "https://vaga.lt", sample_shop_config, rescrape=True)

    assert second.run_id == first_run_id, "must reuse the resumable run"
    assert db_session.query(ScrapeRun).filter_by(status="running").count() == 1
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=first_run_id).count() == 1


def test_new_run_created_when_previous_run_has_no_pending_items(
    db_session, sample_shop_config
):
    """A run whose items were all marked done/failed is NOT resumable."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id)

    service = ScanService(db_session)
    first = service.prepare_scan("vaga", "https://vaga.lt", sample_shop_config, rescrape=True)

    # Finish the first run — this deletes the staging rows.
    service.finish_scan(first.run_id, urls_processed=1, url_status_updates=[], reason="finished")

    # Add a new URL so there is something to do on the second run.
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/b",
            normalized_url="https://vaga.lt/b",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    second = service.prepare_scan("vaga", "https://vaga.lt", sample_shop_config, rescrape=True)
    assert second.run_id != first.run_id, "a new run must be created"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_resumable_runs.py -v`
Expected: FAIL — `second.run_id == first_run_id` fails because the current `prepare_scan` always creates a new run.

- [ ] **Step 3: Add `find_resumable_run` to repo**

Append to `book_scraper/db/repo.py` (after `mark_stale_runs_failed`):

```python
def find_resumable_run(
    session: Session,
    shop_id: int,
    phase: str,
) -> "ScrapeRun | None":
    """Find a 'running' scrape run with pending scrape_url_items.

    Such a run was crash-interrupted and can be resumed: the queue still
    holds unprocessed URLs. Returns None if no resumable run exists.
    """
    from sqlalchemy import exists

    has_pending = (
        exists()
        .where(ScrapeUrlItem.run_id == ScrapeRun.id)
        .where(ScrapeUrlItem.status == "pending")
    )
    stmt = (
        select(ScrapeRun)
        .where(
            ScrapeRun.shop_id == shop_id,
            ScrapeRun.phase == phase,
            ScrapeRun.status == "running",
            has_pending,
        )
        .order_by(ScrapeRun.started_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
```

- [ ] **Step 4: Update `prepare_scan` to check for resumable run first**

In `book_scraper/services/scan.py`, add `find_resumable_run` to the import block:

```python
from book_scraper.db.repo import (
    check_discover_freshness,
    cleanup_scrape_url_items,
    create_scrape_run,
    find_resumable_run,
    finish_scrape_run,
    get_pending_scan_urls,
    get_urls_already_scraped,
    mark_scrape_url_item_done,
    mark_scrape_url_item_failed,
    mark_stale_runs_failed,
    prepare_scrape_url_items,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_shop,
)
```

Replace the `prepare_scan` method body with:

```python
def prepare_scan(
    self,
    shop_name: str,
    base_url: str,
    shop_config: Any,
    rescrape: bool = False,
) -> ScanPlan:
    """Prepare a scan run.

    If a previous 'running' run with pending scrape_url_items exists for
    this shop, resume it (return its run_id, keep the queue). Otherwise
    mark stale runs failed, create a new run, and populate the queue.
    """
    shop = upsert_shop(self.session, shop_name, base_url)

    resumable = find_resumable_run(self.session, shop.id, "scan")
    if resumable is not None:
        pending_count = (
            self.session.query(ScrapeUrlItem)
            .filter_by(run_id=resumable.id, status="pending")
            .count()
        )
        return ScanPlan(
            run_id=resumable.id,
            urls_total=pending_count,
            urls_skipped=0,
            freshness_warnings=[],
        )

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
    prepare_scrape_url_items(self.session, shop.id, run.id, urls_to_scrape)
    self.session.commit()

    return ScanPlan(
        run_id=run.id,
        urls_total=len(urls_to_scrape),
        urls_skipped=urls_skipped,
        freshness_warnings=warnings,
    )
```

At the top of `scan.py`, add the ScrapeUrlItem import:

```python
from book_scraper.db.models import ScrapeUrlItem
```

- [ ] **Step 5: Run the resume tests to verify they pass**

Run: `uv run pytest tests/integration/test_resumable_runs.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add book_scraper/db/repo.py book_scraper/services/scan.py tests/integration/test_resumable_runs.py
git commit -m "feat(scrape-queue): resume running runs with pending queue items"
```

---

## Task 4: Second-pass — queue new product URLs discovered mid-rescrape

**Files:**
- Modify: `book_scraper/db/repo.py` (add `insert_scrape_url_item`)
- Modify: `book_scraper/services/scan.py` (add `enqueue_new_url`)
- Modify: `book_scraper/spiders/scan.py` (detect new discovered URLs, yield follow-up Request)
- Modify: `book_scraper/pipelines.py` (call `enqueue_new_url` when a new DiscoveredUrl is upserted during a scan run)
- Create: `tests/integration/test_scan_second_pass.py`

**Scope note:** The scan spider reads full product pages. New "unknown" product URLs can only appear if a product page has a redirect to another product page, or if the parser discovers cross-links. The hook is: whenever `upsert_discovered_url` in the pipeline inserts a brand-new `DiscoveredUrl` row during a scan run with `rescrape=True`, the pipeline also inserts a pending `scrape_url_items` row linked to the current run. The spider then picks those up via its existing request yielding on the follow-up pass.

- [ ] **Step 1: Write the failing second-pass test**

Create `tests/integration/test_scan_second_pass.py`:

```python
"""New URLs added to scrape_url_items mid-run are processed in the same run."""

from book_scraper.db.models import DiscoveredUrl, ScrapeUrlItem
from book_scraper.db.repo import insert_scrape_url_item, upsert_shop
from book_scraper.services.scan import ScanService


def test_insert_scrape_url_item_adds_pending_row(db_session, sample_shop_config):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/a",
            normalized_url="https://vaga.lt/a",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", sample_shop_config, rescrape=True)

    new_du = DiscoveredUrl(
        shop_id=shop.id,
        url="https://vaga.lt/b",
        normalized_url="https://vaga.lt/b",
        source="product_page",
        url_type="product",
        fail_count=0,
    )
    db_session.add(new_du)
    db_session.commit()

    item = insert_scrape_url_item(
        db_session,
        run_id=plan.run_id,
        shop_id=shop.id,
        discovered_url_id=new_du.id,
        url=new_du.url,
        url_type="product",
    )
    db_session.commit()

    assert item.status == "pending"
    assert (
        db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id, status="pending").count()
        == 2
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_scan_second_pass.py -v`
Expected: FAIL — `ImportError: cannot import name 'insert_scrape_url_item'`.

- [ ] **Step 3: Add `insert_scrape_url_item` to repo**

Append to `book_scraper/db/repo.py` (after `cleanup_scrape_url_items`):

```python
def insert_scrape_url_item(
    session: Session,
    run_id: int,
    shop_id: int,
    discovered_url_id: int | None,
    url: str,
    url_type: str = "product",
) -> ScrapeUrlItem:
    """Insert a single pending scrape_url_item mid-run.

    Used to enqueue newly-discovered URLs so the same run processes them
    as a second pass. Idempotent: if an item for (run_id, url) already
    exists, returns it unchanged.
    """
    existing = (
        session.query(ScrapeUrlItem)
        .filter_by(run_id=run_id, url=url)
        .one_or_none()
    )
    if existing is not None:
        return existing
    item = ScrapeUrlItem(
        run_id=run_id,
        shop_id=shop_id,
        discovered_url_id=discovered_url_id,
        url=url,
        url_type=url_type,
        status="pending",
    )
    session.add(item)
    session.flush()
    return item
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integration/test_scan_second_pass.py -v`
Expected: PASS.

- [ ] **Step 5: Add `enqueue_new_url` to ScanService**

In `book_scraper/services/scan.py`, update the import block to include `insert_scrape_url_item`:

```python
from book_scraper.db.repo import (
    check_discover_freshness,
    cleanup_scrape_url_items,
    create_scrape_run,
    find_resumable_run,
    finish_scrape_run,
    get_pending_scan_urls,
    get_urls_already_scraped,
    insert_scrape_url_item,
    mark_scrape_url_item_done,
    mark_scrape_url_item_failed,
    mark_stale_runs_failed,
    prepare_scrape_url_items,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_shop,
)
```

Add this method to `ScanService`:

```python
def enqueue_new_url(
    self,
    run_id: int,
    shop_id: int,
    discovered_url_id: int | None,
    url: str,
    url_type: str = "product",
) -> int:
    """Queue a newly-discovered URL for same-run processing. Returns item id."""
    item = insert_scrape_url_item(
        self.session, run_id, shop_id, discovered_url_id, url, url_type
    )
    self.session.commit()
    return item.id
```

- [ ] **Step 6: Write the pipeline-integration test**

Append to `tests/integration/test_scan_second_pass.py`:

```python
def test_pipeline_queues_new_urls_during_rescrape(db_session, sample_shop_config):
    """When rescrape encounters a new URL via upsert_discovered_url, it
    is queued into scrape_url_items for same-run processing."""
    from book_scraper.db.repo import upsert_discovered_url

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/a",
            normalized_url="https://vaga.lt/a",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", sample_shop_config, rescrape=True)

    # Simulate the pipeline discovering a new URL mid-run.
    new_du = upsert_discovered_url(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/brand-new",
        source="product_page",
        run_id=plan.run_id,
    )
    service.enqueue_new_url(
        run_id=plan.run_id,
        shop_id=shop.id,
        discovered_url_id=new_du.id,
        url=new_du.url,
    )

    pending = (
        db_session.query(ScrapeUrlItem)
        .filter_by(run_id=plan.run_id, status="pending")
        .all()
    )
    assert {p.url for p in pending} == {
        "https://vaga.lt/a",
        "https://vaga.lt/brand-new",
    }
```

- [ ] **Step 7: Run the new test to verify it passes**

Run: `uv run pytest tests/integration/test_scan_second_pass.py -v`
Expected: PASS (both tests in the file).

- [ ] **Step 8: Store scan-run context on the pipeline**

Open `book_scraper/pipelines.py`. Find `PostgresPipeline.open_spider` (near the top of the `PostgresPipeline` class). Add these lines at the end of `open_spider`:

```python
self._scan_run_id: int | None = (
    getattr(spider, "_run_id", None)
    if getattr(spider, "name", "") == "scan"
    else None
)
self._rescrape: bool = bool(getattr(spider, "_rescrape", False))
```

This lets the pipeline know, on each item, whether the current run is a scan rescrape. No signature changes to `upsert_discovered_url` — `insert_scrape_url_item`'s idempotency handles duplicates.

- [ ] **Step 9: Hook the pipeline to queue newly-discovered URLs during rescrape**

In `book_scraper/pipelines.py`, find the call to `upsert_discovered_url` at line 590 (inside the branch that handles `DiscoveredUrlItem` / shop_book discovery). Directly **after** that call, add:

```python
if self._scan_run_id is not None and self._rescrape:
    from book_scraper.services.scan import ScanService

    ScanService(self.session).enqueue_new_url(
        run_id=self._scan_run_id,
        shop_id=shop_id,
        discovered_url_id=record.id,
        url=record.url,
        url_type=record.url_type or "product",
    )
```

Replace `record` with whatever variable name the current code assigns the `upsert_discovered_url` return value to (read the surrounding lines first to confirm).

Note: `insert_scrape_url_item` is idempotent by `(run_id, url)`, so if the URL is already queued (pending or done), this is a no-op.

- [ ] **Step 10: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step 11: Modify the scan spider to yield follow-up requests after main batch**

In `book_scraper/spiders/scan.py`, the current `start()` yields all pending items once then exits. For second-pass, after the main yield loop, add a check-and-yield loop driven by the `spider_idle` signal — but simpler: since new URLs are enqueued by the pipeline during processing, and the spider is awaiting responses in the reactor, we can instead hook into `spider_idle` to fetch fresh pending items and schedule them.

Add at the top of `scan.py`:

```python
from scrapy import signals
```

In the `ScanSpider` class, add:

```python
@classmethod
def from_crawler(cls, crawler, *args, **kwargs):
    spider = super().from_crawler(crawler, *args, **kwargs)
    crawler.signals.connect(spider.spider_idle, signal=signals.spider_idle)
    return spider

def spider_idle(self, spider) -> None:
    """When the main queue drains, check for new items queued mid-run
    and schedule them. Called by Scrapy when no requests are in flight."""
    if self._run_id is None:
        return
    database_url = self.settings.get("DATABASE_URL")
    session_factory = get_session_factory(database_url)
    session = session_factory()
    try:
        reset_processing_scrape_url_items(session, self._run_id)
        new_items = get_pending_scrape_url_items(session, self._run_id)
        session.commit()
    finally:
        session.close()

    if not new_items:
        return

    from scrapy.exceptions import DontCloseSpider

    for item in new_items:
        req = scrapy.Request(
            item["url"],
            callback=self.parse_product,
            errback=self.handle_error,
            meta={
                "discovered_url_id": item["discovered_url_id"],
                "scrape_url_item_id": item["id"],
            },
        )
        self.crawler.engine.crawl(req)
    raise DontCloseSpider
```

- [ ] **Step 12: Write an end-to-end second-pass test with a fake response**

Append to `tests/integration/test_scan_second_pass.py`:

```python
def test_spider_yields_followup_requests_for_queued_urls(db_session, sample_shop_config):
    """spider_idle picks up items added mid-run and schedules them."""
    from book_scraper.db.repo import insert_scrape_url_item

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/a",
            normalized_url="https://vaga.lt/a",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", sample_shop_config, rescrape=True)

    # Simulate new URL added mid-run, before any processing.
    insert_scrape_url_item(
        db_session,
        run_id=plan.run_id,
        shop_id=shop.id,
        discovered_url_id=None,
        url="https://vaga.lt/mid-run",
        url_type="product",
    )
    db_session.commit()

    # Query shows both pending.
    from book_scraper.db.repo import get_pending_scrape_url_items

    items = get_pending_scrape_url_items(db_session, plan.run_id)
    assert len(items) == 2
    assert any(i["url"] == "https://vaga.lt/mid-run" for i in items)
```

- [ ] **Step 13: Run the test to verify it passes**

Run: `uv run pytest tests/integration/test_scan_second_pass.py -v`
Expected: all three tests pass.

- [ ] **Step 14: Run the full test suite and lint**

```bash
uv run pytest tests/ -v
uv run ruff check book_scraper/ tests/
uv run mypy book_scraper/
```

Expected: all green.

- [ ] **Step 15: Commit**

```bash
git add book_scraper/db/repo.py book_scraper/services/scan.py book_scraper/spiders/scan.py book_scraper/pipelines.py tests/integration/test_scan_second_pass.py
git commit -m "feat(scrape-queue): second-pass new URLs discovered mid-rescrape"
```

---

## Task 5: End-to-end smoke test against real scraper container

**Files:**
- No new files. Follow CLAUDE.md post-task checklist.

- [ ] **Step 1: Rebuild scraper + dashboard images**

```bash
docker compose build dashboard scraper
docker compose up -d dashboard scraper
```

- [ ] **Step 2: Run dashboard integration smoke tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all routes return 200.

- [ ] **Step 3: Trigger a short scan to confirm the scraper container picked up the new models**

```bash
docker compose exec scraper /app/.venv/bin/python -m scrapy crawl scan -a shop=vaga -a max_urls=3 -a rescrape=true
```

Expected: no `column does not exist` errors. Spider scrapes 3 URLs successfully. Run is marked completed. `docker compose exec -e PGPASSWORD=postgres postgres psql -U postgres -d book_scraper -c "SELECT count(*) FROM scrape_url_items;"` returns 0 (staging rows deleted).

- [ ] **Step 4: Trigger a second scan to confirm resume-or-new logic**

Interrupt the previous scan mid-run (if it's a big set; skip for 3-URL test). Then:

```bash
docker compose exec scraper /app/.venv/bin/python -m scrapy crawl scan -a shop=vaga -a max_urls=3 -a rescrape=true
```

Expected: a fresh run created (no pending items remain from the previous run because cleanup ran). If a run was interrupted with pending items, the second call should reuse its run_id.

- [ ] **Step 5: Commit final state (no code changes, but ensures CI is clean)**

If steps 1–4 exposed any bug, fix it and add a regression test. Otherwise skip to the next task or wrap up.

---

## Deferred (separate plan)

The following items from the Notion spec are **not** covered by this plan and need a follow-up plan:

1. **Extend `scrape_url_items` to all discover spiders.** Currently `discover_sitemap`, `discover_categories`, `discover_full_crawl` don't use the queue. Making them use it requires reworking each spider's `start` method and the prepare logic per strategy. Large refactor.
2. **Maximize data extraction** — `discover_categories` yielding `ShopBookItem` with title/author/image; `discover_full_crawl` calling `parse_product_page` on product pages. Separate Notion task.
3. **Dashboard cron management UI.** Separate Notion task.
