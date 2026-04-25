# scrape_url_items Phase 2 — Extend Queue to Discover Spiders

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Make `discover_sitemap`, `discover_categories`, and `discover_full_crawl` use the `scrape_url_items` staging queue (Phase 1 only wired this for `scan`). Each discover run gets crash-resumable and dynamically growable via the queue.

**Architecture:** A new `DiscoverService` with `prepare_discover(strategy)` that seeds the queue with the strategy's starting URL(s). The discover spider reads pending items from the queue at start, yields Scrapy Requests dispatched by `url_type`, and callbacks dual-write: they yield new Scrapy Requests (same as today) AND insert new items into `scrape_url_items` for durability. On completion, the queue's cleanup (Phase 1) deletes staging rows. On crash, `find_resumable_run` picks up the orphaned run and the spider re-reads pending items.

**Tech Stack:** Python 3.12, Scrapy, SQLAlchemy 2.0, pytest integration tests on real Postgres (port 5433).

---

## File Structure

**Created:**
- `book_scraper/services/discover.py` — new `DiscoverService` with `prepare_discover`, `finish_discover`
- `tests/integration/test_discover_service.py` — unit/integration tests for the service
- `tests/integration/test_discover_queue_e2e.py` — end-to-end test using a mocked response

**Modified:**
- `book_scraper/spiders/discover.py` — `start()` consumes queue, callbacks dual-write, `closed()` calls cleanup + last_run_at
- `book_scraper/db/repo.py` — extend `find_resumable_run` to accept any phase string (it currently hardcodes `"scan"` in the docstring but the parameter is already there; confirm and document)

**Unchanged (from Phase 1):**
- `scrape_url_items` table — schema is already flexible (Text `url_type`)
- `insert_scrape_url_item`, `cleanup_scrape_url_items`, `get_pending_scrape_url_items`, `reset_processing_scrape_url_items` — all reused
- `find_resumable_run` — already takes `phase` param; we'll pass `f"discover_{strategy}"`

---

## url_type vocabulary for this phase

- `"sitemap"` — XML sitemap URL, parsed by `parse_sitemap`
- `"category_page"` — HTML category listing page, parsed by `parse_categories`
- `"crawl"` — unknown HTML page, parsed by `parse_full_crawl` (extracts internal links)
- `"product"` — product detail page (inherited from Phase 1 default; full_crawl uses it when it lands on a detected product URL)

The column is plain `Text`, so no schema change needed.

---

## Task 1: `DiscoverService.prepare_discover` + seed into queue

**Files:**
- Create: `book_scraper/services/discover.py`
- Create: `tests/integration/test_discover_service.py`

### Step 1 — Write failing service tests

Create `tests/integration/test_discover_service.py`:

```python
"""DiscoverService: prepare_discover seeds scrape_url_items per strategy."""

from types import SimpleNamespace

from book_scraper.db.models import ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import upsert_shop
from book_scraper.services.discover import DiscoverService


def _config(sitemap_url="https://vaga.lt/sitemap.xml",
            categories_url="https://vaga.lt/knygos?page={page}",
            full_crawl_start_url="https://vaga.lt/"):
    return SimpleNamespace(
        discover=SimpleNamespace(
            sitemap=SimpleNamespace(url=sitemap_url),
            categories=SimpleNamespace(url=categories_url),
            full_crawl=SimpleNamespace(start_url=full_crawl_start_url),
        )
    )


def test_prepare_discover_sitemap_seeds_one_item(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    assert items[0].url == "https://vaga.lt/sitemap.xml"
    assert items[0].url_type == "sitemap"
    assert items[0].status == "pending"

    run = db_session.get(ScrapeRun, plan.run_id)
    assert run.phase == "discover_sitemap"
    assert run.status == "running"


def test_prepare_discover_categories_seeds_page_one(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "categories", _config())

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    assert "page=1" in items[0].url
    assert items[0].url_type == "category_page"


def test_prepare_discover_full_crawl_seeds_start_url(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "full_crawl", _config())

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    assert items[0].url == "https://vaga.lt/"
    assert items[0].url_type == "crawl"


def test_prepare_discover_resumes_running_run_with_pending_items(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    first = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())

    second = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())
    assert second.run_id == first.run_id  # resumed, not new


def test_finish_discover_deletes_staging_rows(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 1

    service.finish_discover(plan.run_id, urls_processed=1, reason="finished")
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 0
```

### Step 2 — Run, verify fail

`uv run pytest tests/integration/test_discover_service.py -v`
Expected: 5 failures on `ModuleNotFoundError`.

