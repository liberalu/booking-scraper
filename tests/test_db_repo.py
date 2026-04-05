from decimal import Decimal

from book_scraper.db.repo import insert_price, upsert_listing, upsert_shop


def test_upsert_shop_creates_new(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    assert shop.id is not None
    assert shop.name == "vaga"
    assert shop.base_url == "https://vaga.lt"


def test_upsert_shop_returns_existing(db_session):
    shop1 = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    shop2 = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    assert shop1.id == shop2.id


def test_upsert_listing_creates_new(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    listing = upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/test-book",
        title="Test Book",
        author="Author",
        isbn_from_shop="9781234567890",
    )
    assert listing.id is not None
    assert listing.title == "Test Book"
    assert listing.match_status == "unmatched"
    assert listing.is_active is True


def test_upsert_listing_updates_existing(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    listing1 = upsert_listing(
        db_session, shop_id=shop.id, url="https://vaga.lt/book", title="Old"
    )
    listing2 = upsert_listing(
        db_session, shop_id=shop.id, url="https://vaga.lt/book", title="New"
    )
    assert listing1.id == listing2.id
    assert listing2.title == "New"


def test_insert_price(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    listing = upsert_listing(
        db_session, shop_id=shop.id, url="https://vaga.lt/book", title="Book"
    )
    price = insert_price(
        db_session,
        listing_id=listing.id,
        price=Decimal("9.99"),
        price_original=Decimal("14.99"),
        in_stock=True,
    )
    assert price.id is not None
    assert price.price == Decimal("9.99")
    assert price.price_original == Decimal("14.99")
