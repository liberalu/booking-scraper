"""Track A — Stability foundation lifecycle tests.

Covers the five Track A items:
  - #11: pool_pre_ping + pool_recycle on the engine
  - #15: heartbeat blackout fix (signal-emitted-early via two-phase API)
  - #16: advisory lock for concurrent scan-creation
  - #2:  reaper coupling + terminal-state guards + queue inheritance
  - #10: stall-detector flags resumable_after_failure (covered indirectly
        through the queue-inheritance path)
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from book_scraper.dashboard.queries import DEAD_RUN_SECONDS, mark_stale_runs
from book_scraper.db.models import DiscoveredUrl, ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import (
    create_scrape_run,
    find_resumable_run,
    inherit_pending_items,
    insert_scrape_url_item,
    mark_scrape_url_item_response,
    try_acquire_scan_lock,
    update_scrape_run_progress,
    upsert_shop,
)
from book_scraper.db.session import get_engine, get_session_factory
from book_scraper.services.scan import ScanService
from tests.conftest import TEST_DATABASE_URL


# ────────────────────────────── #11 ──────────────────────────────


def test_engine_has_pool_pre_ping_and_recycle():
    """get_engine must enable pool_pre_ping and pool_recycle."""
    engine = get_engine(TEST_DATABASE_URL)
    try:
        assert engine.pool._pre_ping is True
        assert engine.pool._recycle == 300
    finally:
        engine.dispose()


# ────────────────────────────── #16 ──────────────────────────────


def _seed_one_url(db_session, shop_id, url="https://vaga.lt/a"):
    db_session.add(
        DiscoveredUrl(
            shop_id=shop_id,
            url=url,
            normalized_url=url,
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()


def test_advisory_lock_blocks_concurrent_acquire(engine):
    """Two separate connections cannot both hold the (shop_id, 'scan') lock.

    Uses two raw connections rather than the transactional fixture
    because pg_try_advisory_xact_lock is reentrant within a single
    transaction — we need genuinely separate xacts to observe the lock.
    """
    SessionLocal = sessionmaker(bind=engine)
    s1 = SessionLocal()
    s2 = SessionLocal()
    try:
        shop = upsert_shop(s1, "lock_test_shop", "https://example.com")
        s1.commit()
        # First connection acquires.
        assert try_acquire_scan_lock(s1, shop.id, "scan") is True
        # Second connection cannot.
        assert try_acquire_scan_lock(s2, shop.id, "scan") is False
        # Release by ending xact on s1.
        s1.commit()
        # Now s2 can acquire.
        assert try_acquire_scan_lock(s2, shop.id, "scan") is True
        s2.commit()
    finally:
        # Cleanup the seeded shop. Matches by name; safe even if test ran
        # concurrently elsewhere (the name is unique to this test).
        from sqlalchemy import text

        s1.execute(text("DELETE FROM shops WHERE name = 'lock_test_shop'"))
        s1.commit()
        s1.close()
        s2.close()


def test_prepare_scan_returns_lock_not_acquired_when_locked(engine):
    """prepare_scan_create_run yields lock_not_acquired when another
    transaction holds the advisory lock for the same shop+phase."""
    SessionLocal = sessionmaker(bind=engine)
    holder = SessionLocal()
    contender = SessionLocal()
    try:
        shop = upsert_shop(holder, "lock_test_shop_2", "https://example.com")
        holder.commit()
        # Holder takes the lock — does NOT commit, so the lock stays held.
        assert try_acquire_scan_lock(holder, shop.id, "scan") is True

        service = ScanService(contender)
        plan = service.prepare_scan_create_run(
            "lock_test_shop_2", "https://example.com", {}, rescrape=True
        )
        assert plan.lock_not_acquired is True
        assert plan.run_id == 0
    finally:
        holder.rollback()
        contender.rollback()
        from sqlalchemy import text

        holder.execute(text("DELETE FROM shops WHERE name = 'lock_test_shop_2'"))
        holder.commit()
        holder.close()
        contender.close()


# ────────────────────────────── #2 ──────────────────────────────


def test_mark_stale_runs_uses_seconds_threshold(db_session):
    """A run with last_heartbeat older than DEAD_RUN_SECONDS is reaped."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    # Backdate the heartbeat past the threshold.
    run.last_heartbeat = datetime.now(UTC) - timedelta(seconds=DEAD_RUN_SECONDS + 30)
    db_session.commit()

    marked = mark_stale_runs(db_session)
    db_session.refresh(run)
    assert marked == 1
    assert run.status == "failed"
    assert run.resumable_after_failure is True
    assert run.finished_at is not None


