"""Match service: links shop_books to canonical books.

Phases (this commit implements 1 + 2; 3 + 4 added in Task 6):

  1. ISBN match — UPDATE shop_books.book_id where isbn matches book_isbns.isbn.
  2. Author backfill — UPDATE shop_authors.canonical_author_id via the
     matched book's primary authors (ba.role = 'author' filter prevents
     position=0 collisions with translator/narrator/illustrator).
  3. shop_inferred synthesis (Task 6).
  4. shop_inferred upgrade — handled by the BookItem upsert path itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class MatchCounters:
    """Per-run match outcome counters. Returned by MatchService.run()."""

    books_linked: int = 0
    authors_linked: int = 0
    books_synthesized: int = 0

    @property
    def total_updates(self) -> int:
        """Sum suitable for scrape_runs.items_updated."""
        return self.books_linked + self.authors_linked


class MatchService:
    """Per-shop matcher. Steps are SQL-driven and idempotent."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self, shop_name: str) -> MatchCounters:
        """Run all match steps for one shop. Returns counters for the run row."""
        counters = MatchCounters()
        counters.books_linked = self._step1_isbn_match(shop_name)
        counters.authors_linked = self._step2_author_backfill(shop_name)
        return counters

    def _step1_isbn_match(self, shop_name: str) -> int:
        """Link shop_books.book_id by ISBN. Returns rows updated."""
        result = self.session.execute(
            text("""
                UPDATE shop_books sb
                   SET book_id = bi.book_id,
                       match_status = 'matched',
                       match_method = 'isbn'
                  FROM book_isbns bi, shops s
                 WHERE sb.shop_id = s.id
                   AND s.name = :shop_name
                   AND sb.isbn IS NOT NULL
                   AND REPLACE(REPLACE(sb.isbn, '-', ''), ' ', '') = bi.isbn
                   AND sb.book_id IS NULL
            """),
            {"shop_name": shop_name},
        )
        n = result.rowcount or 0
        logger.info("MatchService step 1: %d shop_books linked for %s", n, shop_name)
        return n

    def _step2_author_backfill(self, shop_name: str) -> int:
        """Link shop_authors.canonical_author_id where the underlying
        shop_book matched in step 1. role='author' filter prevents
        position=0 collisions with translator/narrator/illustrator.
        """
        result = self.session.execute(
            text("""
                UPDATE shop_authors sa
                   SET canonical_author_id = ba.author_id
                  FROM shop_book_authors sba
                  JOIN shop_books sb ON sb.id = sba.shop_book_id
                  JOIN book_authors ba ON ba.book_id = sb.book_id
                                      AND ba.position = sba.position
                                      AND ba.role = 'author'
                  JOIN shops s ON s.id = sb.shop_id
                 WHERE sa.id = sba.author_id
                   AND sa.canonical_author_id IS NULL
                   AND sb.match_status = 'matched'
                   AND s.name = :shop_name
            """),
            {"shop_name": shop_name},
        )
        n = result.rowcount or 0
        logger.info("MatchService step 2: %d shop_authors linked for %s", n, shop_name)
        return n
