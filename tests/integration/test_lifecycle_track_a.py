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
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import sessionmaker

from book_scraper.dashboard.queries import DEAD_RUN_SECONDS, mark_stale_runs
from book_scraper.db.models import DiscoveredUrl, ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import (
    create_scrape_run,
    find_resumable_run,
    finish_scrape_run,
    insert_scrape_url_item,
    mark_scrape_url_item_processing,
    mark_scrape_url_item_response,
    sweep_orphaned_processing_items,
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


def test_engine_has_fail_fast_connect_args():
    """get_engine must bound how long any sync DB call can block the
    reactor thread. Without these guards, a hung psycopg2 call freezes
    the entire Twisted event loop — see runs 194/195 where heartbeat
    ticks AND the StallDetector both stopped firing for ~5 minutes
    while a sync write waited on a dead postgres connection.

    The guards in connect_args are the only defense for IN-FLIGHT
    queries; pool_pre_ping only checks at checkout. Test by intercepting
    create_engine to read the user-supplied connect_args dict directly
    (SQLAlchemy stores them as a closure on the connect creator, not as
    a public attribute, so an indirect intercept is the cleanest path).
    """
    from unittest.mock import patch

    captured: dict = {}

    def capture(url, **kwargs):
        captured.update(kwargs)
        # Return a stub — this test only verifies what get_engine passed.
        return MagicMock()

    with patch("book_scraper.db.session.create_engine", side_effect=capture):
        get_engine(TEST_DATABASE_URL)

    connect_args = captured.get("connect_args", {})

    # Bounded TCP handshake: a fresh connection can't hang forever.
    assert connect_args.get("connect_timeout") == 5

    # Server-side default statement_timeout: no individual query
    # blocks the reactor more than 10s. Code paths that legitimately
    # need longer (large upserts) opt in via SET LOCAL.
    options = connect_args.get("options", "")
    assert "statement_timeout=10000" in options
    assert "idle_in_transaction_session_timeout=300000" in options

    # TCP keepalives so a silently-dropped connection (NAT idle,
    # postgres restart, network blip) is detected in ~60s rather
    # than the kernel default of ~2 hours.
    assert connect_args.get("keepalives") == 1
    assert connect_args.get("keepalives_idle") == 30
    assert connect_args.get("keepalives_interval") == 10
    assert connect_args.get("keepalives_count") == 3


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
    SessionLocal = sessionmaker(bind=engine)  # noqa: N806
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
    SessionLocal = sessionmaker(bind=engine)  # noqa: N806
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
    assert len(marked) == 1
    assert run.status == "failed"
    assert run.resumable_after_failure is True
    assert run.finished_at is not None
    assert run.close_reason == "heartbeat_timeout"


def test_mark_stale_runs_leaves_fresh_runs_alone(db_session):
    """A run with a fresh heartbeat is not reaped."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    # Heartbeat is fresh (now()).
    db_session.commit()

    marked = mark_stale_runs(db_session)
    db_session.refresh(run)
    assert len(marked) == 0
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
    plan = service.prepare_scan_create_run("vaga", "https://vaga.lt", {}, rescrape=True)

    # Run row exists with a heartbeat...
    run = db_session.get(ScrapeRun, plan.run_id)
    assert run is not None
    assert run.status == "running"
    assert run.last_heartbeat is not None
    # ...but no queue rows have been inserted yet.
    queue_count = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count()
    assert queue_count == 0
    # The plan carries the deferred URL list.
    assert plan._urls_to_scrape is not None
    assert len(plan._urls_to_scrape) == 2

    # Phase 2 inserts the queue.
    service.populate_scan_queue(plan)
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 2


# ─────────────────────── #2 + #10 — queue inheritance ───────────────────────


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
    """End-to-end: a failed-but-resumable run is restarted in place (same row).

    Per docs/superpowers/specs/2026-05-09-restart-and-retry-design.md, auto-resume
    after a stall reuses the same scrape_runs row instead of spawning a new one.
    The queue stays attached to the row; status flips back to running and a
    `restarted` event is appended for audit.
    """
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/i1")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/i2")

    service = ScanService(db_session)
    first = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=first.run_id).count() == 2

    # Simulate stall-style reap: mark first run failed + resumable.
    first_run = db_session.get(ScrapeRun, first.run_id)
    first_run.status = "failed"
    first_run.finished_at = datetime.now(UTC)
    first_run.resumable_after_failure = True
    first_run.close_reason = "stall_timeout"
    db_session.commit()

    # Next prepare_scan: must reuse the same row (single-row restart).
    second = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)
    assert second.run_id == first.run_id

    # Pending items remain on the same run row.
    pending = (
        db_session.query(ScrapeUrlItem)
        .filter_by(run_id=first.run_id, status="pending")
        .count()
    )
    assert pending == 2

    # Row was flipped back to running and finished_at cleared.
    db_session.refresh(first_run)
    assert first_run.status == "running"
    assert first_run.finished_at is None

    # A `restarted` event was emitted for audit (attempt 1).
    from book_scraper.db.models import ScrapeRunEvent

    restart_events = (
        db_session.query(ScrapeRunEvent)
        .filter(
            ScrapeRunEvent.run_id == first.run_id,
            ScrapeRunEvent.event_type == "restarted",
        )
        .all()
    )
    assert len(restart_events) == 1


# ─────────────────────── #2 — abort_processing idempotency ───────────────────────


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


def test_mark_processing_no_ops_for_terminal_run(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/terminal-processing")
    du = (
        db_session.query(DiscoveredUrl)
        .filter_by(url="https://vaga.lt/terminal-processing")
        .one()
    )
    run = create_scrape_run(db_session, shop.id, "scan")
    finish_scrape_run(db_session, run.id, status="failed")
    item = insert_scrape_url_item(db_session, run.id, shop.id, du.id, du.url)
    db_session.commit()

    mark_scrape_url_item_processing(db_session, item.id, dispatched_at=123.0)

    db_session.refresh(item)
    assert item.status == "pending"
    assert item.claimed_at is None


def test_sweep_orphaned_processing_items_cleans_terminal_run(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/orphan-processing")
    du = (
        db_session.query(DiscoveredUrl)
        .filter_by(url="https://vaga.lt/orphan-processing")
        .one()
    )
    run = create_scrape_run(db_session, shop.id, "scan")
    finish_scrape_run(db_session, run.id, status="failed")
    item = insert_scrape_url_item(db_session, run.id, shop.id, du.id, du.url)
    item.status = "processing"
    item.done_at = None
    db_session.commit()

    cleaned = sweep_orphaned_processing_items(db_session)

    assert cleaned == 1
    db_session.refresh(item)
    assert item.status == "failed"
    assert item.done_at is not None
    # PR 3 of the scrape_failures migration: failure detail lives in
    # scrape_failures, not on the queue row.
    from book_scraper.db.models import ScrapeFailure

    failure = (
        db_session.query(ScrapeFailure)
        .filter(ScrapeFailure.scrape_url_item_id == item.id)
        .one()
    )
    assert failure.error_reason == "run_aborted"


def test_sweep_reaps_stuck_rows_on_running_run(db_session):
    """Per-row sweep: only stale processing rows on active runs are reaped."""
    from book_scraper.db.repo import STUCK_ROW_THRESHOLD_S

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/fresh-processing")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/stuck-processing")
    du_fresh = (
        db_session.query(DiscoveredUrl)
        .filter_by(url="https://vaga.lt/fresh-processing")
        .one()
    )
    du_stuck = (
        db_session.query(DiscoveredUrl)
        .filter_by(url="https://vaga.lt/stuck-processing")
        .one()
    )
    run = create_scrape_run(db_session, shop.id, "scan")
    # run defaults to status='running' — leave it that way.
    fresh = insert_scrape_url_item(
        db_session, run.id, shop.id, du_fresh.id, du_fresh.url
    )
    stuck = insert_scrape_url_item(
        db_session, run.id, shop.id, du_stuck.id, du_stuck.url
    )

    now = datetime.now(UTC)
    fresh.status = "processing"
    fresh.claimed_at = now
    stuck.status = "processing"
    stuck.claimed_at = now - timedelta(seconds=STUCK_ROW_THRESHOLD_S + 60)
    db_session.commit()

    cleaned = sweep_orphaned_processing_items(db_session)

    assert cleaned == 1
    db_session.refresh(fresh)
    db_session.refresh(stuck)
    assert fresh.status == "processing"
    assert fresh.done_at is None
    assert stuck.status == "failed"
    assert stuck.done_at is not None
    from book_scraper.db.models import ScrapeFailure

    stuck_failure = (
        db_session.query(ScrapeFailure)
        .filter(ScrapeFailure.scrape_url_item_id == stuck.id)
        .one()
    )
    assert stuck_failure.error_reason == "stuck_in_processing"


def test_sweep_reaps_stuck_rows_on_paused_run(db_session):
    """Paused runs are 'active' for sweep purposes — same per-row treatment."""
    from book_scraper.db.repo import STUCK_ROW_THRESHOLD_S

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id, "https://vaga.lt/paused-stuck")
    du = (
        db_session.query(DiscoveredUrl)
        .filter_by(url="https://vaga.lt/paused-stuck")
        .one()
    )
    run = create_scrape_run(db_session, shop.id, "scan")
    run.status = "paused"
    item = insert_scrape_url_item(db_session, run.id, shop.id, du.id, du.url)
    item.status = "processing"
    item.claimed_at = datetime.now(UTC) - timedelta(seconds=STUCK_ROW_THRESHOLD_S + 60)
    db_session.commit()

    cleaned = sweep_orphaned_processing_items(db_session)

    assert cleaned == 1
    db_session.refresh(item)
    assert item.status == "failed"
    from book_scraper.db.models import ScrapeFailure

    failure = (
        db_session.query(ScrapeFailure)
        .filter(ScrapeFailure.scrape_url_item_id == item.id)
        .one()
    )
    assert failure.error_reason == "stuck_in_processing"


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
