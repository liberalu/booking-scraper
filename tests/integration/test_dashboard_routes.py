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
from book_scraper.db.models import Shop, ShopBook


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


ROUTES = [
    "/",
    "/shops",
    "/shops/vaga",
    "/shops/vaga/not-listed",
    "/runs",
    "/validation",
    "/shop-books",
    # Filter combinations
    "/shop-books?active=true",
    "/shop-books?has_isbn=true",
    "/shop-books?shop=vaga",
    "/shop-books?type=book",
    # Sorting
    "/runs?sort=started_at&order=desc",
    "/runs?sort=id&order=asc",
    "/shop-books?sort=title&order=asc",
    "/shop-books?sort=price&order=desc",
    "/shop-books?sort=type&order=asc",
    "/shops/vaga?sort=started_at&order=desc",
]


@pytest.mark.integration
@pytest.mark.parametrize("route", ROUTES)
def test_route_returns_200(client: TestClient, route: str) -> None:
    response = client.get(route)
    assert response.status_code == 200, f"{route} returned {response.status_code}"


@pytest.mark.integration
def test_nonexistent_shop_returns_404(client: TestClient) -> None:
    response = client.get("/shops/nonexistent")
    assert response.status_code == 404


VALIDATION_ROUTES = [
    "/validation",
    "/validation?state=open",
    "/validation?state=new",
    "/validation?state=recurring",
    "/validation?state=already_seen",
    "/validation?state=all",
    "/validation?shop=vaga",
    "/validation?issue_type=missing_price",
    "/validation?run_id=1",
    "/validation?q=test",
    "/validation?shop=vaga&issue_type=missing_price&run_id=1&q=a",
    "/validation?order=asc",
    "/validation?page=2",
    "/validation?page=9999",  # out-of-range page clamps silently
]


@pytest.mark.integration
@pytest.mark.parametrize("route", VALIDATION_ROUTES)
def test_validation_routes_return_200(client: TestClient, route: str) -> None:
    response = client.get(route)
    assert response.status_code == 200, f"{route} returned {response.status_code}"


@pytest.mark.integration
def test_legacy_validation_detail_route_is_gone(client: TestClient) -> None:
    response = client.get("/validation/missing_price")
    assert response.status_code == 404


@pytest.mark.integration
def test_acknowledge_all_accepts_full_filter_set(client: TestClient) -> None:
    response = client.post(
        "/validation-issues/acknowledge-all",
        data={
            "issue_type": "missing_price",
            "state": "open",
            "shop": "",
            "run_id": "",
            "q": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.mark.integration
def test_delete_matching_requires_filter(client: TestClient) -> None:
    # state='all' + every other filter empty = truly unfiltered;
    # repo raises, route returns 400
    response = client.post(
        "/validation-issues/delete-matching",
        data={"issue_type": "", "state": "all", "shop": "", "run_id": "", "q": ""},
        follow_redirects=False,
    )
    assert response.status_code == 400


@pytest.mark.integration
def test_shop_book_detail_shows_classification_score(
    client: TestClient, db_session: Session
) -> None:
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

    response = client.get(f"/shop-books/{shop_book.id}")

    assert response.status_code == 200
    assert "Classification Score" in response.text
    assert "non_book" in response.text
    assert "-4" in response.text
    assert "-4 non-book categories" in response.text


@pytest.mark.integration
def test_url_detail_page_404(client: TestClient) -> None:
    """Non-existent URL ID returns 404."""
    response = client.get("/urls/999999")
    assert response.status_code == 404


@pytest.mark.integration
def test_url_detail_page_exists(client: TestClient, db_session: Session) -> None:
    """An existing DiscoveredUrl returns 200 on its detail page."""
    from book_scraper.db.repo import upsert_discovered_url, upsert_shop

    shop = upsert_shop(db_session, "smoke_shop", "https://smoke.example.com")
    url = upsert_discovered_url(
        db_session, shop.id, "https://smoke.example.com/p/1", "sitemap"
    )
    db_session.commit()

    response = client.get(f"/urls/{url.id}")
    assert response.status_code == 200
    assert "Not yet classified" in response.text