def test_mark_stale_runs_leaves_fresh_runs_alone(db_session):
    """A run with a fresh heartbeat is not reaped."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    # Heartbeat is fresh (now()).
    db_session.commit()

    marked = mark_stale_runs(db_session)
    db_session.refresh(run)
    assert marked == 0
    assert run.status == "running"
    assert run.resumable_after_failure is False


def test_mark_response_skips_when_run_is_terminal(db_session):
    """Status guard: late writes against a reaped run are no-ops."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/x")
    du = db_session.query(DiscoveredUrl).filter_by(url="https://vaga.lt/x").one()
    run = create_scrape_run(db_session, shop.id, "scan")
    item = insert_scrape_url_item(db_session, run.id, shop.id, du.id, du.url)
    db_session.commit()

    # Reaper transitions the run to failed.
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    db_session.commit()

    # Late mark_response after the reap.
    mark_scrape_url_item_response(
        db_session,
        item.id,
        success=True,
        http_status=200,
        received_at=datetime.now(UTC).timestamp(),
        url_type="product",
    )
    db_session.refresh(item)
    # Item must remain in its pre-reap state.
    assert item.status == "pending"
    assert item.http_status is None


def test_update_progress_skips_when_run_is_terminal(db_session):
    """Status guard on update_scrape_run_progress: terminal runs are immutable."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()

    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    run.urls_processed = 7
    db_session.commit()

    update_scrape_run_progress(db_session, run.id, urls_processed=99)
    db_session.refresh(run)
    assert run.urls_processed == 7  # unchanged
    assert run.status == "failed"


# ────────────────────────────── #15 ──────────────────────────────


def test_create_run_phase_sets_heartbeat_before_queue(db_session):
    """prepare_scan_create_run commits the run row + heartbeat before
    populate_scan_queue runs. The heartbeat is fresh and the queue is empty."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/p1")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/p2")

    service = ScanService(db_session)
    plan = service.prepare_scan_create_run(
        "vaga", "https://vaga.lt", {}, rescrape=True
    )

    # Run row exists with a heartbeat...
    run = db_session.get(ScrapeRun, plan.run_id)
    assert run is not None
    assert run.status == "running"
    assert run.last_heartbeat is not None
    # ...but no queue rows have been inserted yet.
    queue_count = (
        db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count()
    )
    assert queue_count == 0
    # The plan carries the deferred URL list.
    assert plan._urls_to_scrape is not None
    assert len(plan._urls_to_scrape) == 2

    # Phase 2 inserts the queue.
    service.populate_scan_queue(plan)
    assert (
        db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 2
    )


# ────────────────────────────── #2 + #10 — queue inheritance ──────────────────────────────


def test_inherit_pending_items_repoints_run_id(db_session):
    """inherit_pending_items moves pending rows from old run to new run."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/q1")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/q2")
    du1 = db_session.query(DiscoveredUrl).filter_by(url="https://vaga.lt/q1").one()
    du2 = db_session.query(DiscoveredUrl).filter_by(url="https://vaga.lt/q2").one()

    old_run = create_scrape_run(db_session, shop.id, "scan")
    insert_scrape_url_item(db_session, old_run.id, shop.id, du1.id, du1.url)
    item2 = insert_scrape_url_item(
        db_session, old_run.id, shop.id, du2.id, du2.url
    )
    # Mark item2 done so only item1 is pending.
    item2.status = "done"
    item2.done_at = datetime.now(UTC)
    db_session.commit()

    new_run = create_scrape_run(db_session, shop.id, "scan")
    moved = inherit_pending_items(db_session, old_run.id, new_run.id)
    db_session.commit()

    assert moved == 1
    # Pending row moved to new run.
    new_pending = (
        db_session.query(ScrapeUrlItem)
        .filter_by(run_id=new_run.id, status="pending")
        .count()
    )
    assert new_pending == 1
    # Done row stays with the old run.
    old_done = (
        db_session.query(ScrapeUrlItem)
        .filter_by(run_id=old_run.id, status="done")
        .count()
    )
    assert old_done == 1


def test_find_resumable_run_picks_up_resumable_after_failure(db_session):
    """A failed run with resumable_after_failure=True is resumable."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/r1")
    du = db_session.query(DiscoveredUrl).filter_by(url="https://vaga.lt/r1").one()
    run = create_scrape_run(db_session, shop.id, "scan")
    insert_scrape_url_item(db_session, run.id, shop.id, du.id, du.url)
    db_session.commit()

    # Reaper-style transition.
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    run.resumable_after_failure = True
    db_session.commit()

    resumable = find_resumable_run(db_session, shop.id, "scan")
    assert resumable is not None
    assert resumable.id == run.id


