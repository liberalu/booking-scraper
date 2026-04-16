"""Backfill: copy listings.properties JSONB into listing_attributes rows.

Idempotent. Must be run *before* migration `a4bd6135313a` drops the
legacy JSONB column — after the drop there is nothing to read from, and
running this script will be a no-op (the `properties` attribute no
longer exists on the ORM model).

Usage:
    PYTHONPATH=. uv run python scripts/backfill_listing_attributes.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import inspect, text

from book_scraper.db.repo import _sync_attribute_rows
from book_scraper.db.session import get_session_factory

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper",
)


def main() -> int:
    session = get_session_factory(DATABASE_URL)()
    try:
        # The `properties` column may already have been dropped by the
        # follow-up migration. Read it via raw SQL so this script does
        # not depend on the current ORM shape.
        bind = session.get_bind()
        inspector = inspect(bind)
        columns = {c["name"] for c in inspector.get_columns("listings")}
        if "properties" not in columns:
            print(
                "listings.properties column not present — backfill already "
                "applied (or migration a4bd6135313a has dropped it). Nothing "
                "to do."
            )
            return 0

        rows = session.execute(
            text("SELECT id, properties FROM listings WHERE properties IS NOT NULL")
        ).all()
        total = len(rows)
        print(f"{total} listing(s) to process")

        # Lazy import so the ORM model is only consulted when we have work.
        from book_scraper.db.models import Listing

        for batch_start in range(0, total, 500):
            batch = rows[batch_start : batch_start + 500]
            for listing_id, props in batch:
                if not props:
                    continue
                listing = session.get(Listing, listing_id)
                if listing is not None:
                    _sync_attribute_rows(session, listing, props)
            session.commit()
            print(f"  processed {min(batch_start + 500, total)} / {total}")
        print("done")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
