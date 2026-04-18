"""Backfill shop_books.type using the current final classification rules.

Usage:
    DATABASE_URL=postgresql+psycopg2://... \
        uv run python -m book_scraper.scripts.backfill_shop_book_types
"""

from __future__ import annotations

import os

from sqlalchemy.orm import joinedload

from book_scraper.config import load_default_config
from book_scraper.db.models import ShopBook
from book_scraper.db.repo import _infer_shop_book_type
from book_scraper.db.session import get_session_factory


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    return load_default_config().database.url


def main() -> int:
    session_factory = get_session_factory(_database_url())
    session = session_factory()
    changed = 0
    try:
        rows = (
            session.query(ShopBook)
            .options(joinedload(ShopBook.attributes))
            .order_by(ShopBook.id)
            .all()
        )
        for shop_book in rows:
            properties = {attr.key: attr.value for attr in shop_book.attributes}
            inferred = _infer_shop_book_type(
                title=shop_book.title,
                author=shop_book.author,
                isbn=shop_book.isbn,
                year=shop_book.year,
                format=shop_book.format,
                categories=shop_book.categories,
                properties=properties,
            )
            if shop_book.type != inferred:
                shop_book.type = inferred
                changed += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(f"backfilled {changed} shop_books.type rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
