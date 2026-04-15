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
from book_scraper.db.models import Shop


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
    "/listings",
    # Filter combinations
    "/listings?active=true",
    "/listings?has_isbn=true",
    "/listings?shop=vaga",
    # Sorting
    "/runs?sort=started_at&order=desc",
    "/runs?sort=id&order=asc",
    "/listings?sort=title&order=asc",
    "/listings?sort=price&order=desc",
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
