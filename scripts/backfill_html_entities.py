"""Backfill: html.unescape() existing shop_books' title/description/publisher.

Fixes rows scraped before the parser was taught to decode HTML entities
(e.g. "Scythe &amp; Sparrow" -> "Scythe & Sparrow").

Idempotent: only touches rows whose unescaped value differs from the
stored value. Run again safely.

Usage:
    PYTHONPATH=. uv run python scripts/backfill_html_entities.py
"""

from __future__ import annotations

import html
import os
import sys

from book_scraper.db.models import ShopBook
from book_scraper.db.session import get_session_factory

FIELDS = ("title", "description", "publisher")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper",
)


def main() -> int:
    session = get_session_factory(DATABASE_URL)()
    updated = dict.fromkeys(FIELDS, 0)
    try:
        for shop_book in session.query(ShopBook).yield_per(500):
            changed = False
            for field in FIELDS:
                raw = getattr(shop_book, field)
                if not isinstance(raw, str):
                    continue
                decoded = html.unescape(raw)
                if decoded != raw:
                    setattr(shop_book, field, decoded)
                    updated[field] += 1
                    changed = True
            if changed:
                session.add(shop_book)
        session.commit()
    finally:
        session.close()

    for field, count in updated.items():
        print(f"{field}: {count} row(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
