"""One-off backfill: convert every existing HTML listing description
to Markdown in place.

Snapshots the original HTML into `listings_description_backup` before
touching `listings.description`. Idempotent — re-running converts only
rows whose current description still looks like HTML.

Usage:
    DATABASE_URL=postgresql+psycopg2://... \\
        uv run python -m book_scraper.scripts.html_to_markdown_descriptions
"""

from __future__ import annotations

import os
import sys

from markdownify import markdownify as html_to_markdown
from sqlalchemy import text

from book_scraper.db.session import get_session_factory


def _looks_like_html(value: str) -> bool:
    return "<" in value and ">" in value


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    session_factory = get_session_factory(url)
    session = session_factory()
    try:
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS listings_description_backup ("
                "id INTEGER PRIMARY KEY, description TEXT)"
            )
        )
        session.execute(
            text(
                "INSERT INTO listings_description_backup (id, description) "
                "SELECT id, description FROM listings "
                "WHERE description IS NOT NULL "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        rows = session.execute(
            text(
                "SELECT id, description FROM listings "
                "WHERE description IS NOT NULL"
            )
        ).fetchall()
        converted = 0
        for listing_id, description in rows:
            if not isinstance(description, str) or not _looks_like_html(description):
                continue
            md = html_to_markdown(description, heading_style="ATX").strip()
            session.execute(
                text("UPDATE listings SET description = :d WHERE id = :id"),
                {"d": md or None, "id": listing_id},
            )
            converted += 1
        session.commit()
        print(f"converted {converted} descriptions (total rows scanned: {len(rows)})")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
