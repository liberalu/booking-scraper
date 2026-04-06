"""Tests for repo functions not covered by the original test_db_repo.py."""

from decimal import Decimal

import pytest

from book_scraper.db.repo import (
    mark_listings_inactive,
    upsert_category,
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
        listing1 = upsert_listing(
            db_session, shop_id=shop.id, url="https://test.lt/book-1", title="Book 1"
        )
        listing2 = upsert_listing(
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
        listing = upsert_listing(
            db_session,
            shop_id=shop.id,
            url="https://u.lt/book",
            title="Original",
            isbn="123",
            publisher="Pub",
            year=2020,
        )

        updated = upsert_listing(
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
        updated = upsert_listing(
            db_session,
            shop_id=shop.id,
            url="https://m.lt/book",
            title="Book",
            properties={"narrator": "John"},
        )
        assert updated.properties == {"pages": 200, "narrator": "John"}
