"""Regression for the shop_books slash/no-slash duplicate bug.

LupaSearch returns product URLs with a trailing slash; the GraphQL parser
builds them from `f"{base}/{url_key}"` (no trailing slash). Pre-fix,
``upsert_shop_book`` matched on the raw URL string, so a single book
ended up with two rows — one per parser. On pegasas this affected
~10,785 books (~21,570 rows) before the cleanup.

The fix: normalise the URL via ``url_utils.normalize_url`` at the top of
``upsert_shop_book`` so both lookup and persistence use the canonical
form.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from book_scraper.db.models import ShopBook
from book_scraper.db.repo import upsert_shop, upsert_shop_book


@pytest.fixture
def shop_id(db_session: Session) -> int:
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    db_session.flush()
    return shop.id


@pytest.mark.integration
def test_trailing_slash_variant_does_not_create_duplicate(
    db_session: Session, shop_id: int
) -> None:
    """First call creates the row. Second call with the trailing-slash
    variant of the same URL must return the SAME row, not create a new
    one. Mirrors the LupaSearch (with slash) → GraphQL (without slash)
    sequence that produced 21,570 dupes on pegasas."""
    sb1, created1, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop_id,
        url="https://vaga.lt/some-book-1234",  # GraphQL shape
        title="Test Book",
    )
    db_session.flush()
    assert created1 is True

    sb2, created2, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop_id,
        url="https://vaga.lt/some-book-1234/",  # LupaSearch shape
        title="Test Book",
    )
    db_session.flush()
    assert created2 is False
    assert sb2.id == sb1.id

    # Only one row in the DB for this book.
    rows = (
        db_session.query(ShopBook)
        .filter(ShopBook.shop_id == shop_id)
        .filter(ShopBook.url.like("%some-book-1234%"))
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
def test_url_stored_without_trailing_slash(
    db_session: Session, shop_id: int
) -> None:
    """The persisted URL is the canonical form (no trailing slash) even
    when the caller passed the trailing-slash variant first."""
    sb, _, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop_id,
        url="https://vaga.lt/another-book-5678/",
        title="Another Book",
    )
    db_session.flush()
    assert sb.url == "https://vaga.lt/another-book-5678"


@pytest.mark.integration
def test_tracking_params_stripped_for_dedup(
    db_session: Session, shop_id: int
) -> None:
    """``normalize_url`` also drops tracking params (utm_*, fbclid, …).
    A second call with a tracking-tagged variant of the same URL must
    map to the original row."""
    sb1, created1, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop_id,
        url="https://vaga.lt/utm-book-9999",
        title="UTM Book",
    )
    db_session.flush()
    assert created1 is True

    sb2, created2, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop_id,
        url="https://vaga.lt/utm-book-9999?utm_source=newsletter",
        title="UTM Book",
    )
    db_session.flush()
    assert created2 is False
    assert sb2.id == sb1.id


@pytest.mark.integration
def test_sku_match_keeps_row_when_url_changes(
    db_session: Session, shop_id: int
) -> None:
    """SKU is the durable identifier on shops that expose one
    (pegasas's Magento SKU survives slug renames). A URL change for
    the same SKU must update the existing row's ``url`` rather than
    creating a new row.

    This is the bug pattern observed on vaga where the same product
    appeared at both the short slug URL (sitemap) and the full
    category-path URL (full_crawl) — pre-fix produced two rows."""
    sb1, created1, _, changes1 = upsert_shop_book(
        db_session,
        shop_id=shop_id,
        url="https://vaga.lt/short-slug-1234",
        title="SKU Test Book",
        sku="000000000001234567",
    )
    db_session.flush()
    assert created1 is True

    # Same SKU, different URL — simulate slug rename or category-path
    # variant landing in a later run.
    sb2, created2, _, changes2 = upsert_shop_book(
        db_session,
        shop_id=shop_id,
        url="https://vaga.lt/category/sub/short-slug-1234",
        title="SKU Test Book",
        sku="000000000001234567",
    )
    db_session.flush()
    assert created2 is False
    assert sb2.id == sb1.id
    assert sb2.url == "https://vaga.lt/category/sub/short-slug-1234"
    assert any(c["field"] == "url" for c in changes2)


@pytest.mark.integration
def test_no_sku_falls_back_to_url_match(
    db_session: Session, shop_id: int
) -> None:
    """Vaga's HTML scrape sometimes returns no SKU. In that case the
    upsert must fall back to URL-based matching — preserving the
    original behavior for SKU-less books."""
    sb1, created1, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop_id,
        url="https://vaga.lt/no-sku-book-001",
        title="No SKU Book",
    )
    db_session.flush()
    assert created1 is True

    # Same URL, no SKU — should match the existing row.
    sb2, created2, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop_id,
        url="https://vaga.lt/no-sku-book-001",
        title="No SKU Book",
    )
    db_session.flush()
    assert created2 is False
    assert sb2.id == sb1.id

    # Different URL with no SKU — must create a separate row, not collide.
    sb3, created3, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop_id,
        url="https://vaga.lt/no-sku-book-002",
        title="Different No-SKU Book",
    )
    db_session.flush()
    assert created3 is True
    assert sb3.id != sb1.id
