"""One-off cleanup: rebuild shop_authors + shop_book_authors from the
raw shop_books.author string.

Initial migration 905fbbbc4372 backfilled with a capturing regex, so
separators (",", "&", "/", ";") and false-positive fragments ("ir",
"and", bare initials like "M.", "E.") ended up as author rows. This
wipes shop_book_authors entirely and re-splits every shop_book.author
with the corrected regex, dropping now-orphaned shop_authors.

Idempotent. Usage:
    DATABASE_URL=postgresql+psycopg2://... \\
        uv run python -m book_scraper.scripts.fix_author_split
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import text

from book_scraper.db.models import ShopAuthor, ShopBook, ShopBookAuthor
from book_scraper.db.repo import _sync_shop_book_authors
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
        wipe.execute(text("TRUNCATE shop_book_authors"))
        wipe.execute(text("TRUNCATE shop_authors CASCADE"))
        wipe.commit()
    finally:
        wipe.close()

    # Phase 2: read shop_books we need to re-split. Separate session so we
    # don't fight with the identity map of the per-batch sessions below.
    reader = session_factory()
    try:
        rows = (
            reader.query(ShopBook.id, ShopBook.author)
            .filter(ShopBook.author.isnot(None))
            .filter(ShopBook.author != "")
            .all()
        )
    finally:
        reader.close()

    print(f"re-splitting {len(rows)} shop_book authors…")
    # Phase 3: batch re-insert. Commit + recycle the session every N
    # shop_books so ShopAuthor inserts stay small and identity-map
    # pressure is low.
    batch_size = 500
    session = session_factory()
    try:
        for i, (shop_book_id, author) in enumerate(rows, 1):
            _sync_shop_book_authors(session, shop_book_id, author)
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
            f"shop_book_authors={report.query(ShopBookAuthor).count()}"
        )
    finally:
        report.close()


if __name__ == "__main__":
    raise SystemExit(main())
