"""Tests for repo functions not covered by the original test_db_repo.py."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from book_scraper.db.repo import (
    check_discover_freshness,
    create_scrape_run,
    finish_scrape_run,
    get_urls_already_scraped,
    mark_listings_inactive,
    update_discovered_url_status,
    upsert_category,
    upsert_discovered_url,
    upsert_listing,
    upsert_shop,
)


@pytest.mark.integration
class TestUpsertCategory:
    def test_creates_new_category(self, db_session):
        cat = upsert_category(db_session, name="Fiction", slug="fiction")
        assert cat.id is not None
        assert cat.name == "Fiction"

    def test_returns_existing_category(self, db_session):
        cat1 = upsert_category(db_session, name="Fiction", slug="fiction")
        cat2 = upsert_category(db_session, name="Fiction", slug="fiction")
        assert cat1.id == cat2.id

    def test_category_with_parent(self, db_session):
        parent = upsert_category(db_session, name="Books", slug="books")
        child = upsert_category(
            db_session, name="Fiction", slug="fiction", parent_id=parent.id
        )
        assert child.parent_id == parent.id


@pytest.mark.integration
class TestMarkListingsInactive:
    def test_marks_missing_urls_inactive(self, db_session):
        shop = upsert_shop(db_session, name="test_shop", base_url="https://test.lt")
        listing1, _, _ = upsert_listing(
            db_session, shop_id=shop.id, url="https://test.lt/book-1", title="Book 1"
        )
        listing2, _, _ = upsert_listing(
            db_session, shop_id=shop.id, url="https://test.lt/book-2", title="Book 2"
        )

        count = mark_listings_inactive(
            db_session, shop_id=shop.id, active_urls={"https://test.lt/book-1"}
        )
        assert count == 1

        db_session.refresh(listing1)
        db_session.refresh(listing2)
        assert listing1.is_active is True
        assert listing2.is_active is False


@pytest.mark.integration
class TestUpsertListingUpdateFields:
    def test_conditional_field_updates(self, db_session):
        """Fields like isbn, publisher, etc. should not be overwritten with None."""
        shop = upsert_shop(db_session, name="update_shop", base_url="https://u.lt")
        listing, _, _ = upsert_listing(
            db_session,
            shop_id=shop.id,
            url="https://u.lt/book",
            title="Original",
            isbn="123",
            publisher="Pub",
            year=2020,
        )

        updated, _, _ = upsert_listing(
            db_session,
            shop_id=shop.id,
            url="https://u.lt/book",
            title="Updated Title",
            price=Decimal("5.00"),
        )

        assert updated.id == listing.id
        assert updated.title == "Updated Title"
        assert updated.isbn == "123"
        assert updated.publisher == "Pub"
        assert updated.year == 2020

    def test_properties_merge(self, db_session):
        shop = upsert_shop(db_session, name="merge_shop", base_url="https://m.lt")
        upsert_listing(
            db_session,
            shop_id=shop.id,
            url="https://m.lt/book",
            title="Book",
            properties={"pages": 200},
        )
        updated, _, _ = upsert_listing(
            db_session,
            shop_id=shop.id,
            url="https://m.lt/book",
            title="Book",
            properties={"narrator": "John"},
        )
        assert updated.properties == {"pages": 200, "narrator": "John"}


@pytest.mark.integration
class TestCheckDiscoverFreshness:
    def test_raises_when_no_discovered_urls(self, db_session):
        shop = upsert_shop(db_session, name="fresh_shop", base_url="https://f.lt")
        with pytest.raises(RuntimeError, match="No discovered URLs"):
            check_discover_freshness(db_session, shop.id, "fresh_shop", {})

    def test_returns_warnings_when_stale(self, db_session):
        shop = upsert_shop(db_session, name="stale_shop", base_url="https://s.lt")
        upsert_discovered_url(db_session, shop.id, "https://s.lt/book", "sitemap")
        run = create_scrape_run(db_session, shop.id, "discover_sitemap")
        finish_scrape_run(db_session, run.id, "completed")
        # Make the run appear old
        db_session.refresh(run)
        run.finished_at = datetime.now(UTC) - timedelta(hours=200)
        db_session.flush()

        config = {"sitemap": {"url": "https://s.lt/sitemap.xml", "max_age_hours": 168}}
        warnings = check_discover_freshness(db_session, shop.id, "stale_shop", config)
        assert len(warnings) == 1
        assert "200h old" in warnings[0]

    def test_returns_empty_when_fresh(self, db_session):
        shop = upsert_shop(db_session, name="ok_shop", base_url="https://ok.lt")
        upsert_discovered_url(db_session, shop.id, "https://ok.lt/book", "sitemap")
        run = create_scrape_run(db_session, shop.id, "discover_sitemap")
        finish_scrape_run(db_session, run.id, "completed")

        config = {"sitemap": {"url": "https://ok.lt/sitemap.xml", "max_age_hours": 168}}
        warnings = check_discover_freshness(db_session, shop.id, "ok_shop", config)
        assert warnings == []

    def test_warns_when_no_completed_run(self, db_session):
        shop = upsert_shop(db_session, name="norun_shop", base_url="https://nr.lt")
        upsert_discovered_url(db_session, shop.id, "https://nr.lt/book", "sitemap")

        config = {"sitemap": {"url": "https://nr.lt/sitemap.xml", "max_age_hours": 168}}
        warnings = check_discover_freshness(db_session, shop.id, "norun_shop", config)
        assert len(warnings) == 1
        assert "No completed" in warnings[0]


@pytest.mark.integration
class TestGetUrlsAlreadyScraped:
    def test_returns_urls_marked_as_product(self, db_session):
        from book_scraper.db.models import DiscoveredUrl

        shop = upsert_shop(db_session, name="scraped_shop", base_url="https://sc.lt")
        upsert_discovered_url(db_session, shop.id, "https://sc.lt/book-1", "sitemap")
        db_session.flush()
        # Look up the actual ID
        url_record = (
            db_session.query(DiscoveredUrl)
            .filter_by(url="https://sc.lt/book-1")
            .first()
        )
        update_discovered_url_status(
            db_session, url_id=url_record.id, http_status=200, url_type="product"
        )
        db_session.flush()

        result = get_urls_already_scraped(db_session, shop.id)
        assert "https://sc.lt/book-1" in result

    def test_returns_empty_when_no_products(self, db_session):
        shop = upsert_shop(db_session, name="empty_shop", base_url="https://e.lt")
        upsert_discovered_url(db_session, shop.id, "https://e.lt/page", "sitemap")

        result = get_urls_already_scraped(db_session, shop.id)
        assert result == set()
