from book_scraper.db.models import ScrapeRun, Shop
from book_scraper.db.repo import (
    create_scrape_run,
    finalize_run_failsafe,
    finish_scrape_run,
    get_latest_completed_run,
    mark_orphan_runs_failed,
    mark_stale_runs_failed,
    update_scrape_run_progress,
)
from tests.conftest import TEST_DATABASE_URL


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
    finish_scrape_run(db_session, run_id=run.id, status="completed", reason="finished")
    db_session.refresh(run)
    assert run.status == "completed"
    assert run.finished_at is not None
    assert run.close_reason == "finished"


def test_finish_scrape_run_failed_persists_close_reason(db_session):
    """Failed runs record their close reason on the row itself, not just
    in the parallel validation_issues entry."""
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    run = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    finish_scrape_run(
        db_session, run_id=run.id, status="failed", reason="stall_timeout"
    )
    db_session.refresh(run)
    assert run.status == "failed"
    assert run.close_reason == "stall_timeout"


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
    # Out-of-band close paths must also stamp close_reason on the row.
    assert stale.close_reason == "stale_pre_scan"


def test_mark_stale_runs_failed_custom_reason(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    stale = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    db_session.flush()
    mark_stale_runs_failed(
        db_session, shop_id=shop.id, phase="scan", reason="manual_cleanup"
    )
    db_session.refresh(stale)
    assert stale.close_reason == "manual_cleanup"


def test_finalize_run_failsafe_swallows_errors():
    """Failsafe must never raise — its job is to be the belt-and-suspenders
    finalize that runs even when everything else has gone wrong. Calling
    it for a non-existent run_id exercises the no-op branch and verifies
    no exception escapes."""
    # No db_session fixture — the helper opens its own connection.
    finalize_run_failsafe(
        TEST_DATABASE_URL,
        run_id=999_999_999,
        status="failed",
        reason="nonexistent_run_test",
    )


def test_finalize_run_failsafe_persists_close_reason(engine):
    """End-to-end: helper opens a fresh session, finalizes the run,
    and persists close_reason where the next session can read it.

    Bypasses the rollback-isolated db_session fixture because the helper
    opens its own connection that won't see uncommitted fixture data.
    """
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine)
    setup = session_factory()
    try:
        shop = Shop(name="failsafe_test_shop", base_url="https://failsafe.lt")
        setup.add(shop)
        setup.flush()
        run = create_scrape_run(setup, shop_id=shop.id, phase="scan")
        setup.commit()
        run_id = run.id
        shop_id = shop.id
    finally:
        setup.close()

    try:
        finalize_run_failsafe(
            TEST_DATABASE_URL,
            run_id=run_id,
            status="failed",
            reason="poisoned_session_test",
            resumable_after_failure=True,
        )

        verify = session_factory()
        try:
            updated = verify.get(ScrapeRun, run_id)
            assert updated is not None
            assert updated.status == "failed"
            assert updated.close_reason == "poisoned_session_test"
            assert updated.resumable_after_failure is True
        finally:
            verify.close()
    finally:
        cleanup = session_factory()
        try:
            cleanup.execute(
                text("DELETE FROM validation_issues WHERE scrape_run_id = :id"),
                {"id": run_id},
            )
            cleanup.execute(
                text("DELETE FROM scrape_runs WHERE id = :id"), {"id": run_id}
            )
            cleanup.execute(text("DELETE FROM shops WHERE id = :id"), {"id": shop_id})
            cleanup.commit()
        finally:
            cleanup.close()


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
    assert orphan_scan.close_reason == "orphan_on_boot"
    assert orphan_discover.status == "failed"
    assert orphan_discover.finished_at is not None
    assert orphan_discover.close_reason == "orphan_on_boot"
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
