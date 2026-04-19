# tests/unit/test_url_classifications_repo.py
from unittest.mock import MagicMock
from datetime import datetime, UTC

from book_scraper.db.repo import upsert_url_classification
from book_scraper.db.models import UrlClassification


def _make_session():
    session = MagicMock()
    return session


def test_upsert_creates_new_row():
    session = _make_session()
    session.execute.return_value.scalar_one_or_none.return_value = None
    upsert_url_classification(
        session,
        discovered_url_id=42,
        book_score=7,
        is_book_product=True,
        reasons=["+3 valid ISBN", "+2 author present"],
    )
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, UrlClassification)
    assert added.discovered_url_id == 42
    assert added.book_score == 7
    assert added.is_book_product is True
    assert added.reasons == ["+3 valid ISBN", "+2 author present"]
    assert isinstance(added.classified_at, datetime)
    session.flush.assert_called_once()


def test_upsert_updates_existing_row():
    existing = UrlClassification(
        discovered_url_id=42,
        book_score=3,
        is_book_product=True,
        reasons=["+3 valid ISBN"],
        classified_at=datetime.now(UTC),
    )
    original_classified_at = existing.classified_at
    session = _make_session()
    session.execute.return_value.scalar_one_or_none.return_value = existing

    upsert_url_classification(
        session,
        discovered_url_id=42,
        book_score=-2,
        is_book_product=False,
        reasons=["-4 non-book categories"],
    )
    assert existing.book_score == -2
    assert existing.is_book_product is False
    assert existing.reasons == ["-4 non-book categories"]
    assert existing.classified_at > original_classified_at
    session.flush.assert_called_once()
