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
    ScrapeFailure,
    ScrapeRun,
    ScrapeUrlItem,
    Shop,
    ShopBook,
    ShopBookAttribute,
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
def test_shop_book_detail_api_returns_sku_and_attributes(
    client: TestClient, db_session: Session
) -> None:
    """The detail endpoint must surface the durable identifier (sku) and
    every shop_book_attributes row (translator, dimensions, cover_type,
    language, …). Pre-fix these were captured by the parsers but never
    rendered — the user looking at /shop-books/27739 saw an empty 'Raw
    data' tab and concluded the data was missing entirely."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    shop_book = ShopBook(
        shop_id=shop.id,
        url="https://vaga.lt/test-attrs-1234",
        title="Attrs Test",
        sku="000000000001234567",
        type="book",
    )
    db_session.add(shop_book)
    db_session.flush()
    db_session.add_all(
        [
            ShopBookAttribute(
                shop_book_id=shop_book.id,
                key="translator",
                value="Test Translator",
            ),
            ShopBookAttribute(
                shop_book_id=shop_book.id, key="dimensions", value="23x15x1,4"
            ),
            ShopBookAttribute(
                shop_book_id=shop_book.id, key="cover_type", value="Kietas"
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/api/shop-books/{shop_book.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["sku"] == "000000000001234567"
    assert data["attributes"] == {
        "translator": "Test Translator",
        "dimensions": "23x15x1,4",
        "cover_type": "Kietas",
    }


@pytest.mark.integration
def test_url_detail_api_404(client: TestClient) -> None:
    """Non-existent URL ID returns 404 from the API."""
    response = client.get("/api/urls/999999")
    assert response.status_code == 404


@pytest.mark.integration
def test_url_detail_api_returns_url(client: TestClient, db_session: Session) -> None:
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
def test_api_cron_returns_200_with_graphql_strategy_job(
    client: TestClient, db_session: Session
) -> None:
    """Regression: graphql/lupasearch strategies must not crash /api/cron."""
    from book_scraper.db.repo import create_cron_job, upsert_shop

    shop = upsert_shop(db_session, "pegasas", "https://www.pegasas.lt")
    create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="discover",
        strategy="graphql",
        args="",
        cron_expression="0 1 * * *",
        enabled=True,
    )
    db_session.commit()

    resp = client.get("/api/cron")
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    graphql_jobs = [j for j in data["jobs"] if j["strategy"] == "graphql"]
    assert len(graphql_jobs) == 1


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
def test_update_rate_settings_persists(client: TestClient, db_session: Session) -> None:
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
    rows = db_session.query(ShopSettings).filter(ShopSettings.shop_id == shop.id).all()
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
        calls.append({"phase": phase, "shop": shop, "strategy": strategy, "mode": mode})

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
        .filter(ScrapeUrlItem.run_id == run.id, ScrapeUrlItem.status == "pending")
        .count()
    )
    assert pending_after == 3
    assert _mock_spawn == [
        {"phase": "scan", "shop": "vaga", "strategy": "", "mode": "delta"}
    ]


@pytest.mark.integration
def test_continue_run_works_for_any_failure_with_pending(
    client: TestClient, db_session: Session, _mock_spawn: list[dict]
) -> None:
    """Continue is eligible for any failed scan with pending items —
    not only operator stops. Covers heartbeat_timeout, orphan_on_boot,
    stall_timeout, etc."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_stopped_scan_run(
        db_session, shop.id, close_reason_value="heartbeat_timeout"
    )

    resp = client.post(f"/api/runs/{run.id}/continue")
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    refreshed = db_session.get(ScrapeRun, run.id)
    assert refreshed is not None
    assert refreshed.status == "running"
    assert _mock_spawn == [
        {"phase": "scan", "shop": "vaga", "strategy": "", "mode": "delta"}
    ]


