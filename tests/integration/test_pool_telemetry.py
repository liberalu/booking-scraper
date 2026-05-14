"""CODEOBS-08: SQLAlchemy pool emits WARNINGs on invalidate."""
from __future__ import annotations

import logging
import os

import pytest
from sqlalchemy import text

from book_scraper.db.session import get_engine


@pytest.fixture
def test_engine():
    db_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test",
    )
    engine = get_engine(db_url)
    yield engine
    engine.dispose()


def test_pool_invalidate_logs_warning(caplog, test_engine) -> None:
    """Forced invalidation emits a WARNING via the pool event listener."""
    with caplog.at_level(logging.WARNING, logger="book_scraper.db.pool"):
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1")).fetchone()
            # Force invalidate the underlying DBAPI connection
            conn.connection.invalidate()

    invalidates = [
        r.getMessage()
        for r in caplog.records
        if "Pool connection invalidated" in r.message
    ]
    assert len(invalidates) >= 1
