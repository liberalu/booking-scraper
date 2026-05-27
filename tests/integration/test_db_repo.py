from decimal import Decimal

from book_scraper.db.models import Book, BookIsbn
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


def test_upsert_shop_book_unlinks_on_isbn_drift(db_session):
    """When a previously-linked shop_book gets a new ISBN that doesn't
    belong to its canonical book's ISBN set, the guard nulls book_id and
    resets match_status='unmatched' so step 1 can re-link by the new ISBN.
    """
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")

    # Canonical book owns ISBN_A only.
    isbn_a = "9786098183030"
    isbn_b = "9786098163018"  # legitimate but belongs to a different book
    book = Book(data_source="shop_inferred", title="Canonical A")
    db_session.add(book)
    db_session.flush()
    db_session.add(BookIsbn(book_id=book.id, isbn=isbn_a, isbn_type="isbn13"))
    db_session.flush()

    # Initial shop_book: ISBN_A, manually link + mark matched (simulates
    # match step 1 having run).
    shop_book, *_ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/some-book",
        title="Some Book",
        isbn=isbn_a,
    )
    shop_book.book_id = book.id
    shop_book.match_status = "matched"
    db_session.flush()

    # Re-upsert with a DIFFERENT ISBN that isn't in book's book_isbns →
    # guard fires.
    sb2, created, _, changes = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/some-book",
        title="Some Book",
        isbn=isbn_b,
    )
    assert created is False
    assert sb2.id == shop_book.id
    assert sb2.isbn == isbn_b
    assert sb2.book_id is None
    assert sb2.match_status == "unmatched"
    # Lineage row for the unlink is in the returned changes list so the
    # PostgresPipeline writes it to shop_book_changes.
    fields_changed = {c["field"] for c in changes}
    assert "book_id" in fields_changed
    assert "match_status" in fields_changed
    book_id_change = next(c for c in changes if c["field"] == "book_id")
    assert book_id_change["old"] == str(book.id)
    assert book_id_change["new"] is None


def test_upsert_shop_book_keeps_link_when_isbn_still_valid(db_session):
    """A row's book_id must NOT be reset when the new ISBN is a
    different valid ISBN (e.g. ISBN-10 alias) registered for the same
    canonical book — that's the normal isbn10/isbn13 pairing case.
    """
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")

    isbn_13 = "9786098183030"
    isbn_10 = "6098183031"
    book = Book(data_source="shop_inferred", title="Canonical")
    db_session.add(book)
    db_session.flush()
    db_session.add(BookIsbn(book_id=book.id, isbn=isbn_13, isbn_type="isbn13"))
    db_session.add(BookIsbn(book_id=book.id, isbn=isbn_10, isbn_type="isbn10"))
    db_session.flush()

    shop_book, *_ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/book",
        title="Book",
        isbn=isbn_13,
    )
    shop_book.book_id = book.id
    shop_book.match_status = "matched"
    db_session.flush()

    sb2, _, _, changes = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/book",
        title="Book",
        isbn=isbn_10,
    )
    assert sb2.book_id == book.id
    assert sb2.match_status == "matched"
    assert "book_id" not in {c["field"] for c in changes}


def test_upsert_shop_book_no_guard_when_unlinked(db_session):
    """When a shop_book has no canonical link, the guard is a no-op."""
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    shop_book, *_ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/b",
        title="B",
        isbn="9786098183030",
    )
    # No book_id set; this just confirms the guard's short-circuit.
    sb2, _, _, changes = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/b",
        title="B",
        isbn="9786098163018",
    )
    assert sb2.book_id is None
    assert "book_id" not in {c["field"] for c in changes}


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
