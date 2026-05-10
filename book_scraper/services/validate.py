"""Validate service: runs data-quality checks over shop_books rows.

Checks implemented here (plans 02 + 03):
  - Structural duplicates: isbn_duplicate, title_author_duplicate, sku_duplicate
  - Slug-title mismatch: slug_title_mismatch

Results are written to validation_issues via bulk_insert_validation_issues,
which handles (shop_book_id, field, issue) deduplication lifecycle
(_assign_lifecycle_states transitions recurring rows automatically).

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

from book_scraper.db.repo import bulk_insert_validation_issues

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

        if issues:
            bulk_insert_validation_issues(self._session, issues, shop_id=shop_id)

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
