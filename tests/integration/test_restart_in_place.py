"""Integration coverage for restart_run_in_place — single-row mutation
on auto-resume / boot-reconcile paths."""

from datetime import UTC, datetime, timedelta

from book_scraper.db import scrape_run_events as run_event_types
from book_scraper.db.models import ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import (
    create_scrape_run,
    insert_scrape_url_item,
    restart_run_in_place,
    upsert_shop,
)


def _seed_failed_run(session, *, urls_processed=0):
    shop = upsert_shop(session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(session, shop.id, "scan")
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    run.close_reason = "stall_timeout"
    run.resumable_after_failure = True
    run.urls_processed = urls_processed
    run.pid = 1234
    run.last_heartbeat = datetime.now(UTC) - timedelta(minutes=10)
    insert_scrape_url_item(
        session,
        run_id=run.id,
        shop_id=shop.id,
        discovered_url_id=None,
        url="https://www.vaga.lt/p/1",
        url_type="product",
    )
    session.commit()
    return run


def test_restart_in_place_mutates_same_row(db_session):
    run = _seed_failed_run(db_session)
    original_started_at = run.started_at
    original_run_id = run.id

    restart_run_in_place(
        db_session,
        run,
        payload={
            "previous_close_reason": "stall_timeout",
            "attempt": 1,
            "urls_processed_snapshot": 0,
        },
        actor=run_event_types.ACTOR_SYSTEM,
    )
    db_session.commit()

    refreshed = db_session.get(ScrapeRun, original_run_id)
    assert refreshed.id == original_run_id
    assert refreshed.status == "running"
    assert refreshed.finished_at is None
    assert refreshed.close_reason is None
    assert refreshed.resumable_after_failure is False
    assert refreshed.started_at == original_started_at  # untouched

    events = [e for e in refreshed.events if e.event_type == run_event_types.RESTARTED]
    assert len(events) == 1
    assert events[0].payload["previous_close_reason"] == "stall_timeout"
    assert events[0].payload["attempt"] == 1
    assert events[0].actor == run_event_types.ACTOR_SYSTEM


def test_restart_in_place_emits_continued_when_actor_operator(db_session):
    run = _seed_failed_run(db_session)
    restart_run_in_place(
        db_session,
        run,
        payload={
            "previous_close_reason": "stall_timeout",
            "attempt": 1,
            "urls_processed_snapshot": 0,
        },
        actor=run_event_types.ACTOR_OPERATOR,
        event_type=run_event_types.CONTINUED,
    )
    db_session.commit()

    events = [e for e in run.events if e.event_type == run_event_types.CONTINUED]
    assert len(events) == 1


def test_restart_in_place_resets_retryable_failures(db_session):
    run = _seed_failed_run(db_session)
    item = db_session.query(ScrapeUrlItem).filter_by(run_id=run.id).first()
    item.status = "failed"
    db_session.flush()

    from book_scraper.db.repo import record_scrape_failure

    record_scrape_failure(
        db_session,
        scrape_url_item=item,
        error_reason="run_aborted",
        http_status=None,
    )
    db_session.commit()

    restart_run_in_place(
        db_session,
        run,
        payload={
            "previous_close_reason": "stall_timeout",
            "attempt": 1,
            "urls_processed_snapshot": 0,
        },
        actor=run_event_types.ACTOR_SYSTEM,
    )
    db_session.commit()

    refreshed_item = db_session.get(ScrapeUrlItem, item.id)
    assert refreshed_item.status == "pending"


def test_reset_retryable_failures_skips_attempt_exhausted_items(db_session):
    """Retryable failures that have already been attempted RETRY_CAP times
    must stay `failed` (sticky) instead of being reset to pending.

    Regression: a record that the server persistently 5xxes gets aborted
    mid-retry on every stall, comes back as `run_aborted` (retryable), and
    was reset to pending forever — never retiring. The scan re-dispatched
    it each resume, re-stalled, and never reached the healthy backlog. The
    `attempts < cap` ceiling lets these records exhaust and drop out.
    """
    from book_scraper.db.repo import record_scrape_failure, reset_retryable_failures
    from book_scraper.settings import RETRY_CAP

    run = _seed_failed_run(db_session)
    shop_id = run.shop_id

    def _failed_item(url, attempts):
        item = insert_scrape_url_item(
            db_session,
            run_id=run.id,
            shop_id=shop_id,
            discovered_url_id=None,
            url=url,
            url_type="product",
        )
        item.status = "failed"
        item.attempts = attempts
        db_session.flush()
        record_scrape_failure(
            db_session,
            scrape_url_item=item,
            error_reason="run_aborted",
            http_status=None,
        )
        db_session.flush()
        return item

    fresh = _failed_item("https://www.vaga.lt/p/fresh", attempts=RETRY_CAP - 1)
    exhausted = _failed_item("https://www.vaga.lt/p/exhausted", attempts=RETRY_CAP)
    db_session.commit()

    reset_retryable_failures(db_session, run.id)
    db_session.commit()

    assert db_session.get(ScrapeUrlItem, fresh.id).status == "pending"
    assert db_session.get(ScrapeUrlItem, exhausted.id).status == "failed"
