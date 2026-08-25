"""Integration tests for scripts/backfill_authors.py.

The script fetches real HTTP pages, so we monkey-patch httpx.Client
to return a locally-cached fixture. The DB interactions are real.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from book_scraper.db.repo import upsert_shop, upsert_shop_book
from scripts import backfill_authors

FIXTURE = Path(__file__).parents[2] / "fixtures" / "vaga_category_page.html"


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class _FakeClient:
    """Stand-in for httpx.Client that returns the fixture on the first
    call and an empty body thereafter (so pagination terminates)."""

    def __init__(self, fixture: str) -> None:
        self._fixture = fixture
        self._calls = 0

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: Any) -> None:  # pragma: no cover
        return None

    def get(self, url: str, timeout: float | None = None) -> _FakeResponse:
        self._calls += 1
        if self._calls == 1:
            return _FakeResponse(self._fixture, status_code=200)
        return _FakeResponse("", status_code=200)


@pytest.fixture
def patched_client(monkeypatch: pytest.MonkeyPatch) -> None:
    html = FIXTURE.read_text()
    monkeypatch.setattr(
        backfill_authors.httpx,
        "Client",
        lambda follow_redirects=True: _FakeClient(html),
    )


@pytest.mark.integration
class TestBackfillAuthors:
    def test_fills_null_authors_from_category_page(
        self, db_session, patched_client, monkeypatch
    ):
        """Shop books that match a URL parsed from the category fixture
        and currently have NULL author should get the author set."""
        monkeypatch.setattr(
            backfill_authors, "get_session_factory", lambda _: lambda: db_session
        )
        # Suppress db_session.close() so the fixture's rollback still runs.
        monkeypatch.setattr(db_session, "close", lambda: None)
        monkeypatch.setattr(db_session, "commit", db_session.flush)

        shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")

        # Sample some URLs and authors from the fixture to seed shop_books.
        from book_scraper.spiders.vaga.parsers import parse_category_page

        products = parse_category_page(FIXTURE.read_text())["products"]
        with_author = [p for p in products if p.get("author") and p.get("url")][:3]
        assert with_author, "fixture should contain authored products"

        seeded_urls = []
        for product in with_author:
            raw_url = product["url"]
            url = raw_url if raw_url.startswith("http") else f"https://vaga.lt{raw_url}"
            upsert_shop_book(
                db_session,
                shop_id=shop.id,
                url=url,
                title="seeded",
                author=None,
            )
            seeded_urls.append((url, product["author"]))
        db_session.flush()

        updated = backfill_authors.backfill("vaga", max_pages=1)
        assert updated >= len(seeded_urls)

        from book_scraper.db.models import ShopBook

        for url, expected_author in seeded_urls:
            shop_book = (
                db_session.query(ShopBook).filter_by(shop_id=shop.id, url=url).one()
            )
            assert shop_book.author == expected_author

    def test_idempotent_never_clobbers_existing_author(
        self, db_session, patched_client, monkeypatch
    ):
        """Shop books that already have an author must not be changed,
        even if the category page contains a different value for the
        same URL (shouldn't happen in practice, but the filter protects
        against it)."""
        monkeypatch.setattr(
            backfill_authors, "get_session_factory", lambda _: lambda: db_session
        )
        monkeypatch.setattr(db_session, "close", lambda: None)
        monkeypatch.setattr(db_session, "commit", db_session.flush)

        shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")

        from book_scraper.spiders.vaga.parsers import parse_category_page

        products = parse_category_page(FIXTURE.read_text())["products"]
        first = next(p for p in products if p.get("author") and p.get("url"))
        url = (
            first["url"]
            if first["url"].startswith("http")
            else f"https://vaga.lt{first['url']}"
        )
        shop_book, *_ = upsert_shop_book(
            db_session,
            shop_id=shop.id,
            url=url,
            title="existing",
            author="Keep Me",
        )
        db_session.flush()

        backfill_authors.backfill("vaga", max_pages=1)

        db_session.refresh(shop_book)
        assert shop_book.author == "Keep Me"