### Step 3 — Create `DiscoverService`

Create `book_scraper/services/discover.py`:

```python
"""DiscoverService: owns prepare + finish for the three discover strategies.

Analogous to ScanService. Seeds scrape_url_items with strategy-specific
starting URLs; the discover spider consumes the queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from book_scraper.db.models import ScrapeUrlItem
from book_scraper.db.repo import (
    cleanup_scrape_url_items,
    create_scrape_run,
    find_resumable_run,
    finish_scrape_run,
    insert_scrape_url_item,
    mark_cron_job_ran_if_matches,
    mark_stale_runs_failed,
    update_scrape_run_progress,
    upsert_shop,
)


_STRATEGY_URL_TYPE = {
    "sitemap": "sitemap",
    "categories": "category_page",
    "full_crawl": "crawl",
}


@dataclass
class DiscoverPlan:
    run_id: int
    urls_total: int
    freshness_warnings: list[str] = field(default_factory=list)


class DiscoverService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def prepare_discover(
        self,
        shop_name: str,
        base_url: str,
        strategy: str,
        shop_config: Any,
    ) -> DiscoverPlan:
        """Prepare a discover run for the given strategy.

        Resume an existing running run with pending items if one exists;
        otherwise create a new run and seed the queue with the strategy's
        starting URL.
        """
        if strategy not in _STRATEGY_URL_TYPE:
            raise ValueError(f"Unknown discover strategy: {strategy}")
        phase = f"discover_{strategy}"

        shop = upsert_shop(self.session, shop_name, base_url)

        resumable = find_resumable_run(self.session, shop.id, phase)
        if resumable is not None:
            pending = (
                self.session.query(ScrapeUrlItem)
                .filter_by(run_id=resumable.id, status="pending")
                .count()
            )
            return DiscoverPlan(run_id=resumable.id, urls_total=pending)

        mark_stale_runs_failed(self.session, shop.id, phase)

        run = create_scrape_run(self.session, shop.id, phase)

        seed_url = self._seed_url(strategy, shop_config)
        url_type = _STRATEGY_URL_TYPE[strategy]
        insert_scrape_url_item(
            self.session,
            run_id=run.id,
            shop_id=shop.id,
            discovered_url_id=None,
            url=seed_url,
            url_type=url_type,
        )
        self.session.commit()

        return DiscoverPlan(run_id=run.id, urls_total=1)

    @staticmethod
    def _seed_url(strategy: str, shop_config: Any) -> str:
        discover_cfg = (
            shop_config.discover
            if hasattr(shop_config, "discover")
            else shop_config["discover"]
        )
        if strategy == "sitemap":
            return (
                discover_cfg.sitemap.url
                if hasattr(discover_cfg, "sitemap")
                else discover_cfg["sitemap"]["url"]
            )
        if strategy == "categories":
            tmpl = (
                discover_cfg.categories.url
                if hasattr(discover_cfg, "categories")
                else discover_cfg["categories"]["url"]
            )
            return tmpl.format(page=1)
        if strategy == "full_crawl":
            return (
                discover_cfg.full_crawl.start_url
                if hasattr(discover_cfg, "full_crawl")
                else discover_cfg["full_crawl"]["start_url"]
            )
        raise ValueError(f"Unknown strategy: {strategy}")

    def finish_discover(
        self,
        run_id: int,
        urls_processed: int,
        reason: str,
    ) -> None:
        """Mark run completed/failed, update last_run_at on matching cron_job,
        delete staging rows."""
        from book_scraper.db.models import ScrapeRun

        status = "completed" if reason == "finished" else "failed"
        update_scrape_run_progress(self.session, run_id, urls_processed)
        finish_scrape_run(self.session, run_id, status)

        run_row = self.session.get(ScrapeRun, run_id)
        if run_row is not None:
            # Extract strategy from phase "discover_<strategy>"
            strategy = run_row.phase.removeprefix("discover_") if run_row.phase.startswith("discover_") else None
            mark_cron_job_ran_if_matches(
                self.session, run_row.shop_id, phase="discover", strategy=strategy
            )

        cleanup_scrape_url_items(self.session, run_id)
        self.session.commit()
```

### Step 4 — Run tests, verify PASS

`uv run pytest tests/integration/test_discover_service.py -v`
Expected: 5 PASS.

### Step 5 — Run full suite

`uv run pytest tests/ -v` — 356+ tests pass.

### Step 6 — Commit

```bash
git add book_scraper/services/discover.py tests/integration/test_discover_service.py
git commit -m "feat(scrape-queue): add DiscoverService for prepare/finish via queue"
```

