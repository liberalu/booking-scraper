"""Integration tests for GET /api/runs/{id}/live."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db
from book_scraper.db.models import (
    DiscoveredUrl,
    ScrapeRun,
    ScrapeUrlItem,
    Shop,
)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_run(
    db_session: Session,
    *,
    status: str = "running",
    last_heartbeat: datetime | None = None,
) -> tuple[Shop, ScrapeRun]:
    shop = Shop(name="vagatest", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    run = ScrapeRun(
        shop_id=shop.id,
        phase="scan",
        status=status,
        last_heartbeat=last_heartbeat or datetime.now(UTC),
    )
    db_session.add(run)
    db_session.flush()
    return shop, run


def _add_url(
    db_session: Session,
    shop: Shop,
    run: ScrapeRun,
    *,
    url: str,
    status: str = "pending",
    claimed_at: datetime | None = None,
    done_at: datetime | None = None,
    http_status: int | None = None,
    error_reason: str | None = None,
    request_delay_s: float | None = None,
    delay_source: str | None = None,
    response_bytes: int | None = None,
) -> ScrapeUrlItem:
    discovered = DiscoveredUrl(
        shop_id=shop.id,
        url=url,
        normalized_url=url,
        source="sitemap",
        url_type="product",
        fail_count=0,
    )
    db_session.add(discovered)
    db_session.flush()
    item = ScrapeUrlItem(
        run_id=run.id,
        shop_id=shop.id,
        discovered_url_id=discovered.id,
        url=url,
        url_type="product",
        status=status,
        claimed_at=claimed_at,
        done_at=done_at,
        http_status=http_status,
        error_reason=error_reason,
        request_delay_s=request_delay_s,
        delay_source=delay_source,
        response_bytes=response_bytes,
    )
    db_session.add(item)
    db_session.flush()
    return item


def test_live_route_404_for_unknown_run(client: TestClient) -> None:
    resp = client.get("/api/runs/999999/live")
    assert resp.status_code == 404


def test_live_route_empty_run_returns_zeros(
    client: TestClient, db_session: Session
) -> None:
    _, run = _seed_run(db_session)
    db_session.commit()

    resp = client.get(f"/api/runs/{run.id}/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run.id
    assert body["status"] == "running"
    assert body["health"] == "healthy"
    assert body["in_flight"] == []
    assert body["rate"] == {"window_s": 60, "done": 0, "failed": 0}
    assert body["recent_failures"] == []
    assert body["recent_activity"] == []


def test_live_route_reports_in_flight_with_telemetry(
    client: TestClient, db_session: Session
) -> None:
    shop, run = _seed_run(db_session)
    claimed_at = datetime.now(UTC) - timedelta(seconds=2)
    _add_url(
        db_session,
        shop,
        run,
        url="https://vaga.lt/a",
        status="processing",
        claimed_at=claimed_at,
        request_delay_s=0.5,
        delay_source="httpx_observed",
    )
    db_session.commit()

    body = client.get(f"/api/runs/{run.id}/live").json()
    assert len(body["in_flight"]) == 1
    row = body["in_flight"][0]
    assert row["url"] == "https://vaga.lt/a"
    assert row["request_delay_s"] == 0.5
    assert row["delay_source"] == "httpx_observed"
    assert row["retry_count"] == 0
    assert 0 <= row["claimed_age_s"] < 60
    assert body["health"] == "healthy"


def test_live_route_marks_stuck_when_in_flight_age_exceeds_threshold(
    client: TestClient, db_session: Session
) -> None:
    shop, run = _seed_run(db_session)
    claimed_at = datetime.now(UTC) - timedelta(seconds=45)
    _add_url(
        db_session,
        shop,
        run,
        url="https://vaga.lt/hung",
        status="processing",
        claimed_at=claimed_at,
    )
    db_session.commit()

    body = client.get(f"/api/runs/{run.id}/live").json()
    assert body["health"] == "stuck"


def test_live_route_marks_dead_when_heartbeat_stale(
    client: TestClient, db_session: Session
) -> None:
    _, run = _seed_run(
        db_session,
        last_heartbeat=datetime.now(UTC) - timedelta(seconds=120),
    )
    db_session.commit()

    body = client.get(f"/api/runs/{run.id}/live").json()
    assert body["health"] == "dead"


def test_live_route_returns_recent_done_and_failed_counts(
    client: TestClient, db_session: Session
) -> None:
    shop, run = _seed_run(db_session)
    now = datetime.now(UTC)
    # 2 done within window, 1 failed within window, 1 done outside window
    _add_url(
        db_session, shop, run, url="https://vaga.lt/d1",
        status="done", done_at=now - timedelta(seconds=5),
    )
    _add_url(
        db_session, shop, run, url="https://vaga.lt/d2",
        status="done", done_at=now - timedelta(seconds=30),
    )
    _add_url(
        db_session, shop, run, url="https://vaga.lt/f1",
        status="failed", done_at=now - timedelta(seconds=10),
        error_reason="http_503", http_status=503,
    )
    _add_url(
        db_session, shop, run, url="https://vaga.lt/d_old",
        status="done", done_at=now - timedelta(seconds=120),
    )
    db_session.commit()

    body = client.get(f"/api/runs/{run.id}/live").json()
    assert body["rate"]["done"] == 3  # all 3 within last 60s
    assert body["rate"]["failed"] == 1
    assert len(body["recent_failures"]) == 1
    failure = body["recent_failures"][0]
    assert failure["url"] == "https://vaga.lt/f1"
    assert failure["http_status"] == 503
    assert failure["error_reason"] == "http_503"


def test_live_route_recent_activity_includes_timing_and_throttle(
    client: TestClient, db_session: Session
) -> None:
    """recent_activity surfaces start time, finish time, duration,
    throttle delay, and source for done+failed rows newest-first."""
    shop, run = _seed_run(db_session)
    now = datetime.now(UTC)
    claimed_done = now - timedelta(seconds=12)
    done_at = now - timedelta(seconds=10)
    _add_url(
        db_session, shop, run, url="https://vaga.lt/done1",
        status="done", claimed_at=claimed_done, done_at=done_at,
        request_delay_s=2.34, delay_source="autothrottle",
        response_bytes=18432, http_status=200,
    )
    _add_url(
        db_session, shop, run, url="https://vaga.lt/fail1",
        status="failed", claimed_at=now - timedelta(seconds=8),
        done_at=now - timedelta(seconds=6),
        request_delay_s=4.5, delay_source="autothrottle",
        http_status=503, error_reason="http_503",
    )
    # processing rows must NOT appear in recent_activity
    _add_url(
        db_session, shop, run, url="https://vaga.lt/inflight",
        status="processing", claimed_at=now - timedelta(seconds=1),
    )
    db_session.commit()

    body = client.get(f"/api/runs/{run.id}/live").json()
    activity = body["recent_activity"]
    assert len(activity) == 2
    # newest first by done_at
    assert activity[0]["url"] == "https://vaga.lt/fail1"
    assert activity[0]["status"] == "failed"
    assert activity[0]["http_status"] == 503
    assert activity[0]["error_reason"] == "http_503"
    assert activity[0]["delay_source"] == "autothrottle"
    assert activity[0]["request_delay_s"] == 4.5
    assert activity[0]["claimed_at"] is not None
    assert activity[0]["done_at"] is not None
    assert activity[0]["duration_s"] is not None and activity[0]["duration_s"] >= 0
    assert activity[1]["url"] == "https://vaga.lt/done1"
    assert activity[1]["status"] == "done"
    assert activity[1]["response_bytes"] == 18432
    assert activity[1]["delay_source"] == "autothrottle"


def test_live_route_works_for_finished_run(
    client: TestClient, db_session: Session
) -> None:
    """A 'completed' run should still answer with health = '' (empty)."""
    _, run = _seed_run(db_session, status="completed")
    db_session.commit()

    body = client.get(f"/api/runs/{run.id}/live").json()
    assert body["status"] == "completed"
    assert body["health"] == ""