@pytest.mark.integration
def test_continue_run_works_for_discover_phase(
    client: TestClient, db_session: Session, _mock_spawn: list[dict]
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_stopped_scan_run(db_session, shop.id, phase="discover_categories")

    resp = client.post(f"/api/runs/{run.id}/continue")
    assert resp.status_code == 200, resp.text
    assert _mock_spawn == [
        {"phase": "discover", "shop": "vaga", "strategy": "categories", "mode": "delta"}
    ]


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


# ── /api/runs/{id}/urls — failure-group filters ────────────────────────────


def _make_run_with_failures(db_session: Session, shop_id: int) -> ScrapeRun:
    """Run with five failed scrape_url_items spanning the buckets the
    Failures-card buttons need to filter on (same reason / different
    http_status, plus a NULL-reason row).
    """
    from datetime import UTC, datetime

    run = ScrapeRun(
        shop_id=shop_id,
        phase="scan",
        status="failed",
        finished_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.flush()

    rows = [
        ("https://vaga.lt/a", "request_error:TimeoutError", None),
        ("https://vaga.lt/b", "request_error:TimeoutError", 503),
        ("https://vaga.lt/c", "request_error:TimeoutError", 504),
        ("https://vaga.lt/d", "http_404", 404),
        ("https://vaga.lt/e", None, None),
    ]
    items: list[ScrapeUrlItem] = []
    for url, _reason, http in rows:
        # PR 3: scrape_url_items.error_reason was dropped. Failure detail
        # lives in scrape_failures only.
        item = ScrapeUrlItem(
            run_id=run.id,
            shop_id=shop_id,
            url=url,
            url_type="product",
            status="failed",
            http_status=http,
        )
        db_session.add(item)
        items.append(item)
    db_session.flush()
    # Mirror what production does on a real failure: record the event.
    # PR 2 of the scrape-failures migration reads from this table for the
    # failure card / URL filter / retry, so the fixture must populate it.
    for item, (_, reason, http) in zip(items, rows, strict=True):
        db_session.add(
            ScrapeFailure(
                scrape_url_item_id=item.id,
                run_id=run.id,
                shop_id=shop_id,
                url=item.url,
                error_reason=reason,
                http_status=http,
            )
        )
    db_session.commit()
    return run


def _urls(client: TestClient, run_id: int, **params: object) -> list[str]:
    resp = client.get(f"/api/runs/{run_id}/urls", params=params)
    assert resp.status_code == 200, resp.text
    return [r["url"] for r in resp.json()["rows"]]


@pytest.mark.integration
def test_run_urls_filter_by_reason(client: TestClient, db_session: Session) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)

    # Status=failed alone returns all five.
    assert set(_urls(client, run.id, status="failed")) == {
        "https://vaga.lt/a",
        "https://vaga.lt/b",
        "https://vaga.lt/c",
        "https://vaga.lt/d",
        "https://vaga.lt/e",
    }

    # Reason without http_status: three Timeout rows (NULL/503/504).
    assert set(
        _urls(
            client,
            run.id,
            status="failed",
            error_reason="request_error:TimeoutError",
        )
    ) == {"https://vaga.lt/a", "https://vaga.lt/b", "https://vaga.lt/c"}


@pytest.mark.integration
def test_run_urls_filter_by_reason_and_http(
    client: TestClient, db_session: Session
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)

    # Same reason narrowed to http=503 — must NOT include the 504 row.
    assert _urls(
        client,
        run.id,
        status="failed",
        error_reason="request_error:TimeoutError",
        http_status=503,
    ) == ["https://vaga.lt/b"]

    # Same reason narrowed to http_status_is_null — only the no-response row.
    assert _urls(
        client,
        run.id,
        status="failed",
        error_reason="request_error:TimeoutError",
        http_status_is_null="true",
    ) == ["https://vaga.lt/a"]


@pytest.mark.integration
def test_run_urls_filter_by_reason_is_null(
    client: TestClient, db_session: Session
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)

    assert _urls(
        client,
        run.id,
        status="failed",
        error_reason_is_null="true",
    ) == ["https://vaga.lt/e"]


@pytest.mark.integration
def test_run_urls_includes_shop_book_id(
    client: TestClient, db_session: Session
) -> None:
    """Live rows expose shop_book_id (int when ShopBook(shop_id, url) matches,
    None otherwise) so the run-history card can deep-link to the book page."""
    from datetime import UTC, datetime

    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = ScrapeRun(
        shop_id=shop.id,
        phase="scan",
        status="completed",
        finished_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.flush()

    matched_url = "https://vaga.lt/matched-book"
    unmatched_url = "https://vaga.lt/no-book"

    book = ShopBook(
        shop_id=shop.id,
        url=matched_url,
        title="Matched Book",
    )
    db_session.add(book)
    db_session.flush()

    db_session.add_all(
        [
            ScrapeUrlItem(
                run_id=run.id,
                shop_id=shop.id,
                url=matched_url,
                url_type="product",
                status="done",
            ),
            ScrapeUrlItem(
                run_id=run.id,
                shop_id=shop.id,
                url=unmatched_url,
                url_type="product",
                status="done",
            ),
        ]
    )
    db_session.commit()

    resp = client.get(f"/api/runs/{run.id}/urls")
    assert resp.status_code == 200, resp.text
    rows = {r["url"]: r for r in resp.json()["rows"]}

    assert rows[matched_url]["shop_book_id"] == book.id
    assert rows[matched_url]["title"] == "Matched Book"
    assert rows[unmatched_url]["shop_book_id"] is None
    assert rows[unmatched_url]["title"] is None
    # discovered_url_id remains in the payload (existing contract).
    assert "discovered_url_id" in rows[matched_url]


@pytest.mark.integration
def test_run_live_failure_groups_payload_shape(
    client: TestClient, db_session: Session
) -> None:
    """failure_groups gains explicit null-flag keys so the frontend can
    deep-link without string-sentinel ambiguity."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)

    resp = client.get(f"/api/runs/{run.id}/live")
    assert resp.status_code == 200, resp.text
    groups = resp.json()["failure_groups"]
    by_key = {(g["reason"], g["http"]): g for g in groups}

    null_reason = by_key[(None, None)]
    assert null_reason["reason_is_null"] is True
    assert null_reason["http_is_null"] is True
    assert null_reason["reason_display"] == "unknown"

    timeout_503 = by_key[("request_error:TimeoutError", 503)]
    assert timeout_503["reason_is_null"] is False
    assert timeout_503["http_is_null"] is False
    assert timeout_503["reason_display"] == "request_error:TimeoutError"

    timeout_null_http = by_key[("request_error:TimeoutError", None)]
    assert timeout_null_http["reason_is_null"] is False
    assert timeout_null_http["http_is_null"] is True


@pytest.mark.integration
def test_failure_groups_drop_retried_and_succeeded(
    client: TestClient, db_session: Session
) -> None:
    """A URL that failed, was retried, and succeeded must disappear from
    the failure card — the card answers "what is failed right now", not
    "what failed at any point in this run". The append-only event log
    keeps the history; the card filters on current queue state."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)

    # Flip /b (the http_503 row) to `done` — operator retried and it worked.
    db_session.query(ScrapeUrlItem).filter(
        ScrapeUrlItem.run_id == run.id,
        ScrapeUrlItem.url == "https://vaga.lt/b",
    ).update({"status": "done"})
    db_session.commit()

    resp = client.get(f"/api/runs/{run.id}/live")
    assert resp.status_code == 200, resp.text
    groups = resp.json()["failure_groups"]
    by_key = {(g["reason"], g["http"]): g["count"] for g in groups}

    # The 503 bucket no longer has a `failed` queue row — must be gone.
    assert ("request_error:TimeoutError", 503) not in by_key
    # The other Timeout buckets (NULL / 504) still show one failure each.
    assert by_key[("request_error:TimeoutError", None)] == 1
    assert by_key[("request_error:TimeoutError", 504)] == 1


@pytest.mark.integration
def test_failure_groups_recurring_in_runs_counts_prior_runs(
    client: TestClient, db_session: Session
) -> None:
    """`recurring_in_runs` is a status-blind historical count: how many
    of the last N prior runs (same shop) had ≥1 failure in this bucket."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()

    # Two prior runs with the http_404 bucket failing.
    from datetime import UTC, datetime, timedelta

    base = datetime.now(UTC) - timedelta(hours=2)
    for i, started in enumerate([base, base + timedelta(minutes=30)], start=1):
        prior = ScrapeRun(
            shop_id=shop.id,
            phase="scan",
            status="completed",
            started_at=started,
            finished_at=started + timedelta(minutes=10),
        )
        db_session.add(prior)
        db_session.flush()
        item = ScrapeUrlItem(
            run_id=prior.id,
            shop_id=shop.id,
            url=f"https://vaga.lt/historical-{i}",
            url_type="product",
            status="failed",
            http_status=404,
        )
        db_session.add(item)
        db_session.flush()
        db_session.add(
            ScrapeFailure(
                scrape_url_item_id=item.id,
                run_id=prior.id,
                shop_id=shop.id,
                url=item.url,
                error_reason="http_404",
                http_status=404,
            )
        )
    db_session.commit()

    # Current run with the same bucket.
    current = _make_run_with_failures(db_session, shop.id)

    resp = client.get(f"/api/runs/{current.id}/live")
    assert resp.status_code == 200, resp.text
    groups = resp.json()["failure_groups"]
    by_key = {(g["reason"], g["http"]): g for g in groups}

    http_404 = by_key[("http_404", 404)]
    assert http_404["recurring_in_runs"] == 2
    # The other buckets in the current run had no prior occurrences.
    timeout_503 = by_key[("request_error:TimeoutError", 503)]
    assert timeout_503["recurring_in_runs"] == 0


@pytest.mark.integration
def test_api_issues_kind_all_unions_validation_and_scrape_failures(
    client: TestClient, db_session: Session
) -> None:
    """`/api/issues?kind=all` (default) returns both `validation_issues`
    and `scrape_failures` rows, each carrying its `kind` field."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)
    # Add a validation issue on the same run for cross-source coverage.
    db_session.add(
        ValidationIssue(
            scrape_run_id=run.id,
            url="https://vaga.lt/v1",
            field="price",
            issue="missing_price",
            raw_value=None,
        )
    )
    db_session.commit()

    resp = client.get("/api/issues", params={"run_id": run.id, "kind": "all"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    kinds = {i["kind"] for i in body["issues"]}
    assert "validation" in kinds
    assert "scrape_failure" in kinds
    # The 503 row is a useful representative scrape_failure: both fields set.
    sf_503 = next(
        i
        for i in body["issues"]
        if i["kind"] == "scrape_failure" and i["url"] == "https://vaga.lt/b"
    )
    val = next(i for i in body["issues"] if i["kind"] == "validation")
    assert sf_503["error_reason"] == "request_error:TimeoutError"
    assert sf_503["http_status"] == 503
    # Validation rows omit transport keys.
    assert val["error_reason"] is None
    assert val["http_status"] is None


@pytest.mark.integration
def test_api_issues_kind_scrape_failure_excludes_validation(
    client: TestClient, db_session: Session
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)
    db_session.add(
        ValidationIssue(
            scrape_run_id=run.id,
            url="https://vaga.lt/v2",
            field="price",
            issue="missing_price",
            raw_value=None,
        )
    )
    db_session.commit()

    resp = client.get(
        "/api/issues", params={"run_id": run.id, "kind": "scrape_failure"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    kinds = {i["kind"] for i in body["issues"]}
    assert kinds == {"scrape_failure"}
    # No `missing_price` validation row should appear.
    assert all(i["issue"] != "missing_price" for i in body["issues"])


@pytest.mark.integration
def test_api_issues_severity_classifier_handles_per_status_reasons(
    client: TestClient, db_session: Session
) -> None:
    """`error_reason='http_503'` (per-status, today's actual writes) must
    classify as the http_5xx bucket = warning, via http_status range."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)

    resp = client.get(
        "/api/issues", params={"run_id": run.id, "kind": "scrape_failure"}
    )
    assert resp.status_code == 200, resp.text
    by_url = {i["url"]: i for i in resp.json()["issues"]}
    # 503 → warning (http range)
    assert by_url["https://vaga.lt/b"]["severity"] == "warning"
    # 504 → warning (http range)
    assert by_url["https://vaga.lt/c"]["severity"] == "warning"
    # 404 → warning (http range)
    assert by_url["https://vaga.lt/d"]["severity"] == "warning"
    # request_error:TimeoutError, http_status NULL → critical (prefix)
    assert by_url["https://vaga.lt/a"]["severity"] == "critical"
    # NULL reason, NULL http → default warning
    assert by_url["https://vaga.lt/e"]["severity"] == "warning"


@pytest.mark.integration
def test_acknowledge_run_failures_flips_lifecycle(
    client: TestClient, db_session: Session
) -> None:
    """POST /failures/ack flips matching scrape_failures.lifecycle_state
    to `already_seen`, sets `acknowledged_at`, and records the note."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)

    resp = client.post(
        f"/api/runs/{run.id}/failures/ack",
        params={
            "error_reason": "request_error:TimeoutError",
            "http_status": 503,
            "note": "vendor outage 2026-04-28",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["acknowledged"] == 1
    assert body["run_id"] == run.id

    db_session.expire_all()
    rows = (
        db_session.query(ScrapeFailure)
        .filter(
            ScrapeFailure.run_id == run.id,
            ScrapeFailure.error_reason == "request_error:TimeoutError",
            ScrapeFailure.http_status == 503,
        )
        .all()
    )
    assert all(r.lifecycle_state == "already_seen" for r in rows)
    assert all(r.acknowledged_at is not None for r in rows)
    assert all(r.acknowledged_note == "vendor outage 2026-04-28" for r in rows)
    # Other buckets untouched.
    other = (
        db_session.query(ScrapeFailure)
        .filter(
            ScrapeFailure.run_id == run.id,
            ScrapeFailure.error_reason == "http_404",
        )
        .one()
    )
    assert other.lifecycle_state == "new"


@pytest.mark.integration
def test_acknowledge_run_failures_no_match_returns_400(
    client: TestClient, db_session: Session
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)

    resp = client.post(
        f"/api/runs/{run.id}/failures/ack",
        params={"error_reason": "no_such_reason"},
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_acknowledge_run_failures_404_when_missing(client: TestClient) -> None:
    resp = client.post("/api/runs/999999999/failures/ack")
    assert resp.status_code == 404


@pytest.mark.integration
def test_acknowledged_bucket_disappears_from_failure_card(
    client: TestClient, db_session: Session
) -> None:
    """End-to-end: ack a bucket, then re-fetch /api/runs/{id}/live and
    confirm the bucket is no longer surfaced."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)

    before = client.get(f"/api/runs/{run.id}/live").json()["failure_groups"]
    assert any(g["http"] == 404 for g in before)

    resp = client.post(
        f"/api/runs/{run.id}/failures/ack",
        params={"error_reason": "http_404", "http_status": 404},
    )
    assert resp.status_code == 200, resp.text

    after = client.get(f"/api/runs/{run.id}/live").json()["failure_groups"]
    assert all(g["http"] != 404 for g in after)


@pytest.mark.integration
def test_failure_groups_hides_acknowledged_by_default(
    client: TestClient, db_session: Session
) -> None:
    """Marking a bucket's latest event as `already_seen` removes it from
    the failure card unless the caller opts in."""
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)

    # Acknowledge the http_404 bucket.
    db_session.query(ScrapeFailure).filter(
        ScrapeFailure.run_id == run.id,
        ScrapeFailure.error_reason == "http_404",
    ).update({"lifecycle_state": "already_seen"}, synchronize_session=False)
    db_session.commit()

    resp = client.get(f"/api/runs/{run.id}/live")
    assert resp.status_code == 200, resp.text
    groups = resp.json()["failure_groups"]
    keys = {(g["reason"], g["http"]) for g in groups}
    assert ("http_404", 404) not in keys
    # The other buckets still show.
    assert ("request_error:TimeoutError", 503) in keys


# ── /api/runs/{id}/retry ───────────────────────────────────────────────────


def _retry_run_status(run: ScrapeRun, db_session: Session, status: str) -> None:
    """Force-set the run to the given status so we exercise both the
    alive-no-spawn and terminal-spawn branches of /retry."""
    run.status = status
    if status in ("failed", "completed"):
        run.close_reason = "test"
        from datetime import UTC
        from datetime import datetime as _dt

        run.finished_at = _dt.now(UTC)
    db_session.commit()


@pytest.mark.integration
def test_retry_run_filtered_alive_no_spawn(
    client: TestClient, db_session: Session, _mock_spawn: list[dict]
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)
    _retry_run_status(run, db_session, "running")

    resp = client.post(
        f"/api/runs/{run.id}/retry",
        params={"error_reason": "request_error:TimeoutError", "http_status": 503},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["retried"] == 1
    assert body["spawned"] is False
    assert body["run_status"] == "running"

    # The flipped row is now `pending` with cleared error fields. The
    # other Timeout rows (NULL / 504) and unrelated buckets stay failed.
    db_session.expire_all()
    rows = (
        db_session.query(ScrapeUrlItem)
        .filter(ScrapeUrlItem.run_id == run.id)
        .order_by(ScrapeUrlItem.id)
        .all()
    )
    by_url = {r.url: r for r in rows}
    flipped = by_url["https://vaga.lt/b"]
    assert flipped.status == "pending"
    # error_reason column dropped in PR 3; failure history stays in
    # scrape_failures (append-only) — retry doesn't delete events.
    assert flipped.http_status is None
    # Same-reason / different-http buckets must NOT be touched.
    assert by_url["https://vaga.lt/a"].status == "failed"
    assert by_url["https://vaga.lt/c"].status == "failed"
    assert by_url["https://vaga.lt/d"].status == "failed"
    assert _mock_spawn == []  # alive run — no respawn


@pytest.mark.integration
def test_retry_run_terminal_respawns(
    client: TestClient, db_session: Session, _mock_spawn: list[dict]
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)
    _retry_run_status(run, db_session, "failed")

    resp = client.post(f"/api/runs/{run.id}/retry")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # All five failed rows reset.
    assert body["retried"] == 5
    assert body["spawned"] is True
    assert body["run_status"] == "running"

    db_session.expire_all()
    refreshed = db_session.get(ScrapeRun, run.id)
    assert refreshed is not None
    assert refreshed.status == "running"
    assert refreshed.close_reason is None
    assert refreshed.finished_at is None
    pending = (
        db_session.query(ScrapeUrlItem)
        .filter(ScrapeUrlItem.run_id == run.id, ScrapeUrlItem.status == "pending")
        .count()
    )
    assert pending == 5
    assert _mock_spawn == [
        {"phase": "scan", "shop": "vaga", "strategy": "", "mode": "delta"}
    ]


@pytest.mark.integration
def test_retry_run_no_match_returns_400(
    client: TestClient, db_session: Session, _mock_spawn: list[dict]
) -> None:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").one()
    run = _make_run_with_failures(db_session, shop.id)
    _retry_run_status(run, db_session, "failed")

    resp = client.post(
        f"/api/runs/{run.id}/retry",
        params={"error_reason": "no_such_reason"},
    )
    assert resp.status_code == 400
    # Run state must be untouched on a no-match retry.
    db_session.expire_all()
    refreshed = db_session.get(ScrapeRun, run.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert _mock_spawn == []


@pytest.mark.integration
def test_retry_run_404_when_missing(client: TestClient) -> None:
    resp = client.post("/api/runs/999999999/retry")
    assert resp.status_code == 404


@pytest.mark.integration
def test_api_cron_exposes_chain_to_id(client: TestClient, db_session: Session) -> None:
    from book_scraper.db.repo import create_cron_job, upsert_shop

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job_a = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *",
    )
    job_b = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *",
        chain_to_job_id=job_a.id,
    )
    db_session.commit()

    resp = client.get("/api/cron")
    assert resp.status_code == 200
    jobs = {j["id"]: j for j in resp.json()["jobs"]}

    assert jobs[job_a.id]["chain_to_id"] is None
    assert jobs[job_b.id]["chain_to_id"] == job_a.id
    assert jobs[job_b.id]["chain_to_name"] is not None


@pytest.mark.integration
def test_api_cron_create_with_chain(client: TestClient, db_session: Session) -> None:
    from book_scraper.db.repo import create_cron_job, get_cron_job, upsert_shop

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job_a = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *",
    )
    db_session.commit()

    resp = client.post(
        "/api/cron",
        json={
            "shop": "vaga",
            "phase": "scan",
            "strategy": "",
            "cron_expression": "0 3 * * *",
            "chain_to_id": job_a.id,
        },
    )
    assert resp.status_code == 200
    new_id = resp.json()["id"]

    db_session.expire_all()
    saved = get_cron_job(db_session, new_id)
    assert saved.chain_to_job_id == job_a.id


def test_api_run_detail_exposes_restarted_event(
    client: TestClient, db_session: Session
) -> None:
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.repo import (
        create_scrape_run,
        emit_scrape_run_event,
        upsert_shop,
    )

    shop = upsert_shop(db_session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(db_session, shop.id, "scan")
    emit_scrape_run_event(
        db_session,
        run.id,
        run_event_types.RESTARTED,
        payload={
            "previous_close_reason": "stall_timeout",
            "attempt": 1,
            "urls_processed_snapshot": 0,
        },
        actor=run_event_types.ACTOR_SYSTEM,
    )
    db_session.commit()

    response = client.get(f"/api/runs/{run.id}")
    assert response.status_code == 200
    data = response.json()
    event_types = [e["event_type"] for e in data["events"]]
    assert "restarted" in event_types
    restarted = next(e for e in data["events"] if e["event_type"] == "restarted")
    assert restarted["payload"]["attempt"] == 1
    assert restarted["payload"]["previous_close_reason"] == "stall_timeout"
