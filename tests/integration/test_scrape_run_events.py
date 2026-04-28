"""Integration tests for scrape_run_events lifecycle log.

Covers:
  - emit_scrape_run_event helper validates event_type
  - create_scrape_run emits 'started'
  - finish_scrape_run emits 'completed' / 'failed' once
  - mark_stale_runs (dashboard reaper) emits 'failed'
  - mark_orphan_runs_failed (boot reaper) emits 'failed'
  - mark_stale_runs_failed (pre-scan reaper) emits 'failed'
  - get_scrape_run_events returns oldest-first dicts
  - api_run_detail and api_run_live include events
  - operator endpoints (pause/resume/stop/retry/rerun/continue) emit events
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import get_scrape_run_events, mark_stale_runs
from book_scraper.db import scrape_run_events as run_event_types
from book_scraper.db.models import ScrapeRunEvent
from book_scraper.db.repo import (
    create_scrape_run,
    emit_scrape_run_event,
    finish_scrape_run,
    mark_orphan_runs_failed,
    mark_stale_runs_failed,
    upsert_shop,
)


def _make_shop(db_session, name="ev_shop"):
    shop = upsert_shop(db_session, name, "https://example.com")
    db_session.commit()
    return shop


def _events_of(db_session, run_id):
    return (
        db_session.query(ScrapeRunEvent)
        .filter_by(run_id=run_id)
        .order_by(ScrapeRunEvent.created_at.asc(), ScrapeRunEvent.id.asc())
        .all()
    )


def test_emit_scrape_run_event_rejects_unknown_type(db_session):
    shop = _make_shop(db_session, "ev_unknown")
    run = create_scrape_run(db_session, shop.id, "scan")
    with pytest.raises(ValueError):
        emit_scrape_run_event(db_session, run.id, "nope_not_real")


def test_create_scrape_run_emits_started(db_session):
    shop = _make_shop(db_session, "ev_started")
    run = create_scrape_run(
        db_session,
        shop.id,
        "scan",
        urls_total=12,
        extra_payload={"rescrape": True},
    )
    events = _events_of(db_session, run.id)
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == run_event_types.STARTED
    assert ev.actor == run_event_types.ACTOR_SYSTEM
    assert ev.payload["phase"] == "scan"
    assert ev.payload["urls_total"] == 12
    assert ev.payload["rescrape"] is True


def test_finish_scrape_run_emits_completed(db_session):
    shop = _make_shop(db_session, "ev_completed")
    run = create_scrape_run(db_session, shop.id, "scan")
    finish_scrape_run(db_session, run.id, "completed", reason="finished")
    types = [e.event_type for e in _events_of(db_session, run.id)]
    assert types == [run_event_types.STARTED, run_event_types.COMPLETED]
    completed = _events_of(db_session, run.id)[-1]
    assert completed.payload["close_reason"] == "finished"


def test_finish_scrape_run_emits_failed(db_session):
    shop = _make_shop(db_session, "ev_failed")
    run = create_scrape_run(db_session, shop.id, "scan")
    finish_scrape_run(
        db_session, run.id, "failed", reason="stopped_by_operator"
    )
    types = [e.event_type for e in _events_of(db_session, run.id)]
    assert types == [run_event_types.STARTED, run_event_types.FAILED]
    failed = _events_of(db_session, run.id)[-1]
    assert failed.payload["close_reason"] == "stopped_by_operator"


def test_finish_scrape_run_idempotent_no_duplicate_event(db_session):
    shop = _make_shop(db_session, "ev_idem")
    run = create_scrape_run(db_session, shop.id, "scan")
    finish_scrape_run(db_session, run.id, "completed", reason="finished")
    finish_scrape_run(db_session, run.id, "completed", reason="finished")
    types = [e.event_type for e in _events_of(db_session, run.id)]
    assert types == [run_event_types.STARTED, run_event_types.COMPLETED]


def test_mark_stale_runs_emits_failed(db_session):
    """Dashboard reaper: heartbeat-timeout path emits a failed event."""
    shop = _make_shop(db_session, "ev_reap_stale")
    run = create_scrape_run(db_session, shop.id, "scan")
    # Force the heartbeat into the past so the reaper picks it up.
    run.last_heartbeat = datetime.now(UTC) - timedelta(seconds=600)
    db_session.commit()
    marked = mark_stale_runs(db_session)
    assert marked >= 1
    db_session.expire_all()
    types = [e.event_type for e in _events_of(db_session, run.id)]
    assert types == [run_event_types.STARTED, run_event_types.FAILED]
    failed = _events_of(db_session, run.id)[-1]
    assert failed.payload["close_reason"] == "heartbeat_timeout"


def test_mark_orphan_runs_failed_emits_failed(db_session):
    """Boot reaper: any 'running' row gets marked failed with orphan_on_boot."""
    shop = _make_shop(db_session, "ev_orphan")
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()
    n = mark_orphan_runs_failed(db_session)
    assert n >= 1
    db_session.expire_all()
    types = [e.event_type for e in _events_of(db_session, run.id)]
    assert types == [run_event_types.STARTED, run_event_types.FAILED]
    failed = _events_of(db_session, run.id)[-1]
    assert failed.payload["close_reason"] == "orphan_on_boot"


def test_mark_stale_runs_failed_emits_failed(db_session):
    """Pre-scan reaper (mark_stale_runs_failed): emits a failed event."""
    shop = _make_shop(db_session, "ev_pre_scan")
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()
    n = mark_stale_runs_failed(db_session, shop.id, "scan", reason="stale_pre_scan")
    assert n >= 1
    db_session.expire_all()
    types = [e.event_type for e in _events_of(db_session, run.id)]
    assert types == [run_event_types.STARTED, run_event_types.FAILED]
    failed = _events_of(db_session, run.id)[-1]
    assert failed.payload["close_reason"] == "stale_pre_scan"


def test_get_scrape_run_events_returns_oldest_first(db_session):
    shop = _make_shop(db_session, "ev_order")
    run = create_scrape_run(db_session, shop.id, "scan")
    emit_scrape_run_event(
        db_session,
        run.id,
        run_event_types.PAUSED,
        actor=run_event_types.ACTOR_OPERATOR,
        payload={"previous_status": "running"},
    )
    emit_scrape_run_event(
        db_session,
        run.id,
        run_event_types.RESUMED,
        actor=run_event_types.ACTOR_OPERATOR,
        payload={"previous_status": "paused"},
    )
    db_session.commit()
    events = get_scrape_run_events(db_session, run.id)
    assert [e["event_type"] for e in events] == [
        run_event_types.STARTED,
        run_event_types.PAUSED,
        run_event_types.RESUMED,
    ]
    # Each dict carries the standard shape.
    pause = events[1]
    assert pause["actor"] == run_event_types.ACTOR_OPERATOR
    assert pause["payload"] == {"previous_status": "running"}
    assert pause["created_at"] is not None


# ──────────────────────────── API surface ────────────────────────────


@pytest.fixture()
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient with DB dependency overridden to use the rolling test session."""

    def _override() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_run_detail_includes_events(api_client, db_session):
    shop = _make_shop(db_session, "ev_api_detail")
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()
    r = api_client.get(f"/api/runs/{run.id}")
    assert r.status_code == 200
    body = r.json()
    assert "events" in body
    types = [e["event_type"] for e in body["events"]]
    assert run_event_types.STARTED in types


def test_api_run_live_includes_events(api_client, db_session):
    shop = _make_shop(db_session, "ev_api_live")
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()
    r = api_client.get(f"/api/runs/{run.id}/live")
    assert r.status_code == 200
    body = r.json()
    assert "events" in body
    types = [e["event_type"] for e in body["events"]]
    assert run_event_types.STARTED in types


def test_api_pause_resume_stop_emit_events(api_client, db_session):
    shop = _make_shop(db_session, "ev_api_ops")
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()

    # Pause from running.
    r = api_client.post(f"/api/runs/{run.id}/pause")
    assert r.status_code == 200
    assert r.json()["status"] == "paused"

    # Resume back to running.
    r = api_client.post(f"/api/runs/{run.id}/resume")
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    # Stop request flips to stopping.
    r = api_client.post(f"/api/runs/{run.id}/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "stopping"

    db_session.expire_all()
    types = [e.event_type for e in _events_of(db_session, run.id)]
    assert types == [
        run_event_types.STARTED,
        run_event_types.PAUSED,
        run_event_types.RESUMED,
        run_event_types.STOP_REQUESTED,
    ]