def test_find_resumable_run_skips_failed_without_flag(db_session):
    """A failed run without resumable_after_failure is NOT resumable."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/r2")
    du = db_session.query(DiscoveredUrl).filter_by(url="https://vaga.lt/r2").one()
    run = create_scrape_run(db_session, shop.id, "scan")
    insert_scrape_url_item(db_session, run.id, shop.id, du.id, du.url)
    db_session.commit()

    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    # resumable_after_failure stays False (default).
    db_session.commit()

    resumable = find_resumable_run(db_session, shop.id, "scan")
    assert resumable is None


def test_prepare_scan_inherits_queue_from_resumable_failed_run(db_session):
    """End-to-end: a failed-but-resumable run's queue is adopted by a new run."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/i1")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/i2")

    service = ScanService(db_session)
    first = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)
    assert (
        db_session.query(ScrapeUrlItem).filter_by(run_id=first.run_id).count() == 2
    )

    # Simulate stall-style reap: mark first run failed + resumable.
    first_run = db_session.get(ScrapeRun, first.run_id)
    first_run.status = "failed"
    first_run.finished_at = datetime.now(UTC)
    first_run.resumable_after_failure = True
    db_session.commit()

    # Next prepare_scan: must spawn a new run row that adopts the queue.
    second = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)
    assert second.run_id != first.run_id

    # All pending items are now under the new run.
    moved = (
        db_session.query(ScrapeUrlItem)
        .filter_by(run_id=second.run_id, status="pending")
        .count()
    )
    assert moved == 2
    leftover = (
        db_session.query(ScrapeUrlItem)
        .filter_by(run_id=first.run_id, status="pending")
        .count()
    )
    assert leftover == 0

    # Old run row stays for postmortem.
    db_session.refresh(first_run)
    assert first_run.status == "failed"
    assert first_run.resumable_after_failure is True


# ────────────────────────────── #2 — abort_processing idempotency ──────────────────────────────


def test_abort_processing_skips_already_done_items(db_session):
    """abort_processing_scrape_url_items does not re-stamp done_at."""
    from book_scraper.db.repo import abort_processing_scrape_url_items

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/idem")
    du = db_session.query(DiscoveredUrl).filter_by(url="https://vaga.lt/idem").one()
    run = create_scrape_run(db_session, shop.id, "scan")
    item = insert_scrape_url_item(db_session, run.id, shop.id, du.id, du.url)
    db_session.commit()

    # First reaper pass aborts the processing row.
    item.status = "processing"
    db_session.commit()
    aborted_first = abort_processing_scrape_url_items(db_session, run.id)
    assert aborted_first == 1
    db_session.refresh(item)
    assert item.status == "failed"
    first_done_at = item.done_at
    assert first_done_at is not None

    # Second reaper pass against the same run: the row is no longer
    # `processing` AND has done_at set, so it's skipped.
    aborted_second = abort_processing_scrape_url_items(db_session, run.id)
    assert aborted_second == 0
    db_session.refresh(item)
    assert item.done_at == first_done_at  # unchanged


# ─────────────────────── pool_pre_ping smoke (best-effort) ───────────────────────


def test_session_factory_uses_configured_engine():
    """get_session_factory returns a sessionmaker bound to a pre-pinged engine."""
    factory = get_session_factory(TEST_DATABASE_URL)
    session = factory()
    try:
        # Round-trip a trivial query.
        from sqlalchemy import text

        result = session.execute(text("SELECT 1")).scalar()
        assert result == 1
        # Inspect the bound engine.
        bind = session.get_bind()
        assert bind.pool._pre_ping is True
        assert bind.pool._recycle == 300
    finally:
        session.close()


# Avoid an unused-import warning for `pytest` in some runners.
_ = pytest
