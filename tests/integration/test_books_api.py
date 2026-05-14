"""Integration tests for canonical books API endpoints."""
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_books_list_returns_paginated_books(client, db_session):
    from book_scraper.db.models import Author, Book, BookAuthor, BookIsbn, Publisher

    pub = Publisher(name="Šviesa")
    db_session.add(pub)
    db_session.flush()
    book = Book(
        data_source="ibiblioteka", libis_code="LIBIS000000800001",
        title="API Test Book", year=2024, publisher_id=pub.id,
    )
    db_session.add(book)
    db_session.flush()
    db_session.add(BookIsbn(book_id=book.id, isbn="9789876543099", isbn_type="isbn13"))
    author = Author(name="Foo, Bar", normalized_name="foo bar")
    db_session.add(author)
    db_session.flush()
    db_session.add(BookAuthor(
        book_id=book.id, author_id=author.id, role="author", position=0
    ))
    db_session.commit()

    response = client.get("/api/books")
    assert response.status_code == 200
    data = response.json()
    assert "books" in data
    assert any(b["title"] == "API Test Book" for b in data["books"])
    found = next(b for b in data["books"] if b["title"] == "API Test Book")
    assert found["data_source"] == "ibiblioteka"
    assert found["year"] == 2024
    assert found["publisher"] == "Šviesa"
    assert "Foo, Bar" in (found.get("authors") or [])


def test_books_list_filter_by_data_source(client):
    response = client.get("/api/books?data_source=ibiblioteka")
    assert response.status_code == 200
    assert all(b["data_source"] == "ibiblioteka" for b in response.json()["books"])


