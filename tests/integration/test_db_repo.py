from decimal import Decimal

from book_scraper.db.repo import insert_price, upsert_shop, upsert_shop_book


def test_upsert_shop_creates_new(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    assert shop.id is not None
    assert shop.name == "vaga"
    assert shop.base_url == "https://vaga.lt"


def test_upsert_shop_returns_existing(db_session):
    shop1 = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    shop2 = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    assert shop1.id == shop2.id


def test_upsert_shop_book_creates_new(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    shop_book, *_ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/test-book",
        title="Test Book",
        author="Author",
        isbn="9781234567890",
    )
    assert shop_book.id is not None
    assert shop_book.title == "Test Book"
    assert shop_book.match_status == "unmatched"
    assert shop_book.is_active is True


def test_upsert_shop_book_updates_existing(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    shop_book1, *_ = upsert_shop_book(
        db_session, shop_id=shop.id, url="https://vaga.lt/book", title="Old"
    )
    shop_book2, *_ = upsert_shop_book(
        db_session, shop_id=shop.id, url="https://vaga.lt/book", title="New"
    )
    assert shop_book1.id == shop_book2.id
    assert shop_book2.title == "New"


def test_insert_price(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    shop_book, *_ = upsert_shop_book(
        db_session, shop_id=shop.id, url="https://vaga.lt/book", title="Book"
    )
    price = insert_price(
        db_session,
        shop_book_id=shop_book.id,
        price=Decimal("9.99"),
        price_original=Decimal("14.99"),
        in_stock=True,
    )
    assert price.id is not None
    assert price.price == Decimal("9.99")
    assert price.price_original == Decimal("14.99")
