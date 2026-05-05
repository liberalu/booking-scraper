"""Tests for created_run_id, get_run_item_counts, and /api/runs/{run_id}/books."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import (
    get_run_item_counts,
)
from book_scraper.db.models import ScrapeRun, Shop, ShopBookChange
from book_scraper.db.repo import upsert_shop, upsert_shop_book


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def shop(db_session: Session) -> Shop:
    return upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")


@pytest.fixture()
def run_a(db_session: Session, shop: Shop) -> ScrapeRun:
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="completed")
    db_session.add(run)
    db_session.flush()
    return run


@pytest.fixture()
def run_b(db_session: Session, shop: Shop) -> ScrapeRun:
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="completed")
    db_session.add(run)
    db_session.flush()
    return run


@pytest.mark.integration
def test_created_run_id_set_on_first_create(
    db_session: Session, shop: Shop, run_a: ScrapeRun
):
    sb, created, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/book-1",
        title="Book One",
        run_id=run_a.id,
    )
    assert created is True
    assert sb.created_run_id == run_a.id
    assert sb.last_run_id == run_a.id


@pytest.mark.integration
def test_created_run_id_not_overwritten_on_rescrape(
    db_session: Session, shop: Shop, run_a: ScrapeRun, run_b: ScrapeRun
):
    upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/book-1",
        title="Book One",
        run_id=run_a.id,
    )
    sb, created, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/book-1",
        title="Book One Updated",
        run_id=run_b.id,
    )
    assert created is False
    assert sb.created_run_id == run_a.id  # immutable
    assert sb.last_run_id == run_b.id  # updated


@pytest.mark.integration
def test_get_run_item_counts_uses_created_run_id(
    db_session: Session, shop: Shop, run_a: ScrapeRun, run_b: ScrapeRun
):
    # Create one book in run_a, re-scrape in run_b
    upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/book-1",
        title="Book One",
        run_id=run_a.id,
    )
    upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/book-1",
        title="Book One v2",
        run_id=run_b.id,
    )

    counts_a = get_run_item_counts(db_session, run_a.id)
    counts_b = get_run_item_counts(db_session, run_b.id)

    # run_a created the book; run_b only updated it
    assert counts_a["items_added"] == 1
    assert counts_b["items_added"] == 0


@pytest.mark.integration
def test_api_run_books_updated(
    client: TestClient, db_session: Session, shop: Shop, run_a: ScrapeRun
):
    sb, _, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/book-2",
        title="Book Two",
        run_id=run_a.id,
    )
    change = ShopBookChange(
        shop_book_id=sb.id,
        scrape_run_id=run_a.id,
        field="price",
        old_value="10.00",
        new_value="9.00",
    )
    db_session.add(change)
    db_session.flush()

    resp = client.get(f"/api/runs/{run_a.id}/books?type=updated")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["books"][0]["id"] == sb.id
    assert "price" in data["books"][0]["changed_fields"]


@pytest.mark.integration
def test_api_run_books_invalid_type(
    client: TestClient, db_session: Session, shop: Shop, run_a: ScrapeRun
):
    resp = client.get(f"/api/runs/{run_a.id}/books?type=invalid")
    assert resp.status_code == 400


@pytest.mark.integration
def test_api_run_books_404_for_missing_run(client: TestClient):
    resp = client.get("/api/runs/99999999/books?type=added")
    assert resp.status_code == 404
