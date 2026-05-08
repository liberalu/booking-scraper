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
        self.shop_trust = self._load_shop_trust()  # {shop_name: int}

    @staticmethod
    def _load_shop_trust() -> dict[str, int]:
        """Load per-shop trust from config/shops/*.toml [match] trust=N.

        Broken / missing TOMLs are logged but don't kill the matcher —
        a single shop with an unreadable config falls back to default
        trust (50) elsewhere; the rest of the catalogue still matches.
        """
        from pathlib import Path

        from book_scraper.config import load_shop_config

        out: dict[str, int] = {}
        cfg_dir = Path("config/shops")
        if not cfg_dir.exists():
            return out
        for toml in cfg_dir.glob("*.toml"):
            try:
                cfg = load_shop_config(toml.stem)
                out[toml.stem] = cfg.match.trust
            except FileNotFoundError:
                continue
            except Exception:
                logger.exception("Failed to load match.trust from %s", toml)
                continue
        return out

    def run(self, shop_name: str) -> MatchCounters:
        """Run all match steps for one shop. Returns counters for the run row."""
        counters = MatchCounters()
        counters.books_linked = self._step1_isbn_match(shop_name)
        counters.authors_linked = self._step2_author_backfill(shop_name)
        counters.books_synthesized = self._step3_shop_inferred_synthesis()
        # Step 4 (LIBIS upgrade) is performed inside _upsert_book; nothing here.
        # Re-run step 1 so newly synthesised books pick up matches.
        counters.books_linked += self._step1_isbn_match(shop_name)
        return counters

    def _step3_shop_inferred_synthesis(self) -> int:
        """Find ISBNs on ≥2 shops with no canonical book; create shop_inferred rows."""
        rows = self.session.execute(text("""
            WITH candidates AS (
              SELECT REPLACE(REPLACE(sb.isbn, '-', ''), ' ', '') AS isbn,
                     COUNT(DISTINCT sb.shop_id) AS shop_count
                FROM shop_books sb
               WHERE sb.isbn IS NOT NULL
                 AND sb.book_id IS NULL
               GROUP BY 1
              HAVING COUNT(DISTINCT sb.shop_id) >= 2
            )
            SELECT c.isbn, c.shop_count
              FROM candidates c
             WHERE NOT EXISTS (
                 SELECT 1 FROM book_isbns bi WHERE bi.isbn = c.isbn
             )
        """)).all()

        synthesised = 0
        for isbn_norm, _shop_count in rows:
            self._synthesise_one(isbn_norm)
            synthesised += 1

        logger.info(
            "MatchService step 3: %d shop_inferred books synthesised", synthesised
        )
        return synthesised

    def _synthesise_one(self, isbn_norm: str) -> None:
        """Build a shop_inferred Book from the highest-trust shop's data,
        with the FIRST writer's publisher (sticky)."""
        from datetime import datetime, timezone

        from sqlalchemy import select

        from book_scraper.db.models import Book, BookIsbn, Publisher

        # Sentinel for NULL first_seen_at — sorts NULL rows last so they
        # don't accidentally win the "first writer" tiebreak.
        _FAR_FUTURE = datetime(9999, 1, 1, tzinfo=timezone.utc)

        candidates = self.session.execute(text("""
            SELECT sb.id, sb.shop_id, s.name AS shop_name, sb.title, sb.year,
                   sb.format, sb.type, sb.publisher, sb.first_seen_at
              FROM shop_books sb
              JOIN shops s ON s.id = sb.shop_id
             WHERE REPLACE(REPLACE(sb.isbn, '-', ''), ' ', '') = :isbn
        """), {"isbn": isbn_norm}).all()

        if len(candidates) < 2:
            return

        scored = sorted(
            candidates,
            key=lambda r: (-(self.shop_trust.get(r.shop_name, 50)),),
        )
        winner = scored[0]

        first_with_pub = sorted(
            [c for c in candidates if c.publisher],
            key=lambda r: r.first_seen_at or _FAR_FUTURE,
        )
        publisher_name = first_with_pub[0].publisher if first_with_pub else None

        publisher_id = None
        if publisher_name:
            pub = self.session.execute(
                select(Publisher).where(Publisher.name == publisher_name)
            ).scalar_one_or_none()
            if pub is None:
                pub = Publisher(name=publisher_name)
                self.session.add(pub)
                self.session.flush()
            publisher_id = pub.id

        book = Book(
            data_source="shop_inferred",
            libis_code=None,
            title=winner.title or "(untitled)",
            year=winner.year,
            publisher_id=publisher_id,
            type=winner.type,
            format=winner.format,
        )
        self.session.add(book)
        self.session.flush()
        self.session.add(BookIsbn(
            book_id=book.id, isbn=isbn_norm,
            isbn_type="isbn13" if len(isbn_norm) == 13 else "isbn10",
        ))
        self.session.flush()

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
