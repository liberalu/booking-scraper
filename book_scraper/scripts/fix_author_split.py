"""One-off cleanup: rebuild shop_authors + listing_authors from the
raw listings.author string.

Initial migration 905fbbbc4372 backfilled with a capturing regex, so
separators (",", "&", "/", ";") and false-positive fragments ("ir",
"and", bare initials like "M.", "E.") ended up as author rows. This
wipes listing_authors entirely and re-splits every listing.author with
the corrected regex, dropping now-orphaned shop_authors.

Idempotent. Usage:
    DATABASE_URL=postgresql+psycopg2://... \\
        uv run python -m book_scraper.scripts.fix_author_split
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import text

from book_scraper.db.models import Listing, ListingAuthor, ShopAuthor
from book_scraper.db.repo import _sync_listing_authors
from book_scraper.db.session import get_session_factory


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    session_factory = get_session_factory(url)

    # Phase 1: wipe. Own session, committed + closed before re-build.
    wipe = session_factory()
    try:
        wipe.execute(text("TRUNCATE listing_authors"))
        wipe.execute(text("TRUNCATE shop_authors CASCADE"))
        wipe.commit()
    finally:
        wipe.close()

    # Phase 2: read listings we need to re-split. Separate session so we
    # don't fight with the identity map of the per-batch sessions below.
    reader = session_factory()
    try:
        rows = (
            reader.query(Listing.id, Listing.author)
            .filter(Listing.author.isnot(None))
            .filter(Listing.author != "")
            .all()
        )
    finally:
        reader.close()

    print(f"re-splitting {len(rows)} listing authors…")
    # Phase 3: batch re-insert. Commit + recycle the session every N
    # listings so ShopAuthor inserts stay small and identity-map pressure
    # is low.
    batch_size = 500
    session = session_factory()
    try:
        for i, (listing_id, author) in enumerate(rows, 1):
            _sync_listing_authors(session, listing_id, author)
            if i % batch_size == 0:
                session.commit()
                session.close()
                session = session_factory()
                print(f"  {i}/{len(rows)}")
        session.commit()
    finally:
        session.close()

    # Phase 4: report.
    report = session_factory()
    try:
        print(
            f"done. shop_authors={report.query(ShopAuthor).count()}, "
            f"listing_authors={report.query(ListingAuthor).count()}"
        )
    finally:
        report.close()


if __name__ == "__main__":
    raise SystemExit(main())