def test_book_detail_returns_full_record_with_shops(db_session, client):
    from book_scraper.db.models import Book, BookIsbn, Shop, ShopBook

    book = Book(
        data_source="ibiblioteka", libis_code="LIBIS000000800002", title="Detail Test"
    )
    db_session.add(book)
    db_session.flush()
    db_session.add(BookIsbn(book_id=book.id, isbn="9789876543098", isbn_type="isbn13"))
    from sqlalchemy import select
    shop = db_session.execute(
        select(Shop).where(Shop.name == "vaga")
    ).scalar_one_or_none()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt")
        db_session.add(shop)
        db_session.flush()
    db_session.add(ShopBook(
        shop_id=shop.id, url="https://vaga.lt/books/test", title="Detail Test",
        price="15.00", in_stock=True, book_id=book.id,
    ))
    db_session.commit()

    response = client.get(f"/api/books/{book.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Detail Test"
    assert data["libis_code"] == "LIBIS000000800002"
    assert any(s["shop"] == "vaga" for s in data["shops"])
    assert any(s["price"] == "15.00" for s in data["shops"])


def test_book_detail_404_for_unknown(client):
    response = client.get("/api/books/999999999")
    assert response.status_code == 404


# ----- Smart search (Task 5/6) ---------------------------------------------


def test_books_search_by_isbn_exact_match(client, db_session):
    from book_scraper.db.models import Book, BookIsbn

    target = Book(data_source="shop_inferred", title="Hobitas SearchA", year=2020)
    other = Book(data_source="shop_inferred", title="Žiedų valdovas SearchA", year=2021)
    db_session.add_all([target, other])
    db_session.flush()
    db_session.add(
        BookIsbn(book_id=target.id, isbn="9786094661099", isbn_type="isbn13")
    )
    db_session.commit()

    resp = client.get("/api/books?search=9786094661099")
    assert resp.status_code == 200
    titles = [b["title"] for b in resp.json()["books"]]
    assert "Hobitas SearchA" in titles
    assert "Žiedų valdovas SearchA" not in titles


def test_books_search_by_isbn_with_dashes(client, db_session):
    from book_scraper.db.models import Book, BookIsbn

    book = Book(data_source="shop_inferred", title="Test Dash ISBN SearchB", year=2020)
    db_session.add(book)
    db_session.flush()
    db_session.add(BookIsbn(book_id=book.id, isbn="9786094661080", isbn_type="isbn13"))
    db_session.commit()

    resp = client.get("/api/books?search=978-609-466-1080")
    assert resp.status_code == 200
    titles = [b["title"] for b in resp.json()["books"]]
    assert "Test Dash ISBN SearchB" in titles


def test_books_search_by_title_substring(client, db_session):
    from book_scraper.db.models import Book

    db_session.add(Book(
        data_source="shop_inferred",
        title="Tolkien biography SearchC",
        year=2020,
    ))
    db_session.add(Book(
        data_source="shop_inferred", title="UnrelatedSearchC", year=2020
    ))
    db_session.commit()

    resp = client.get("/api/books?search=Tolkien biography SearchC")
    assert resp.status_code == 200
    titles = [b["title"] for b in resp.json()["books"]]
    assert "Tolkien biography SearchC" in titles
    assert "UnrelatedSearchC" not in titles


def test_books_search_by_author_name(client, db_session):
    from book_scraper.db.models import Author, Book, BookAuthor

    book = Book(
        data_source="shop_inferred",
        title="A title nothing like the author SearchD",
        year=2020,
    )
    db_session.add(book)
    db_session.flush()
    author = Author(
        name="J.R.R. Tolkien SearchableD",
        normalized_name="j.r.r. tolkien searchabled",
    )
    db_session.add(author)
    db_session.flush()
    db_session.add(BookAuthor(
        book_id=book.id, author_id=author.id, role="author", position=0,
    ))
    db_session.commit()

    resp = client.get("/api/books?search=Tolkien SearchableD")
    assert resp.status_code == 200
    titles = [b["title"] for b in resp.json()["books"]]
    assert "A title nothing like the author SearchD" in titles


def test_books_search_empty_string_acts_like_no_filter(client, db_session):
    from book_scraper.db.models import Book

    db_session.add(Book(
        data_source="shop_inferred", title="Some Book SearchE", year=2020,
    ))
    db_session.commit()

    resp_with = client.get("/api/books?search=")
    resp_without = client.get("/api/books")
    assert resp_with.status_code == 200
    assert resp_without.status_code == 200
    assert resp_with.json()["total"] == resp_without.json()["total"]


# ----- Price history (Task 1/2) --------------------------------------------


def test_book_prices_empty_for_book_without_shops(client, db_session):
    from book_scraper.db.models import Book

    book = Book(data_source="shop_inferred", title="PriceTest NoShop A", year=2020)
    db_session.add(book)
    db_session.commit()

    resp = client.get(f"/api/books/{book.id}/prices")
    assert resp.status_code == 200
    assert resp.json()["series"] == []


def test_book_prices_returns_series_for_linked_shop_books(client, db_session):
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from book_scraper.db.models import Book, Price, Shop, ShopBook

    shop = db_session.execute(
        select(Shop).where(Shop.name == "vaga")
    ).scalar_one_or_none()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt")
        db_session.add(shop)
        db_session.flush()

    book = Book(data_source="shop_inferred", title="PriceTest WithShop B", year=2020)
    db_session.add(book)
    db_session.flush()

    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/ptb",
        title="PriceTest WithShop B", price=Decimal("19.90"),
        in_stock=True, book_id=book.id,
    )
    db_session.add(sb)
    db_session.flush()

    db_session.add(Price(
        shop_book_id=sb.id, price=Decimal("19.90"), in_stock=True,
        scraped_at=datetime.now(UTC) - timedelta(days=1),
    ))
    db_session.add(Price(
        shop_book_id=sb.id, price=Decimal("18.50"), in_stock=True,
        scraped_at=datetime.now(UTC) - timedelta(days=2),
    ))
    db_session.commit()

    resp = client.get(f"/api/books/{book.id}/prices")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 1
    assert data["series"][0]["shop"] == "vaga"
    assert len(data["series"][0]["series"]) == 2  # two distinct days


def test_book_prices_404_for_unknown_book(client):
    resp = client.get("/api/books/999999999/prices")
    assert resp.status_code == 404


def test_book_prices_excludes_data_older_than_30_days(client, db_session):
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from book_scraper.db.models import Book, Price, Shop, ShopBook

    shop = db_session.execute(
        select(Shop).where(Shop.name == "vaga")
    ).scalar_one_or_none()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt")
        db_session.add(shop)
        db_session.flush()

    book = Book(data_source="shop_inferred", title="PriceTest OldData C", year=2020)
    db_session.add(book)
    db_session.flush()

    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/ptc",
        title="PriceTest OldData C", price=Decimal("15.00"),
        in_stock=True, book_id=book.id,
    )
    db_session.add(sb)
    db_session.flush()

    db_session.add(Price(
        shop_book_id=sb.id, price=Decimal("15.00"), in_stock=True,
        scraped_at=datetime.now(UTC) - timedelta(days=5),   # recent
    ))
    db_session.add(Price(
        shop_book_id=sb.id, price=Decimal("12.00"), in_stock=True,
        scraped_at=datetime.now(UTC) - timedelta(days=45),  # old, excluded
    ))
    db_session.commit()

    resp = client.get(f"/api/books/{book.id}/prices")
    assert resp.status_code == 200
    series = resp.json()["series"][0]["series"]
    prices = [p["price"] for p in series]
    assert 12.0 not in prices
    assert 15.0 in prices
