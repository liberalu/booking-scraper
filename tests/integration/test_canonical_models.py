"""Integration tests for canonical book layer ORM models."""
import pytest
from sqlalchemy import select

from book_scraper.db.models import (
    Author,
    Book,
    BookAuthor,
    BookIsbn,
    Publisher,
    Series,
)


def test_publisher_round_trip(db_session):
    pub = Publisher(name="Šviesa", country="LT")
    db_session.add(pub)
    db_session.flush()
    assert pub.id is not None
    found = db_session.execute(
        select(Publisher).where(Publisher.name == "Šviesa")
    ).scalar_one()
    assert found.country == "LT"


def test_book_with_publisher_and_series(db_session):
    pub = Publisher(name="Tyto Alba")
    series = Series(title="Tylioji srovė")
    db_session.add_all([pub, series])
    db_session.flush()

    book = Book(
        data_source="ibiblioteka",
        libis_code="LIBIS000000123456",
        title="Test Book",
        year=2024,
        publisher_id=pub.id,
        series_id=series.id,
    )
    db_session.add(book)
    db_session.flush()
    assert book.id is not None


def test_book_isbn_unique(db_session):
    book = Book(
        data_source="ibiblioteka", libis_code="LIBIS000000999999", title="X"
    )
    db_session.add(book)
    db_session.flush()
    db_session.add(
        BookIsbn(book_id=book.id, isbn="9789876543210", isbn_type="isbn13")
    )
    db_session.flush()
    db_session.add(
        BookIsbn(book_id=book.id, isbn="9789876543210", isbn_type="isbn13")
    )
    with pytest.raises(Exception):
        db_session.flush()


def test_book_author_with_role(db_session):
    book = Book(
        data_source="ibiblioteka", libis_code="LIBIS000000888888", title="Y"
    )
    author = Author(name="Mildažytė, Edita", normalized_name="mildazyte edita")
    db_session.add_all([book, author])
    db_session.flush()
    db_session.add(
        BookAuthor(book_id=book.id, author_id=author.id, role="author", position=0)
    )
    db_session.flush()


def test_libis_code_required_for_ibiblioteka(db_session):
    """CHECK constraint enforces libis_code when data_source='ibiblioteka'."""
    book = Book(data_source="ibiblioteka", libis_code=None, title="Bad")
    db_session.add(book)
    with pytest.raises(Exception):
        db_session.flush()


def test_shop_inferred_libis_code_optional(db_session):
    book = Book(data_source="shop_inferred", libis_code=None, title="Inferred")
    db_session.add(book)
    db_session.flush()
    assert book.id is not None
