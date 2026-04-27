"""Track B — Operator controls: Stop, Re-run, Pre-flight, Repeated failures.

Covers the four API-side items (#20 Stop, #19 Re-run, #27 Pre-flight,
#25 Repeated failures). The fifth Track B item (#21, live-view-stays-static)
is React-only and verified manually after deploy.
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import get_repeated_failures, mark_stale_runs
from book_scraper.db.models import ScrapeRun, Shop, ValidationIssue
from book_scraper.db.repo import (
    create_scrape_run,
    record_scrape_run_failed_issue,
    upsert_shop,
)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ────────────────────────────── #20 Stop ──────────────────────────────


def test_stop_running_run_transitions_to_stopping(
    client: TestClient, db_session: Session
):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()

    resp = client.post(f"/api/runs/{run.id}/stop")
    assert resp.status_code == 200
    assert resp.json() == {"run_id": run.id, "status": "stopping"}
    db_session.refresh(run)
    assert run.status == "stopping"


def test_stop_terminal_run_is_idempotent(client: TestClient, db_session: Session):
    """Stopping a completed/failed run is a 200 no-op carrying current status."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    db_session.commit()

    resp = client.post(f"/api/runs/{run.id}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


def test_stop_unknown_run_returns_404(client: TestClient):
    resp = client.post("/api/runs/999999/stop")
    assert resp.status_code == 404


def test_reaper_marks_stuck_stopping_run_failed(db_session: Session):
    """A `stopping` run whose heartbeat goes stale gets reaped with
    error_reason='stop_timeout' and resumable_after_failure=True."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    run.status = "stopping"
    run.last_heartbeat = datetime.now(UTC) - timedelta(seconds=120)
    db_session.commit()

    marked = mark_stale_runs(db_session)
    assert marked == 1
    db_session.refresh(run)
    assert run.status == "failed"
    assert run.resumable_after_failure is True
    issue = (
        db_session.query(ValidationIssue)
        .filter_by(scrape_run_id=run.id, issue="scrape_run_failed")
        .one()
    )
    assert issue.raw_value == "stop_timeout"


# ────────────────────────────── #19 Re-run ──────────────────────────────


def test_rerun_failed_run_flags_resumable_and_spawns(
    client: TestClient, db_session: Session
):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    db_session.commit()

    with patch("book_scraper.dashboard.routes.api._spawn_scrapy_in_container") as spawn:
        resp = client.post(f"/api/runs/{run.id}/rerun")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "started"
    assert body["rerun_of"] == run.id
    assert body["shop"] == "vaga"

    spawn.assert_called_once()
    kwargs = spawn.call_args.kwargs
    assert kwargs["phase"] == "scan"
    assert kwargs["shop"] == "vaga"

    db_session.refresh(run)
    assert run.resumable_after_failure is True
    # The old run row stays in `failed` for postmortem.
    assert run.status == "failed"


def test_rerun_running_run_returns_400(client: TestClient, db_session: Session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()

    resp = client.post(f"/api/runs/{run.id}/rerun")
    assert resp.status_code == 400


def test_rerun_when_concurrent_run_active_returns_409(
    client: TestClient, db_session: Session
):
    """Pre-flight refuses to spawn if another run for the same shop+phase
    is already active. The request must NOT spawn a subprocess."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    failed_run = create_scrape_run(db_session, shop.id, "scan")
    failed_run.status = "failed"
    failed_run.finished_at = datetime.now(UTC)
    # And a concurrent active run already exists.
    active_run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()

    with patch("book_scraper.dashboard.routes.api._spawn_scrapy_in_container") as spawn:
        resp = client.post(f"/api/runs/{failed_run.id}/rerun")
    assert resp.status_code == 409
    spawn.assert_not_called()
    assert str(active_run.id) in resp.text or "running" in resp.text


def test_rerun_handles_discover_phase(client: TestClient, db_session: Session):
    """Re-running a discover_categories run preserves the phase as
    phase=discover, strategy=categories."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "discover_categories")
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    db_session.commit()

    with patch("book_scraper.dashboard.routes.api._spawn_scrapy_in_container") as spawn:
        resp = client.post(f"/api/runs/{run.id}/rerun")
    assert resp.status_code == 200
    spawn.assert_called_once()
    kwargs = spawn.call_args.kwargs
    assert kwargs["phase"] == "discover"
    assert kwargs["strategy"] == "categories"


# ────────────────────────────── #27 Pre-flight ──────────────────────────────


def test_create_run_rejects_unknown_shop(client: TestClient):
    resp = client.post(
        "/api/runs", json={"shop": "nonexistent_shop_xyz", "phase": "scan"}
    )
    assert resp.status_code == 404


def test_create_run_rejects_concurrent_active_run(
    client: TestClient, db_session: Session
):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()

    with patch("book_scraper.dashboard.routes.api._spawn_scrapy_in_container") as spawn:
        resp = client.post("/api/runs", json={"shop": "vaga", "phase": "scan"})
    assert resp.status_code == 409
    spawn.assert_not_called()


def test_create_run_rejects_concurrent_stopping_run(
    client: TestClient, db_session: Session
):
    """A run mid-shutdown must also block a fresh creation."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    run.status = "stopping"
    db_session.commit()

    with patch("book_scraper.dashboard.routes.api._spawn_scrapy_in_container") as spawn:
        resp = client.post("/api/runs", json={"shop": "vaga", "phase": "scan"})
    assert resp.status_code == 409
    spawn.assert_not_called()
    assert str(run.id) in resp.text


# ────────────────────────────── #25 Repeated failures ──────────────────────────────


def _seed_failed_run(db_session: Session, shop_id: int, phase: str, reason: str):
    run = create_scrape_run(db_session, shop_id, phase)
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    db_session.commit()
    record_scrape_run_failed_issue(db_session, run, reason)
    db_session.commit()
    return run


def test_repeated_failures_detects_3_consecutive_same_reason(
    db_session: Session,
):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    for _ in range(3):
        _seed_failed_run(db_session, shop.id, "scan", "heartbeat_timeout")

    items = get_repeated_failures(db_session)
    matching = [i for i in items if i["shop"] == "vaga" and i["phase"] == "scan"]
    assert len(matching) == 1
    assert matching[0]["count"] == 3
    assert matching[0]["error_reason"] == "heartbeat_timeout"


def test_repeated_failures_ignores_mixed_reasons(db_session: Session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    _seed_failed_run(db_session, shop.id, "scan", "heartbeat_timeout")
    _seed_failed_run(db_session, shop.id, "scan", "stall_timeout")
    _seed_failed_run(db_session, shop.id, "scan", "heartbeat_timeout")

    items = get_repeated_failures(db_session)
    matching = [i for i in items if i["shop"] == "vaga" and i["phase"] == "scan"]
    assert matching == []


def test_repeated_failures_resets_on_success(db_session: Session):
    """A `completed` run in the recent window breaks the streak."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    _seed_failed_run(db_session, shop.id, "scan", "heartbeat_timeout")
    _seed_failed_run(db_session, shop.id, "scan", "heartbeat_timeout")
    # Then a success.
    ok = create_scrape_run(db_session, shop.id, "scan")
    ok.status = "completed"
    ok.finished_at = datetime.now(UTC)
    db_session.commit()

    items = get_repeated_failures(db_session)
    matching = [i for i in items if i["shop"] == "vaga" and i["phase"] == "scan"]
    assert matching == []


def test_get_run_in_flight_caps_at_render_limit(db_session: Session):
    """Defensive: a run with N >> CONCURRENT_REQUESTS_PER_DOMAIN stuck
    `processing` rows must not blow up the live panel. Cap at
    IN_FLIGHT_RENDER_CAP. Real runs should never hit this — Track A's
    abort_processing_scrape_url_items zeroes processing rows on
    transition — but the dashboard hardens against stranded data."""
    from book_scraper.dashboard.queries import (
        IN_FLIGHT_RENDER_CAP,
        get_run_in_flight,
    )
    from book_scraper.db.models import DiscoveredUrl
    from book_scraper.db.repo import insert_scrape_url_item

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()

    cap = IN_FLIGHT_RENDER_CAP
    extras = 5
    for i in range(cap + extras):
        url = f"https://vaga.lt/cap-{i}"
        db_session.add(
            DiscoveredUrl(
                shop_id=shop.id,
                url=url,
                normalized_url=url,
                source="sitemap",
                url_type="product",
                fail_count=0,
            )
        )
        db_session.flush()
        du = db_session.query(DiscoveredUrl).filter_by(url=url, shop_id=shop.id).one()
        item = insert_scrape_url_item(db_session, run.id, shop.id, du.id, url)
        item.status = "processing"
        item.claimed_at = datetime.now(UTC)
    db_session.commit()

    in_flight = get_run_in_flight(db_session, run.id)
    assert len(in_flight) == cap


def test_repeated_failures_endpoint(client: TestClient, db_session: Session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()
    for _ in range(3):
        _seed_failed_run(db_session, shop.id, "scan", "heartbeat_timeout")

    resp = client.get("/api/runs/repeated-failures")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    matching = [
        i for i in body["items"] if i["shop"] == "vaga" and i["phase"] == "scan"
    ]
    assert len(matching) == 1
    assert matching[0]["error_reason"] == "heartbeat_timeout"


# Avoid unused-import warnings.
_ = (Shop, ScrapeRun)
