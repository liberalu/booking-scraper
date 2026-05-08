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
