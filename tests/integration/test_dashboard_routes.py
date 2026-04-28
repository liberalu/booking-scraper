"""Smoke tests for all dashboard routes.

Verifies every page returns 200 after deployment.
Requires a running PostgreSQL test database on port 5433.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db
from book_scraper.db.models import (
    ScrapeRun,
    ScrapeUrlItem,
    Shop,
    ShopBook,
    ValidationIssue,
)
from book_scraper.db.repo import bulk_insert_validation_issues


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient with DB dependency overridden to use test session."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _ensure_shop(db_session: Session) -> None:
    """Ensure a test shop exists for shop-specific routes."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").first()
    if not shop:
        shop = Shop(name="vaga", base_url="https://www.vaga.lt")
        db_session.add(shop)
        db_session.flush()


@pytest.mark.integration
def test_shop_book_detail_api_returns_classification(
    client: TestClient, db_session: Session
) -> None:
    # SPA fetches via /api/shop-books/{id} — verify the JSON has the
    # fields the UI renders (type, categories).
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    shop_book = ShopBook(
        shop_id=shop.id,
        url="https://vaga.lt/vokas",
        title="Vokas popierinis",
        type="non_book",
        categories=["Mokyklinės ir raštinės prekės"],
    )
    db_session.add(shop_book)
    db_session.commit()

    response = client.get(f"/api/shop-books/{shop_book.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "non_book"
    assert "Mokyklinės ir raštinės prekės" in data["categories"]


@pytest.mark.integration
def test_url_detail_api_404(client: TestClient) -> None:
    """Non-existent URL ID returns 404 from the API."""
    response = client.get("/api/urls/999999")
    assert response.status_code == 404


@pytest.mark.integration
def test_url_detail_api_returns_url(
    client: TestClient, db_session: Session
) -> None:
    """An existing DiscoveredUrl is returned by the API."""
    from book_scraper.db.repo import upsert_discovered_url, upsert_shop

    shop = upsert_shop(db_session, "smoke_shop", "https://smoke.example.com")
    url = upsert_discovered_url(
        db_session, shop.id, "https://smoke.example.com/p/1", "sitemap"
    )
    db_session.commit()

    response = client.get(f"/api/urls/{url.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "https://smoke.example.com/p/1"
    assert data["shop"] == "smoke_shop"


@pytest.mark.integration
def test_api_overview(client: TestClient) -> None:
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "stats" in data
    assert "recent_runs" in data
    assert "activity" in data
    assert len(data["activity"]) == 14


@pytest.mark.integration
def test_api_runs(client: TestClient) -> None:
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert "kpis" in data
    assert "running_now" in data["kpis"]


@pytest.mark.integration
def test_api_shop_books(client: TestClient) -> None:
    resp = client.get("/api/shop-books")
    assert resp.status_code == 200
    data = resp.json()
    assert "books" in data
    assert "total" in data
    assert "kpis" in data


@pytest.mark.integration
def test_api_urls(client: TestClient) -> None:
    resp = client.get("/api/urls")
    assert resp.status_code == 200
    data = resp.json()
    assert "urls" in data
    assert "stats" in data


@pytest.mark.integration
def test_api_shops(client: TestClient) -> None:
    resp = client.get("/api/shops")
    assert resp.status_code == 200
    data = resp.json()
    assert "shops" in data


@pytest.mark.integration
def test_api_cron(client: TestClient) -> None:
    resp = client.get("/api/cron")
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data


@pytest.mark.integration
def test_api_issues(client: TestClient) -> None:
    resp = client.get("/api/issues")
    assert resp.status_code == 200
    data = resp.json()
    assert "issues" in data
    assert "counts" in data


@pytest.mark.integration
def test_api_issues_run_id_filter(client: TestClient, db_session: Session) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").first()
    run_a = ScrapeRun(shop_id=shop.id, phase="scan", status="completed")
    run_b = ScrapeRun(shop_id=shop.id, phase="scan", status="completed")
    db_session.add_all([run_a, run_b])
    db_session.flush()

    def _seed(run_id: int, n: int) -> None:
        bulk_insert_validation_issues(
            db_session,
            [
                {
                    "scrape_run_id": run_id,
                    "url": f"https://vaga.lt/book-{run_id}-{i}",
                    "field": "price",
                    "issue": "missing",
                    "raw_value": None,
                    "shop_book_id": None,
                }
                for i in range(n)
            ],
        )

    _seed(run_a.id, 2)
    _seed(run_b.id, 3)
    db_session.flush()

    resp = client.get(f"/api/issues?run_id={run_a.id}&state=all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(i["scrape_run_id"] == run_a.id for i in data["issues"])
    c = data["counts"]
    assert c["new"] + c["recurring"] + c["already_seen"] == 2

    resp_b = client.get(f"/api/issues?run_id={run_b.id}&state=all")
    assert resp_b.json()["total"] == 3


@pytest.mark.integration
def test_api_prices(client: TestClient) -> None:
    resp = client.get("/api/prices")
    assert resp.status_code == 200
    data = resp.json()
    assert "changes" in data
    assert "days" in data


@pytest.mark.integration
def test_api_shop_not_found(client: TestClient) -> None:
    resp = client.get("/api/shops/nonexistent_shop_xyz")
    assert resp.status_code == 404


@pytest.mark.integration
def test_api_run_not_found(client: TestClient) -> None:
    resp = client.get("/api/runs/999999999")
    assert resp.status_code == 404


@pytest.mark.integration
def test_spa_entry_point(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<html" in resp.content
    assert b"BookScraper Dashboard" in resp.content


@pytest.mark.integration
def test_validation_redirects_to_issues(client: TestClient) -> None:
    resp = client.get("/validation", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/issues"


@pytest.mark.integration
def test_validation_redirects_preserves_query_string(client: TestClient) -> None:
    resp = client.get("/validation?run_id=42&state=new", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/issues?run_id=42&state=new"


@pytest.mark.integration
def test_not_listed_redirects_to_shop_detail(client: TestClient) -> None:
    resp = client.get("/shops/vaga/not-listed", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/shops/vaga"


@pytest.mark.integration
def test_update_rate_settings_persists(
    client: TestClient, db_session: Session
) -> None:
    from book_scraper.db.models import ShopSettings

    response = client.post(
        "/shops/vaga/rate-settings",
        data={"download_delay": "1.5", "concurrent_requests_per_domain": "2"},
    )
    assert response.status_code == 200
    assert "Saved" in response.text

    shop = db_session.query(Shop).filter(Shop.name == "vaga").first()
    assert shop is not None
    db_session.expire(shop)
    rows = (
        db_session.query(ShopSettings)
        .filter(ShopSettings.shop_id == shop.id)
        .all()
    )
    settings = {r.key: r.value for r in rows}
    assert settings.get("download_delay") == "1.5"
    assert settings.get("concurrent_requests_per_domain") == "2"


@pytest.mark.integration
def test_update_rate_settings_validates_bounds(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/shops/vaga/rate-settings",
        data={"download_delay": "0.0", "concurrent_requests_per_domain": "1"},
    )
    assert response.status_code == 400

    response = client.post(
        "/shops/vaga/rate-settings",
        data={"download_delay": "1.0", "concurrent_requests_per_domain": "0"},
    )
    assert response.status_code == 400


# ── /api/runs/{id}/continue ──────────────────────────────────────────────


def _make_stopped_scan_run(
    db_session: Session,
    shop_id: int,
    *,
    pending: int = 2,
    phase: str = "scan",
    close_reason_value: str | None = "stopped_by_operator",
) -> ScrapeRun:
    """Create a failed run with the given close_reason and pending URLs.

    `close_reason` is read from the latest ValidationIssue with
    issue='scrape_run_failed' (see get_run_close_reason).
    """
    from datetime import UTC, datetime

    run = ScrapeRun(
        shop_id=shop_id,
        phase=phase,
        status="failed",
        close_reason=close_reason_value,
        finished_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.flush()

    if close_reason_value is not None:
        db_session.add(
            ValidationIssue(
                scrape_run_id=run.id,
                url="run-level",
                field="run",
                issue="scrape_run_failed",
                raw_value=close_reason_value,
                shop_book_id=None,
            )
        )

    for i in range(pending):
        db_session.add(
            ScrapeUrlItem(
                run_id=run.id,
                shop_id=shop_id,
                url=f"https://vaga.lt/p/{run.id}-{i}",
                url_type="product",
                status="pending",
            )
        )
    db_session.commit()
    return run


@pytest.fixture()
def _mock_spawn(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def _fake(
        *, phase: str, shop: str, strategy: str = "", mode: str = "delta"
    ) -> None:
        calls.append(
            {"phase": phase, "shop": shop, "strategy": strategy, "mode": mode}
        )

    monkeypatch.setattr(
        "book_scraper.dashboard.routes.api._spawn_scrapy_in_container", _fake
    )
    return calls


@pytest.mark.integration
def test_continue_run_happy_path(
    client: TestClient, db_session: Session, _mock_spawn: list[dict]
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_stopped_scan_run(db_session, shop.id, pending=3)

    resp = client.post(f"/api/runs/{run.id}/continue")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"status": "continued", "run_id": run.id, "shop": "vaga"}

    db_session.expire_all()
    refreshed = db_session.get(ScrapeRun, run.id)
    assert refreshed is not None
    assert refreshed.status == "running"
    assert refreshed.close_reason is None
    assert refreshed.finished_at is None

    pending_after = (
        db_session.query(ScrapeUrlItem)
        .filter(
            ScrapeUrlItem.run_id == run.id, ScrapeUrlItem.status == "pending"
        )
        .count()
    )
    assert pending_after == 3
    assert _mock_spawn == [
        {"phase": "scan", "shop": "vaga", "strategy": "", "mode": "delta"}
    ]


@pytest.mark.integration
def test_continue_run_rejects_non_operator_failure(
    client: TestClient, db_session: Session, _mock_spawn: list[dict]
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_stopped_scan_run(
        db_session, shop.id, close_reason_value="heartbeat_timeout"
    )

    resp = client.post(f"/api/runs/{run.id}/continue")
    assert resp.status_code == 400
    assert _mock_spawn == []

    refreshed = db_session.get(ScrapeRun, run.id)
    assert refreshed is not None
    assert refreshed.status == "failed"


@pytest.mark.integration
def test_continue_run_rejects_discover_phase(
    client: TestClient, db_session: Session, _mock_spawn: list[dict]
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_stopped_scan_run(
        db_session, shop.id, phase="discover_categories"
    )

    resp = client.post(f"/api/runs/{run.id}/continue")
    assert resp.status_code == 400
    assert _mock_spawn == []


@pytest.mark.integration
def test_continue_run_rejects_when_no_pending_items(
    client: TestClient, db_session: Session, _mock_spawn: list[dict]
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_stopped_scan_run(db_session, shop.id, pending=0)

    resp = client.post(f"/api/runs/{run.id}/continue")
    assert resp.status_code == 400
    assert "pending" in resp.json()["detail"].lower()
    assert _mock_spawn == []


@pytest.mark.integration
def test_continue_run_rejects_when_other_run_active(
    client: TestClient, db_session: Session, _mock_spawn: list[dict]
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_stopped_scan_run(db_session, shop.id, pending=1)

    other = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(other)
    db_session.commit()

    resp = client.post(f"/api/runs/{run.id}/continue")
    assert resp.status_code == 409
    assert _mock_spawn == []

    refreshed = db_session.get(ScrapeRun, run.id)
    assert refreshed is not None
    assert refreshed.status == "failed"


@pytest.mark.integration
def test_continue_run_rolls_back_on_spawn_failure(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_stopped_scan_run(db_session, shop.id, pending=2)

    db_session.expire(run)
    refreshed_before = db_session.get(ScrapeRun, run.id)
    assert refreshed_before is not None
    snapshot_close_reason = refreshed_before.close_reason
    snapshot_finished_at = refreshed_before.finished_at
    snapshot_last_heartbeat = refreshed_before.last_heartbeat
    snapshot_pid = refreshed_before.pid

    def _boom(**_kwargs: object) -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="Docker not available")

    monkeypatch.setattr(
        "book_scraper.dashboard.routes.api._spawn_scrapy_in_container", _boom
    )

    resp = client.post(f"/api/runs/{run.id}/continue")
    assert resp.status_code == 503

    db_session.expire_all()
    after = db_session.get(ScrapeRun, run.id)
    assert after is not None
    assert after.status == "failed"
    assert after.close_reason == snapshot_close_reason
    assert after.finished_at == snapshot_finished_at
    assert after.last_heartbeat == snapshot_last_heartbeat
    assert after.pid == snapshot_pid


@pytest.mark.integration
def test_continue_run_404_when_missing(client: TestClient) -> None:
    resp = client.post("/api/runs/999999999/continue")
    assert resp.status_code == 404