---

## Task 2: Refactor discover spider to consume the queue

**Files:**
- Modify: `book_scraper/spiders/discover.py`
- Create: `tests/integration/test_discover_queue_e2e.py` (end-to-end with mocked responses)

### Step 1 — Read the current discover spider

`book_scraper/spiders/discover.py` currently:
- `__init__` — accepts `shop`, `strategy`, `max_pages`; loads config and parsers
- `start()` — creates a run directly (not via service), yields ONE Request for the strategy's seed URL based on `self.strategy`
- `parse_sitemap` — yields `DiscoveredUrlItem` for each URL in sitemap
- `parse_categories` — yields `DiscoveredUrlItem`, `ShopBookItem`, and paginating `Request`
- `parse_full_crawl` — yields `DiscoveredUrlItem`, `ShopBookItem`, and following `Request`
- `closed()` — finishes the run

Read the file to confirm the exact method shapes and imports before editing.

### Step 2 — Refactor `start()` to use DiscoverService + queue

Replace the existing `start()` method. The new flow:

1. Open a session.
2. Call `DiscoverService(session).prepare_discover(...)` — this either creates a new run + seeds queue, or returns a resumable run_id.
3. Call `reset_processing_scrape_url_items(session, run_id)` (Phase 1 helper) in case of crash recovery.
4. Call `get_pending_scrape_url_items(session, run_id)` — returns `[{id, url, discovered_url_id, ...}]`. **You need to extend this helper to also return `url_type`** — see Step 2a below.
5. For each item, yield a Request with callback=`self.dispatch` and `meta={"scrape_url_item_id": item["id"], "url_type": item["url_type"]}`.
6. Store `self._run_id = plan.run_id`.

### Step 2a — Extend `get_pending_scrape_url_items` to include `url_type`

In `book_scraper/db/repo.py`, find `get_pending_scrape_url_items`. Add `url_type` to the dict:

```python
return [
    {
        "id": r.id,
        "url": r.url,
        "url_type": r.url_type,
        "discovered_url_id": r.discovered_url_id,
    }
    for r in rows
]
```

Check callers — the scan spider already uses this helper. Adding a key is backwards-compatible (scan spider just ignores `url_type`).

### Step 3 — Add a dispatch method

```python
def dispatch(self, response: scrapy.http.Response):
    """Route a downloaded response to the correct parser based on url_type."""
    url_type = response.meta.get("url_type", "crawl")
    if url_type == "sitemap":
        yield from self.parse_sitemap(response)
    elif url_type == "category_page":
        yield from self.parse_categories(response)
    elif url_type == "product":
        yield from self.parse_product(response)  # may not exist yet — see Step 3a
    else:  # "crawl" or unknown
        yield from self.parse_full_crawl(response)

    # Mark the queue item done.
    item_id = response.meta.get("scrape_url_item_id")
    if item_id is not None and self._run_id is not None:
        database_url = self.settings.get("DATABASE_URL")
        factory = get_session_factory(database_url)
        with factory() as s:
            mark_scrape_url_item_done(s, item_id)
            s.commit()
```

### Step 3a — Optional: parse_product for full_crawl's product-page case

If `parse_full_crawl` currently detects a product URL and calls `parse_product_page`, extract that into a helper method `parse_product(response)` so `dispatch` can route to it. If not, skip this step.

### Step 4 — Refactor callbacks to dual-write to queue

In `parse_categories`, find the line that yields the next-page request (currently `yield scrapy.Request(next_url, callback=self.parse_categories, ...)`). Replace with:

```python
from book_scraper.db.repo import insert_scrape_url_item

# Dual-write: insert into queue for durability, yield Request for immediate processing.
database_url = self.settings.get("DATABASE_URL")
factory = get_session_factory(database_url)
with factory() as s:
    item = insert_scrape_url_item(
        s, run_id=self._run_id, shop_id=self._shop_id,
        discovered_url_id=None, url=next_url, url_type="category_page",
    )
    s.commit()
    new_item_id = item.id
yield scrapy.Request(
    next_url,
    callback=self.dispatch,
    errback=self.handle_start_error,
    meta={"page": page, "scrape_url_item_id": new_item_id, "url_type": "category_page"},
)
```

