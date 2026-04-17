from book_scraper.db.models import Shop
from book_scraper.db.repo import (
    create_scrape_run,
    finish_scrape_run,
    get_latest_completed_run,
    mark_orphan_runs_failed,
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


def test_mark_orphan_runs_failed_spans_shops_and_phases(db_session):
    shop_a = Shop(name="shop_a", base_url="https://a.lt")
    shop_b = Shop(name="shop_b", base_url="https://b.lt")
    db_session.add_all([shop_a, shop_b])
    db_session.flush()

    orphan_scan = create_scrape_run(db_session, shop_id=shop_a.id, phase="scan")
    orphan_discover = create_scrape_run(
        db_session, shop_id=shop_b.id, phase="discover_sitemap"
    )
    completed = create_scrape_run(db_session, shop_id=shop_a.id, phase="scan")
    finish_scrape_run(db_session, run_id=completed.id, status="completed")
    db_session.flush()

    count = mark_orphan_runs_failed(db_session)
    assert count == 2

    db_session.refresh(orphan_scan)
    db_session.refresh(orphan_discover)
    db_session.refresh(completed)
    assert orphan_scan.status == "failed"
    assert orphan_scan.finished_at is not None
    assert orphan_discover.status == "failed"
    assert orphan_discover.finished_at is not None
    assert completed.status == "completed"


def test_mark_orphan_runs_failed_noop_when_none_running(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    run = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    finish_scrape_run(db_session, run_id=run.id, status="completed")
    db_session.flush()

    assert mark_orphan_runs_failed(db_session) == 0


def test_update_scrape_run_progress(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    run = create_scrape_run(db_session, shop_id=shop.id, phase="scan", urls_total=100)
    update_scrape_run_progress(db_session, run_id=run.id, urls_processed=50)
    db_session.refresh(run)
    assert run.urls_processed == 50
    assert run.urls_total == 100
