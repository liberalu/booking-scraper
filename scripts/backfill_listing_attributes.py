"""Backfill: copy listings.properties JSONB into listing_attributes rows.

Idempotent. Run it once after deploying the listing_attributes table;
re-running is safe because _sync_attribute_rows does upsert-style updates.

Usage:
    PYTHONPATH=. uv run python scripts/backfill_listing_attributes.py
"""

from __future__ import annotations

import os
import sys

from book_scraper.db.models import Listing
from book_scraper.db.repo import _sync_attribute_rows
from book_scraper.db.session import get_session_factory

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper",
)


def main() -> int:
    session = get_session_factory(DATABASE_URL)()
    try:
        ids = [
            row.id
            for row in session.query(Listing.id)
            .filter(Listing.properties.is_not(None))
            .all()
        ]
        total = len(ids)
        print(f"{total} listing(s) to process")
        for batch_start in range(0, total, 500):
            batch_ids = ids[batch_start : batch_start + 500]
            for listing in (
                session.query(Listing).filter(Listing.id.in_(batch_ids)).all()
            ):
                if listing.properties:
                    _sync_attribute_rows(session, listing, listing.properties)
            session.commit()
            print(f"  processed {min(batch_start + 500, total)} / {total}")
        print("done")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
