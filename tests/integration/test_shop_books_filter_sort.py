"""Verify the /shop-books page composes filters and sort instead of resetting
one when the other changes."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db
from book_scraper.db.models import Shop, ShopBook


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _seed(db_session: Session) -> None:
    shop = db_session.query(Shop).filter_by(name="vaga").first()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt")
        db_session.add(shop)
        db_session.flush()
    if db_session.query(ShopBook).filter_by(shop_id=shop.id).count() == 0:
        db_session.add_all(
            [
                ShopBook(
                    shop_id=shop.id,
                    url=f"https://vaga.lt/t-{i}",
                    title=f"Title {i}",
                    price=i,
                )
                for i in range(1, 4)
            ]
        )
        db_session.flush()


def test_filter_form_preserves_active_sort(client: TestClient) -> None:
    """When a sort is active, the filter form must carry it as a hidden
    input so submitting the filter doesn't reset the sort."""
    html = client.get("/shop-books?sort=title&order=asc").text
    assert 'name="sort" value="title"' in html
    assert 'name="order" value="asc"' in html


def test_sort_header_preserves_filters(client: TestClient) -> None:
    """Clicking a sort header must carry the filter query params so it
    doesn't clear the current filter."""
    html = client.get("/shop-books?shop=vaga&active=true").text
    # Any sort header anchor on the page should include shop= and active=
    # as part of base_params before sort=.
    assert "shop=vaga" in html
    assert "active=true" in html
    # And the sort column anchors exist.
    assert "sort=title" in html


def test_filter_badge_remove_preserves_sort(client: TestClient) -> None:
    """The ✕ on a filter badge drops only that filter, not the sort."""
    import re

    # active=all puts up the "All statuses" badge; shop=vaga puts up the
    # shop badge. Active=true is the default and renders no badge.
    html = client.get("/shop-books?shop=vaga&active=all&sort=price&order=desc").text
    badge_hrefs = re.findall(r'filter-badge[^<]*<a href="([^"]*)"', html, re.DOTALL)
    assert len(badge_hrefs) == 2, badge_hrefs
    for href in badge_hrefs:
        assert "sort=price" in href
        assert "order=desc" in href


def test_reset_preserves_sort(client: TestClient) -> None:
    """Reset clears filters but keeps the sort per task spec."""
    import re

    html = client.get("/shop-books?shop=vaga&sort=price&order=desc").text
    # Reset button is the secondary link with role="button" pointing
    # back at /shop-books — must carry the active sort.
    reset_hrefs = re.findall(
        r'href="([^"]*)"[^>]*role="button" class="secondary"', html
    )
    assert reset_hrefs, "Reset button not found"
    assert "sort=price" in reset_hrefs[0]
    assert "order=desc" in reset_hrefs[0]


def test_both_applied_together(client: TestClient) -> None:
    """Sanity: the server does filter+sort in one request without error."""
    resp = client.get("/shop-books?shop=vaga&active=true&sort=price&order=desc")
    assert resp.status_code == 200