`self._shop_id` needs to be set in `__init__` or `start()`. The current code probably has `self.shop_name` but not `self._shop_id`. Add it when you create the run (in `start()`, after `upsert_shop` — you'll already have the shop object from the service call).

Actually: `DiscoverService.prepare_discover` internally calls `upsert_shop`. You need the shop_id afterward. Extend `DiscoverPlan` to include `shop_id` too, or make DiscoverService expose it via `plan.shop_id`. Simplest: add `shop_id: int` to `DiscoverPlan` and populate it in `prepare_discover`.

In `parse_full_crawl`, do the same dual-write for internal links. Determine `url_type` at enqueue time:
- If the URL matches the product-URL filter pattern → `url_type="product"` (these will route to parse_product)
- Otherwise → `url_type="crawl"`

In `parse_sitemap` — this one DOESN'T enqueue URLs into scrape_url_items. The sitemap finds product URLs which go to `discovered_urls` only. The sitemap discover run processes exactly one URL (the sitemap itself). So no dual-write here.

### Step 5 — Update `closed()` to use service

Replace the existing run-finalization logic in `closed(reason)` with:

```python
if self._run_id is None:
    return
database_url = self.settings.get("DATABASE_URL")
factory = get_session_factory(database_url)
with factory() as s:
    DiscoverService(s).finish_discover(self._run_id, self._urls_processed, reason)
```

Keep any error-stat tracking you currently have — merge it with the above.

### Step 6 — Add spider_idle hook (same pattern as scan spider)

Mirror `scan.py`'s `spider_idle`:

```python
@classmethod
def from_crawler(cls, crawler, *args, **kwargs):
    spider = super().from_crawler(crawler, *args, **kwargs)
    crawler.signals.connect(spider.spider_idle, signal=signals.spider_idle)
    return spider

def spider_idle(self, spider):
    if self._run_id is None:
        return
    from scrapy.exceptions import DontCloseSpider

    database_url = self.settings.get("DATABASE_URL")
    factory = get_session_factory(database_url)
    with factory() as s:
        reset_processing_scrape_url_items(s, self._run_id)
        new_items = get_pending_scrape_url_items(s, self._run_id)
        s.commit()

    if not new_items:
        return

    for item in new_items:
        req = scrapy.Request(
            item["url"],
            callback=self.dispatch,
            errback=self.handle_start_error,
            meta={
                "scrape_url_item_id": item["id"],
                "url_type": item["url_type"],
            },
        )
        engine = self.crawler.engine
        assert engine is not None
        engine.crawl(req)
    raise DontCloseSpider
```

### Step 7 — E2E integration test

Create `tests/integration/test_discover_queue_e2e.py`:

```python
"""End-to-end: prepare_discover seeds queue, spider consumes, cleanup fires."""

from book_scraper.db.models import DiscoveredUrl, ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import upsert_shop
from book_scraper.services.discover import DiscoverService


def _config():
    from types import SimpleNamespace
    return SimpleNamespace(
        discover=SimpleNamespace(
            sitemap=SimpleNamespace(url="https://vaga.lt/sitemap.xml"),
            categories=SimpleNamespace(url="https://vaga.lt/p?page={page}"),
            full_crawl=SimpleNamespace(start_url="https://vaga.lt/"),
        )
    )


def test_finish_discover_marks_last_run_and_cleans_up(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    # Simulate an enabled cron_job so last_run_at tracking fires.
    from book_scraper.db.repo import create_cron_job, get_cron_job
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *", enabled=True,
    )
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 1

    service.finish_discover(plan.run_id, urls_processed=1, reason="finished")

    db_session.expire_all()
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 0
    assert db_session.get(ScrapeRun, plan.run_id).status == "completed"
    assert get_cron_job(db_session, job.id).last_run_at is not None
```

### Step 8 — Run tests + smoke

```bash
uv run pytest tests/integration/test_discover_service.py tests/integration/test_discover_queue_e2e.py -v
uv run pytest tests/ -v
docker compose build scraper
docker compose up -d scraper
sleep 3
# Trigger a sitemap discover run via "Run now" in dashboard, then:
docker compose exec -e PGPASSWORD=postgres postgres psql -U postgres -d book_scraper \
  -c "SELECT run_id, url, url_type, status FROM scrape_url_items ORDER BY id DESC LIMIT 5;"
```

### Step 9 — Commit

```bash
git add book_scraper/spiders/discover.py book_scraper/db/repo.py book_scraper/services/discover.py tests/integration/test_discover_queue_e2e.py
git commit -m "feat(scrape-queue): discover spider consumes scrape_url_items"
```

---

## Deferred

- Normalized URL deduplication in `insert_scrape_url_item` (Phase 1 known gap)
- DB `UniqueConstraint(run_id, url)` + `INSERT ON CONFLICT DO NOTHING`
- Dashboard view showing queue depth per running run (nice-to-have for ops visibility)
