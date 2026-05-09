"""Integration coverage for end-of-run retry helpers."""

import pytest

from book_scraper.db.models import ScrapeUrlItem
from book_scraper.db.repo import (
    create_scrape_run,
    fetch_retryable_failed_items,
    insert_scrape_url_item,
    reset_failed_items_to_pending,
    upsert_shop,
)


def _seed_run_with_items(session, attempts_per_status):
    """attempts_per_status: list of (status, attempts) tuples."""
    shop = upsert_shop(session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(session, shop.id, "scan")
    items = []
    for i, (status, attempts) in enumerate(attempts_per_status):
        item = insert_scrape_url_item(
            session,
            run_id=run.id,
            shop_id=shop.id,
            discovered_url_id=None,
            url=f"https://www.vaga.lt/p/{i}",
            url_type="product",
        )
        item.status = status
        item.attempts = attempts
        items.append(item)
    session.flush()
    session.commit()
    return run, items


def test_fetch_retryable_failed_items_excludes_capped(db_session):
    run, items = _seed_run_with_items(
        db_session,
        [
            ("failed", 0),
            ("failed", 1),
            ("failed", 2),
            ("failed", 3),  # capped
            ("done", 1),
            ("pending", 0),
        ],
    )

    eligible = fetch_retryable_failed_items(db_session, run.id, cap=3)

    eligible_ids = {item.id for item in eligible}
    assert eligible_ids == {items[0].id, items[1].id, items[2].id}


def test_fetch_retryable_failed_items_only_current_run(db_session):
    run_a, items_a = _seed_run_with_items(db_session, [("failed", 1)])
    run_b, items_b = _seed_run_with_items(db_session, [("failed", 1)])

    eligible_a = fetch_retryable_failed_items(db_session, run_a.id, cap=3)
    assert {item.id for item in eligible_a} == {items_a[0].id}


def test_reset_failed_items_to_pending_default_keeps_attempts(db_session):
    run, items = _seed_run_with_items(
        db_session,
        [
            ("failed", 1),
            ("failed", 2),
        ],
    )

    reset_failed_items_to_pending(db_session, [items[0].id, items[1].id])
    db_session.commit()

    refreshed = [db_session.get(ScrapeUrlItem, item.id) for item in items]
    assert all(item.status == "pending" for item in refreshed)
    assert refreshed[0].attempts == 1  # untouched
    assert refreshed[1].attempts == 2  # untouched


def test_reset_failed_items_to_pending_with_attempts_reset(db_session):
    """Operator-triggered Retry-failures path resets attempts to 0."""
    run, items = _seed_run_with_items(
        db_session,
        [
            ("failed", 3),  # capped
        ],
    )

    reset_failed_items_to_pending(db_session, [items[0].id], reset_attempts=True)
    db_session.commit()

    refreshed = db_session.get(ScrapeUrlItem, items[0].id)
    assert refreshed.status == "pending"
    assert refreshed.attempts == 0


def test_mark_processing_increments_attempts(db_session):
    import time

    from book_scraper.db.repo import mark_scrape_url_item_processing

    run, items = _seed_run_with_items(db_session, [("pending", 0)])
    db_session.get(type(items[0]), items[0].id)  # ensure attached

    # Run must be 'running' for mark_scrape_url_item_processing to apply.
    run.status = "running"
    db_session.commit()

    mark_scrape_url_item_processing(db_session, items[0].id, time.time())
    db_session.commit()

    refreshed = db_session.get(type(items[0]), items[0].id)
    assert refreshed.status == "processing"
    assert refreshed.attempts == 1


def test_mark_processing_increments_attempts_on_redispatch(db_session):
    import time

    from book_scraper.db.repo import mark_scrape_url_item_processing

    run, items = _seed_run_with_items(db_session, [("pending", 1)])
    run.status = "running"
    db_session.commit()

    mark_scrape_url_item_processing(db_session, items[0].id, time.time())
    db_session.commit()

    refreshed = db_session.get(type(items[0]), items[0].id)
    assert refreshed.attempts == 2


def test_scan_spider_idle_resets_failed_below_cap_to_pending(engine):
    """Until the sweep flag is set, idle should reset failed-and-eligible
    items to pending and reschedule them. After the sweep flag is set,
    further idle ticks no-op for the retry path.

    Bypasses the rollback-isolated db_session fixture: spider_idle opens
    its own connection via get_session_factory and won't see uncommitted
    fixture data.
    """
    from unittest.mock import MagicMock

    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from book_scraper.db.models import ScrapeUrlItem
    from book_scraper.db.repo import (
        create_scrape_run,
        insert_scrape_url_item,
        upsert_shop,
    )
    from book_scraper.spiders.scan import ScanSpider
    from tests.conftest import TEST_DATABASE_URL

    session_factory = sessionmaker(bind=engine)
    setup = session_factory()
    try:
        shop = upsert_shop(setup, "vaga_idle_retry", "https://www.vaga.lt")
        run = create_scrape_run(setup, shop.id, "scan")
        run.status = "running"
        item = insert_scrape_url_item(
            setup, run_id=run.id, shop_id=shop.id, discovered_url_id=None,
            url="https://www.vaga.lt/p/idle-retry-1", url_type="product",
        )
        item.status = "failed"
        item.attempts = 1
        setup.commit()
        run_id = run.id
        shop_id = shop.id
        item_id = item.id
    finally:
        setup.close()

    try:
        spider = ScanSpider.__new__(ScanSpider)  # bypass __init__
        spider._run_id = run_id
        spider._end_of_run_retry_done = False
        spider.settings = MagicMock()
        spider.settings.get = lambda k, default=None: {
            "DATABASE_URL": TEST_DATABASE_URL,
            "RETRY_CAP": 3,
        }.get(k, default)
        spider.settings.getint = lambda k, default=None: 3
        spider.crawler = MagicMock()
        spider.crawler.engine = MagicMock()
        spider._build_scan_request = MagicMock(return_value=MagicMock())

        from scrapy.exceptions import DontCloseSpider
        with pytest.raises(DontCloseSpider):
            spider.spider_idle(spider)

        verify = session_factory()
        try:
            refreshed = verify.get(ScrapeUrlItem, item_id)
            assert refreshed is not None
            assert refreshed.status == "pending"
        finally:
            verify.close()
        assert spider._end_of_run_retry_done is True

        # Second idle tick: no-op (no fresh pending items, sweep done).
        # Simulate retry pass landed and failed by flipping back to failed.
        flip = session_factory()
        try:
            flipped = flip.get(ScrapeUrlItem, item_id)
            assert flipped is not None
            flipped.status = "failed"
            flipped.attempts = 2
            flip.commit()
        finally:
            flip.close()

        # spider_idle should NOT raise — sweep already done, no other pending.
        result = spider.spider_idle(spider)
        assert result is None
    finally:
        cleanup = session_factory()
        try:
            cleanup.execute(
                text("DELETE FROM scrape_url_items WHERE run_id = :id"),
                {"id": run_id},
            )
            cleanup.execute(
                text("DELETE FROM scrape_run_events WHERE run_id = :id"),
                {"id": run_id},
            )
            cleanup.execute(
                text("DELETE FROM scrape_runs WHERE id = :id"),
                {"id": run_id},
            )
            cleanup.execute(
                text("DELETE FROM shops WHERE id = :id"),
                {"id": shop_id},
            )
            cleanup.commit()
        finally:
            cleanup.close()
