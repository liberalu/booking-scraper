"""Validate service: runs data-quality checks over shop_books rows.

Checks implemented here (plans 02 + 03):
  - Structural duplicates: isbn_duplicate, title_author_duplicate, sku_duplicate
  - Slug-title mismatch: slug_title_mismatch
  - Data completeness: active_no_price, in_stock_no_price, book_no_metadata,
      no_price_history
  - Data correctness: year_out_of_range, price_zero, format_is_dimensions
  - Classification consistency: book_no_signals, non_book_has_isbn,
      non_product_active
  - Staleness: stale_active, unreachable_active, orphan_no_url
  - Match readiness: unmatched_has_isbn, match_isbn_drift
  - Relationship integrity: url_aliases, product_url_non_book

Results are written to validation_issues via upsert_validation_issues,
which handles (shop_book_id, field, issue) deduplication and lifecycle
transitions (re-detect resolved → new; re-detect open → run_count++).

Usage::

    session = get_session_factory(url)()
    try:
        counters = ValidateService(session).run(shop_id, run_id)
        session.commit()
    finally:
        session.close()
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import text
from sqlalchemy.orm import Session

from book_scraper.db.repo import resolve_gone_issues, upsert_validation_issues

# Per-shop discover cadence threshold used by the stale_active check (plan 03).
# Deferred to v2: per-shop cadence field in DB (CONTEXT.md decision D-defer-1).
VALIDATE_STALE_CADENCE_DAYS: int = 14


def _tokenize(s: str) -> set[str]:
    """Lowercase, strip diacritics (NFD + filter Mn category), split on -/whitespace."""
    if not s:
        return set()
    nfd = unicodedata.normalize("NFD", s.lower())
    ascii_only = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return set(re.split(r"[-\s]+", ascii_only)) - {""}


def _should_flag_slug_title(slug: str | None, title: str | None) -> bool:
    """True iff both slug and title have tokens AND their intersection is empty.

    See spec §Slug-title mismatch for the zero-overlap threshold rationale.
    """
    if not slug or not title:
        return False
    slug_tokens = _tokenize(slug)
    title_tokens = _tokenize(title)
    if not slug_tokens or not title_tokens:
        return False
    return not (slug_tokens & title_tokens)


class ValidateService:
    """Per-shop data-quality validator. Checks are SQL-driven and idempotent.

    The caller is responsible for committing the session after run() returns.
    ValidateService never calls session.commit() itself (mirrors MatchService).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def run(self, shop_id: int, run_id: int) -> dict[str, int]:
        """Run all check groups and bulk-insert findings.

        Returns a counter dict keyed by issue key, e.g.::

            {"isbn_duplicate": 4, "slug_title_mismatch": 2}

        Total inserted == sum of values.
        """
        issues: list[dict[str, str | int | None]] = []
        issues.extend(self.check_structural_duplicates(shop_id, run_id))
        issues.extend(self.check_slug_title_mismatch(shop_id, run_id))
        issues.extend(self.check_data_completeness(shop_id, run_id))
        issues.extend(self.check_data_correctness(shop_id, run_id))
        issues.extend(self.check_classification_consistency(shop_id, run_id))
        issues.extend(self.check_staleness(shop_id, run_id))
        issues.extend(self.check_match_readiness(shop_id, run_id))
        issues.extend(self.check_relationship_integrity(shop_id, run_id))

        if issues:
            upsert_validation_issues(self._session, issues, shop_id=shop_id, run_id=run_id)

        resolve_gone_issues(self._session, shop_id=shop_id, run_id=run_id)

        counters: dict[str, int] = {}
        for issue in issues:
            key = str(issue["issue"])
            counters[key] = counters.get(key, 0) + 1
        return counters

    def check_structural_duplicates(
        self, shop_id: int, run_id: int
    ) -> list[dict[str, str | int | None]]:
        """Return ValidationIssue dicts for isbn/title_author/sku duplicates.

        Both rows of each pair receive a ValidationIssue (spec §Structural
        duplicates). Queries use EXISTS sub-selects to identify each row that
        has at least one sibling with the same identifying value.
        """
        results: list[dict[str, str | int | None]] = []

        # ISBN duplicates
        isbn_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url, sb.isbn "
                "FROM shop_books sb "
                "WHERE sb.shop_id = :shop_id "
                "  AND sb.isbn IS NOT NULL "
                "  AND EXISTS ("
                "      SELECT 1 FROM shop_books sb2 "
                "      WHERE sb2.shop_id = :shop_id "
                "        AND sb2.isbn = sb.isbn "
                "        AND sb2.id != sb.id"
                "  )"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in isbn_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "isbn",
                    "issue": "isbn_duplicate",
                    "raw_value": row.isbn,
                    "shop_book_id": row.id,
                }
            )

        # Title + author duplicates (case-insensitive, both non-null)
        title_author_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url, sb.title, sb.author "
                "FROM shop_books sb "
                "WHERE sb.shop_id = :shop_id "
                "  AND sb.title IS NOT NULL "
                "  AND sb.author IS NOT NULL "
                "  AND EXISTS ("
                "      SELECT 1 FROM shop_books sb2 "
                "      WHERE sb2.shop_id = :shop_id "
                "        AND lower(sb2.title) = lower(sb.title) "
                "        AND lower(sb2.author) = lower(sb.author) "
                "        AND sb2.id != sb.id"
                "  )"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in title_author_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "title_author",
                    "issue": "title_author_duplicate",
                    "raw_value": f"{row.title} / {row.author}",
                    "shop_book_id": row.id,
                }
            )

        # SKU duplicates (non-null)
        sku_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url, sb.sku "
                "FROM shop_books sb "
                "WHERE sb.shop_id = :shop_id "
                "  AND sb.sku IS NOT NULL "
                "  AND EXISTS ("
                "      SELECT 1 FROM shop_books sb2 "
                "      WHERE sb2.shop_id = :shop_id "
                "        AND sb2.sku = sb.sku "
                "        AND sb2.id != sb.id"
                "  )"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in sku_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "sku",
                    "issue": "sku_duplicate",
                    "raw_value": row.sku,
                    "shop_book_id": row.id,
                }
            )

        return results

    def check_slug_title_mismatch(
        self, shop_id: int, run_id: int
    ) -> list[dict[str, str | int | None]]:
        """Return ValidationIssue dicts for slug-title zero-token-overlap cases.

        Slug is derived from the last path segment of the product URL.
        Flags only when both slug_tokens and title_tokens are non-empty AND
        their intersection is empty (spec §Slug-title mismatch).
        """
        rows = self._session.execute(
            text(
                "SELECT id, url, title "
                "FROM shop_books "
                "WHERE shop_id = :shop_id AND title IS NOT NULL"
            ),
            {"shop_id": shop_id},
        ).all()

        results: list[dict[str, str | int | None]] = []
        for row in rows:
            slug = row.url.rstrip("/").rsplit("/", 1)[-1]
            if _should_flag_slug_title(slug, row.title):
                results.append(
                    {
                        "scrape_run_id": run_id,
                        "url": row.url,
                        "field": "slug",
                        "issue": "slug_title_mismatch",
                        "raw_value": slug,
                        "shop_book_id": row.id,
                    }
                )
        return results

    def check_data_completeness(
        self, shop_id: int, run_id: int
    ) -> list[dict[str, str | int | None]]:
        """Return ValidationIssue dicts for data completeness problems.

        Issue keys: active_no_price, in_stock_no_price, book_no_metadata,
        no_price_history.
        """
        results: list[dict[str, str | int | None]] = []

        # active_no_price: is_active=true AND price IS NULL
        active_no_price_rows = self._session.execute(
            text(
                "SELECT id, url FROM shop_books "
                "WHERE shop_id = :shop_id AND is_active = true AND price IS NULL"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in active_no_price_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "price",
                    "issue": "active_no_price",
                    "raw_value": None,
                    "shop_book_id": row.id,
                }
            )

        # in_stock_no_price: is_active=true AND in_stock=true AND price IS NULL
        in_stock_no_price_rows = self._session.execute(
            text(
                "SELECT id, url FROM shop_books "
                "WHERE shop_id = :shop_id AND is_active = true "
                "  AND in_stock = true AND price IS NULL"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in in_stock_no_price_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "price",
                    "issue": "in_stock_no_price",
                    "raw_value": None,
                    "shop_book_id": row.id,
                }
            )

        # book_no_metadata: type='book' AND isbn/author/year all NULL
        book_no_metadata_rows = self._session.execute(
            text(
                "SELECT id, url FROM shop_books "
                "WHERE shop_id = :shop_id AND type = 'book' "
                "  AND isbn IS NULL AND author IS NULL AND year IS NULL"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in book_no_metadata_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "metadata",
                    "issue": "book_no_metadata",
                    "raw_value": None,
                    "shop_book_id": row.id,
                }
            )

        # no_price_history: is_active=true AND no row in prices table
        no_price_history_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url FROM shop_books sb "
                "LEFT JOIN prices p ON p.shop_book_id = sb.id "
                "WHERE sb.shop_id = :shop_id AND sb.is_active = true AND p.id IS NULL"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in no_price_history_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "price_history",
                    "issue": "no_price_history",
                    "raw_value": None,
                    "shop_book_id": row.id,
                }
            )

        return results

    def check_data_correctness(
        self, shop_id: int, run_id: int
    ) -> list[dict[str, str | int | None]]:
        """Return ValidationIssue dicts for incorrect field values.

        Issue keys: year_out_of_range, price_zero, format_is_dimensions.
        """
        results: list[dict[str, str | int | None]] = []

        # year_out_of_range: year < 1800 OR year > current_year + 2
        year_rows = self._session.execute(
            text(
                "SELECT id, url, year FROM shop_books "
                "WHERE shop_id = :shop_id AND year IS NOT NULL "
                "  AND (year < 1800 OR year > extract(year from now())::int + 2)"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in year_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "year",
                    "issue": "year_out_of_range",
                    "raw_value": str(row.year),
                    "shop_book_id": row.id,
                }
            )

        # price_zero: price = 0
        price_zero_rows = self._session.execute(
            text(
                "SELECT id, url FROM shop_books WHERE shop_id = :shop_id AND price = 0"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in price_zero_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "price",
                    "issue": "price_zero",
                    "raw_value": "0",
                    "shop_book_id": row.id,
                }
            )

        # format_is_dimensions: format matches dimension pattern (e.g. '15x20')
        format_rows = self._session.execute(
            text(
                r"SELECT id, url, format FROM shop_books "
                r"WHERE shop_id = :shop_id AND format IS NOT NULL "
                r"  AND format ~ '^\d+.*[xX×].*\d+'"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in format_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "format",
                    "issue": "format_is_dimensions",
                    "raw_value": row.format,
                    "shop_book_id": row.id,
                }
            )

        return results

    def check_classification_consistency(
        self, shop_id: int, run_id: int
    ) -> list[dict[str, str | int | None]]:
        """Return ValidationIssue dicts for classification inconsistencies.

        Issue keys: book_no_signals, non_book_has_isbn, non_product_active.
        """
        results: list[dict[str, str | int | None]] = []

        # book_no_signals: type='book' with no discriminating metadata
        book_no_signals_rows = self._session.execute(
            text(
                "SELECT id, url FROM shop_books "
                "WHERE shop_id = :shop_id AND type = 'book' "
                "  AND isbn IS NULL AND author IS NULL "
                "  AND year IS NULL AND format IS NULL"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in book_no_signals_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "type",
                    "issue": "book_no_signals",
                    "raw_value": None,
                    "shop_book_id": row.id,
                }
            )

        # non_book_has_isbn: type='non_book' AND isbn IS NOT NULL
        non_book_isbn_rows = self._session.execute(
            text(
                "SELECT id, url, isbn FROM shop_books "
                "WHERE shop_id = :shop_id AND type = 'non_book' AND isbn IS NOT NULL"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in non_book_isbn_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "type",
                    "issue": "non_book_has_isbn",
                    "raw_value": row.isbn,
                    "shop_book_id": row.id,
                }
            )

        # non_product_active: url_type='non_product' AND shop_book is_active=true
        # Join via discovered_urls.shop_book_id FK
        non_product_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url FROM shop_books sb "
                "JOIN discovered_urls du ON du.shop_book_id = sb.id "
                "WHERE sb.shop_id = :shop_id AND sb.is_active = true "
                "  AND du.url_type = 'non_product'"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in non_product_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "url_type",
                    "issue": "non_product_active",
                    "raw_value": "non_product",
                    "shop_book_id": row.id,
                }
            )

        return results

    def check_staleness(
        self, shop_id: int, run_id: int
    ) -> list[dict[str, str | int | None]]:
        """Return ValidationIssue dicts for staleness problems.

        Issue keys: stale_active, unreachable_active, orphan_no_url.
        """
        results: list[dict[str, str | int | None]] = []

        days = 2 * VALIDATE_STALE_CADENCE_DAYS

        # stale_active: is_active=true AND last_seen_at older than 2 * cadence days
        stale_rows = self._session.execute(
            text(
                "SELECT id, url, last_seen_at FROM shop_books "
                "WHERE shop_id = :shop_id AND is_active = true "
                "  AND last_seen_at < now() - make_interval(days => :days)"
            ),
            {"shop_id": shop_id, "days": days},
        ).all()
        for row in stale_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "last_seen_at",
                    "issue": "stale_active",
                    "raw_value": row.last_seen_at.isoformat(),
                    "shop_book_id": row.id,
                }
            )

        # unreachable_active: discovered_urls.url_type='unreachable' AND is_active=true
        unreachable_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url FROM shop_books sb "
                "JOIN discovered_urls du ON du.shop_book_id = sb.id "
                "WHERE sb.shop_id = :shop_id AND sb.is_active = true "
                "  AND du.url_type = 'unreachable'"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in unreachable_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "url_type",
                    "issue": "unreachable_active",
                    "raw_value": "unreachable",
                    "shop_book_id": row.id,
                }
            )

        # orphan_no_url: shop_books with no matching discovered_urls row
        orphan_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url FROM shop_books sb "
                "LEFT JOIN discovered_urls du ON du.shop_book_id = sb.id "
                "WHERE sb.shop_id = :shop_id AND du.id IS NULL"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in orphan_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "url",
                    "issue": "orphan_no_url",
                    "raw_value": row.url,
                    "shop_book_id": row.id,
                }
            )

        return results

    def check_match_readiness(
        self, shop_id: int, run_id: int
    ) -> list[dict[str, str | int | None]]:
        """Return ValidationIssue dicts for match-phase readiness problems.

        Issue keys: unmatched_has_isbn, match_isbn_drift.

        Note: books table has no direct isbn column — ISBNs live in book_isbns.
        match_isbn_drift joins shop_books -> books -> book_isbns to detect
        ISBN mismatch after matching.
        """
        results: list[dict[str, str | int | None]] = []

        # unmatched_has_isbn: match_status='unmatched' AND isbn IS NOT NULL
        unmatched_rows = self._session.execute(
            text(
                "SELECT id, url, isbn FROM shop_books "
                "WHERE shop_id = :shop_id AND match_status = 'unmatched' "
                "  AND isbn IS NOT NULL"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in unmatched_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "match_status",
                    "issue": "unmatched_has_isbn",
                    "raw_value": row.isbn,
                    "shop_book_id": row.id,
                }
            )

        # match_isbn_drift: matched shop_book isbn differs from book_isbns
        # Join: shop_books -> books (book_id) -> book_isbns
        drift_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url, sb.isbn AS sb_isbn, bi.isbn AS book_isbn "
                "FROM shop_books sb "
                "JOIN books b ON b.id = sb.book_id "
                "JOIN book_isbns bi ON bi.book_id = b.id "
                "WHERE sb.shop_id = :shop_id "
                "  AND sb.match_status = 'matched' "
                "  AND sb.isbn IS NOT NULL "
                "  AND bi.isbn IS NOT NULL "
                "  AND bi.isbn != sb.isbn"
            ),
            {"shop_id": shop_id},
        ).all()
        seen_drift: set[int] = set()
        for row in drift_rows:
            if row.id in seen_drift:
                continue
            seen_drift.add(row.id)
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "isbn",
                    "issue": "match_isbn_drift",
                    "raw_value": f"{row.sb_isbn} vs {row.book_isbn}",
                    "shop_book_id": row.id,
                }
            )

        return results

    def check_relationship_integrity(
        self, shop_id: int, run_id: int
    ) -> list[dict[str, str | int | None]]:
        """Return ValidationIssue dicts for URL relationship integrity problems.

        Issue keys: url_aliases, product_url_non_book.
        """
        results: list[dict[str, str | int | None]] = []

        # url_aliases: shop_books with >1 discovered_urls row (shop_book_id FK)
        aliases_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url, COUNT(du.id) AS n "
                "FROM shop_books sb "
                "JOIN discovered_urls du ON du.shop_book_id = sb.id "
                "WHERE sb.shop_id = :shop_id "
                "GROUP BY sb.id, sb.url "
                "HAVING COUNT(du.id) > 1"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in aliases_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "url",
                    "issue": "url_aliases",
                    "raw_value": str(row.n),
                    "shop_book_id": row.id,
                }
            )

        # product_url_non_book: url_type='product' but shop_book type='non_book'
        product_non_book_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url FROM shop_books sb "
                "JOIN discovered_urls du ON du.shop_book_id = sb.id "
                "WHERE sb.shop_id = :shop_id "
                "  AND du.url_type = 'product' AND sb.type = 'non_book'"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in product_non_book_rows:
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": row.url,
                    "field": "type",
                    "issue": "product_url_non_book",
                    "raw_value": "non_book",
                    "shop_book_id": row.id,
                }
            )

        return results
