from datetime import UTC, datetime

from sqlalchemy.orm import Session

from book_scraper.db.models import UrlClassification
from book_scraper.db.repo import (
    upsert_discovered_url,
    upsert_shop,
    upsert_url_classification,
)


def test_upsert_creates_classification(db_session: Session):
    """Test that upsert_url_classification creates a new classification record."""
    shop = upsert_shop(db_session, name="test_shop", base_url="https://example.com")
    discovered_url = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://example.com/p/1", source="sitemap"
    )
    db_session.flush()

    upsert_url_classification(
        db_session,
        discovered_url_id=discovered_url.id,
        book_score=7,
        is_book_product=True,
        reasons=["+3 valid ISBN", "+2 author present"],
    )
    db_session.flush()

    row = (
        db_session.query(UrlClassification)
        .filter_by(discovered_url_id=discovered_url.id)
        .one()
    )
    assert row.book_score == 7
    assert row.is_book_product is True
    assert row.reasons == ["+3 valid ISBN", "+2 author present"]
    assert isinstance(row.classified_at, datetime)


def test_upsert_overwrites_on_rescan(db_session: Session):
    """Test that upsert_url_classification overwrites existing record on rescan."""
    shop = upsert_shop(db_session, name="test_shop", base_url="https://example.com")
    discovered_url = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://example.com/p/1", source="sitemap"
    )
    db_session.flush()

    upsert_url_classification(
        db_session,
        discovered_url_id=discovered_url.id,
        book_score=7,
        is_book_product=True,
        reasons=["+3 valid ISBN"],
    )
    db_session.flush()

    # Capture time before second upsert
    before_second_upsert = datetime.now(UTC)

    upsert_url_classification(
        db_session,
        discovered_url_id=discovered_url.id,
        book_score=-2,
        is_book_product=False,
        reasons=["-4 non-book categories"],
    )
    db_session.flush()

    rows = (
        db_session.query(UrlClassification)
        .filter_by(discovered_url_id=discovered_url.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].book_score == -2
    assert rows[0].is_book_product is False
    assert rows[0].reasons == ["-4 non-book categories"]
    assert rows[0].classified_at >= before_second_upsert


def test_relationship_accessible(db_session: Session):
    """Verify the ORM relationship between DiscoveredUrl and UrlClassification."""
    shop = upsert_shop(db_session, name="test_shop", base_url="https://example.com")
    discovered_url = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://example.com/p/1", source="sitemap"
    )
    db_session.flush()

    upsert_url_classification(
        db_session,
        discovered_url_id=discovered_url.id,
        book_score=5,
        is_book_product=True,
        reasons=["+3 valid ISBN"],
    )
    db_session.flush()
    db_session.refresh(discovered_url)

    assert discovered_url.classification is not None
    assert discovered_url.classification.book_score == 5
    assert discovered_url.classification.is_book_product is True
    assert discovered_url.classification.reasons == ["+3 valid ISBN"]
