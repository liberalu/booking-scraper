"""Integration tests for ISBN normalization on shop_books store and BookItem upsert."""
from book_scraper.items import ShopBookItem
from book_scraper.pipelines import ValidationPipeline


def test_validation_pipeline_normalizes_dashed_isbn():
    item = ShopBookItem(
        url="https://example.com/p/1",
        shop_name="vaga",
        title="X",
        isbn="978-0-306-40615-7",
        price="10.0",
    )
    p = ValidationPipeline()
    result = p.process_item(item)
    assert result["isbn"] == "9780306406157"


def test_validation_pipeline_keeps_already_normalized_isbn():
    item = ShopBookItem(
        url="https://example.com/p/2",
        shop_name="vaga",
        title="Y",
        isbn="9780306406157",
        price="10.0",
    )
    p = ValidationPipeline()
    result = p.process_item(item)
    assert result["isbn"] == "9780306406157"


def test_validation_pipeline_drops_invalid_isbn_to_none():
    item = ShopBookItem(
        url="https://example.com/p/3",
        shop_name="vaga",
        title="Z",
        isbn="not-an-isbn",
        price="10.0",
    )
    p = ValidationPipeline()
    result = p.process_item(item)
    assert result["isbn"] is None


import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from book_scraper.db.models import Author, Book, BookAuthor, BookIsbn, Publisher
from book_scraper.items import BookItem


@pytest.fixture
def book_pipeline(db_session):
    """PostgresPipeline wired to the rollback-isolated test session.

    Reuses `db_session`'s connection so the pipeline's `session.commit()`
    calls only release a SAVEPOINT (see conftest). Binding to `engine`
    directly here would leak inserted rows across tests (publisher
    "Šviesa" in particular caused UniqueViolation in test_canonical_models
    and test_books_api).
    """
    from book_scraper.pipelines import PostgresPipeline
    pipeline = PostgresPipeline(database_url=str(db_session.bind.engine.url))
    pipeline.session_factory = sessionmaker(bind=db_session.connection())
    pipeline.session = db_session
    yield pipeline


def test_bookitem_inserts_publishers_series_authors_isbns(db_session, book_pipeline):
    item = BookItem(
        libis_code="LIBIS000000111111",
        data_source="ibiblioteka",
        title="Test Book",
        year=2024,
        publisher="Šviesa",
        series="Maži milžinai",
        isbns=[{"isbn": "9780306406157", "type": "isbn13"}],
        authors=[{"name": "Mildažytė, Edita", "libis_code": "LNB:Hd0;=BC",
                  "role": "author", "position": 0}],
    )
    book_pipeline.process_item(item)

    book = db_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000111111")
    ).scalar_one()
    assert book.title == "Test Book"
    assert book.year == 2024
    pub = db_session.execute(
        select(Publisher).where(Publisher.name == "Šviesa")
    ).scalar_one()
    assert book.publisher_id == pub.id
    assert book.series_id is not None
    isbns = db_session.execute(
        select(BookIsbn.isbn).where(BookIsbn.book_id == book.id)
    ).scalars().all()
    assert "9780306406157" in isbns
    assert "0306406152" in isbns
    authors = db_session.execute(
        select(Author).join(BookAuthor).where(BookAuthor.book_id == book.id)
    ).scalars().all()
    assert any(a.libis_code == "LNB:Hd0;=BC" for a in authors)


def test_bookitem_re_upsert_idempotent(db_session, book_pipeline):
    base = BookItem(
        libis_code="LIBIS000000222222",
        data_source="ibiblioteka",
        title="First Title",
        year=2023,
        isbns=[{"isbn": "9780306406164", "type": "isbn13"}],
    )
    book_pipeline.process_item(base)

    updated = BookItem(
        libis_code="LIBIS000000222222",
        data_source="ibiblioteka",
        title="Updated Title",
        year=2024,
        isbns=[{"isbn": "9780306406164", "type": "isbn13"}],
    )
    book_pipeline.process_item(updated)

    rows = db_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000222222")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "Updated Title"
    assert rows[0].year == 2024


def test_publisher_id_sticky_on_re_upsert(db_session, book_pipeline):
    first = BookItem(
        libis_code="LIBIS000000333333",
        data_source="ibiblioteka",
        title="Sticky Test",
        publisher="First Publisher",
        isbns=[],
    )
    book_pipeline.process_item(first)
    book = db_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000333333")
    ).scalar_one()
    first_pub_id = book.publisher_id
    assert first_pub_id is not None

    db_session.expire_all()
    second = BookItem(
        libis_code="LIBIS000000333333",
        data_source="ibiblioteka",
        title="Sticky Test",
        publisher="Second Publisher",
        isbns=[],
    )
    book_pipeline.process_item(second)
    book = db_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000333333")
    ).scalar_one()
    assert book.publisher_id == first_pub_id


def test_lookup_by_isbn_finds_existing_shop_inferred(db_session, book_pipeline):
    inferred = BookItem(
        libis_code=None,
        data_source="shop_inferred",
        title="Inferred",
        publisher="Shop Publisher",
        isbns=[{"isbn": "9780306406171", "type": "isbn13"}],
    )
    book_pipeline.process_item(inferred)

    db_session.expire_all()
    libis = BookItem(
        libis_code="LIBIS000000444444",
        data_source="ibiblioteka",
        title="LIBIS Title",
        publisher="LIBIS Publisher",
        isbns=[{"isbn": "9780306406171", "type": "isbn13"}],
    )
    book_pipeline.process_item(libis)

    rows = db_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000444444")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].data_source == "ibiblioteka"
    assert rows[0].title == "LIBIS Title"
    pub = db_session.execute(
        select(Publisher).where(Publisher.id == rows[0].publisher_id)
    ).scalar_one()
    assert pub.name == "Shop Publisher"


def test_libis_upgrade_preserves_inferred_publisher(db_session, book_pipeline):
    """A shop_inferred book gets upgraded to ibiblioteka by ISBN; LIBIS
    overwrites everything except publisher_id (sticky)."""
    inferred = BookItem(
        libis_code=None,
        data_source="shop_inferred",
        title="Inferred Title",
        publisher="Shop Publisher",
        isbns=[{"isbn": "9780000000099", "type": "isbn13"}],
    )
    book_pipeline.process_item(inferred)

    db_session.expire_all()
    upgrade = BookItem(
        libis_code="LIBIS000000999900",
        data_source="ibiblioteka",
        title="LIBIS Title",
        publisher="LIBIS Publisher",
        isbns=[{"isbn": "9780000000099", "type": "isbn13"}],
    )
    book_pipeline.process_item(upgrade)

    rows = db_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000999900")
    ).scalars().all()
    assert len(rows) == 1
    book = rows[0]
    assert book.data_source == "ibiblioteka"
    assert book.title == "LIBIS Title"
    pub = db_session.execute(
        select(Publisher).where(Publisher.id == book.publisher_id)
    ).scalar_one()
    assert pub.name == "Shop Publisher"
