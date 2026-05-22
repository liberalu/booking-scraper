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
  - Relationship integrity: url_aliases

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
from urllib.parse import unquote

from sqlalchemy import text
from sqlalchemy.orm import Session

from book_scraper.db.repo import resolve_gone_issues, upsert_validation_issues

# Per-shop discover cadence threshold used by the stale_active check (plan 03).
# Deferred to v2: per-shop cadence field in DB (CONTEXT.md decision D-defer-1).
VALIDATE_STALE_CADENCE_DAYS: int = 14


def _tokenize(s: str) -> set[str]:
    """Lowercase, strip diacritics (NFD + filter Mn category), extract
    alphanumeric runs.

    Splitting on anything non-alphanumeric handles punctuation like the
    Lithuanian opening quote (``„``), closing quote, periods, and other
    typography that otherwise glues onto adjacent words and prevents
    title tokens (e.g. ``„menulio``, ``geles"``, ``e.knyga``) from
    matching their slug counterparts.
    """
    if not s:
        return set()
    nfd = unicodedata.normalize("NFD", s.lower())
    ascii_only = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return set(re.findall(r"[a-z0-9]+", ascii_only))


# OpenCart legacy route URL pattern (vaga.lt). The shop's underlying
# platform exposes every product at both a SEO slug URL and a raw
# `index.php?route=product/product&product_id=NNN` URL. The two URL
# shapes coexist by platform design; flagging them as data-quality
# aliases is noise. Matches both the raw and percent-encoded slash
# forms (`route=product/product` and `route=product%2Fproduct`).
_OPENCART_ROUTE_RE = re.compile(
    r"index\.php\?route=product(?:/|%2F)product&product_id=\d+", re.IGNORECASE
)


def _is_genuine_url_alias(canon_url: str, alias_url: str) -> bool:
    """True iff the alias_url is a genuinely different URL shape from
    canon_url — i.e. they survive URL-decoding + OpenCart-route stripping.

    Filters out the two real-world false-positive classes observed on
    vaga.lt (see the call-site in `check_relationship_integrity`).
    """
    if not canon_url or not alias_url:
        return False
    # OpenCart route URLs are platform-level aliases — never genuine.
    if _OPENCART_ROUTE_RE.search(alias_url) or _OPENCART_ROUTE_RE.search(canon_url):
        return False
    # URL-decode both sides and compare. Handles `mi%C5%A1ku-...` vs
    # `mišku-...` and `route=product%2Fproduct` vs `route=product/product`.
    canon_dec = unquote(canon_url).rstrip("/")
    alias_dec = unquote(alias_url).rstrip("/")
    if canon_dec == alias_dec:
        return False
    # Also re-apply the last-segment-differs gate after decoding (the SQL
    # gate runs on the raw strings; decoded forms can match where raw
    # forms don't).
    canon_last = canon_dec.rsplit("/", 1)[-1]
    alias_last = alias_dec.rsplit("/", 1)[-1]
    return canon_last != alias_last


# Lithuanian category keywords that indicate a non-book product. When
# any of these appears in a shop_book's `categories` array, it's a
# legitimate non-book (puzzle, game, notebook, map, hobby item, etc.)
# even if it carries an ISBN — many LT publishers register such products
# under ISBN. Diacritic-stripped keys handle NFD-stored values; both
# raw and stripped variants are checked for safety.
_NON_BOOK_CATEGORY_KEYWORDS: tuple[str, ...] = (
    "zaisl",      # žaislai (toys)
    "zaidim",     # žaidimai (games)
    "delion",     # dėlionės (puzzles / jigsaws)
    "sasiuvin",   # sąsiuviniai (notebooks)
    "kortel",     # kortelės (cards)
    "zemelap",    # žemėlapiai (maps)
    "rastin",     # raštinės prekės (office supplies)
    "hobio",      # hobio prekės (hobby goods)
    "mokyklin",   # mokyklinės prekės (school supplies)
    "popier",     # popieriaus gaminiai (paper goods)
    "lavinam",    # lavinamieji (educational toys)
    "stalo zaid", # stalo žaidimai (board games — covers cases where kw above misses)
)


def _categories_indicate_non_book(categories: list[str] | None) -> bool:
    """True iff any category in the list contains a recognised non-book
    keyword (diacritic-insensitive).

    Used by `non_book_has_isbn` to suppress legitimate non-book products
    that happen to carry a publisher-issued ISBN (jigsaw puzzles, board
    games, learning cards, notebooks, etc.).
    """
    if not categories:
        return False
    blob = " | ".join(str(c) for c in categories).lower()
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", blob)
        if unicodedata.category(c) != "Mn"
    )
    return any(kw in stripped for kw in _NON_BOOK_CATEGORY_KEYWORDS)


# Title-pattern markers that clearly identify a product as not a book.
# Used by `non_book_has_isbn` to suppress noise on shops whose catalogue
# mixes books and non-books at the same URL path (patogupirkti's /knyga/
# sells DVDs, CDs, bundles too).
_NON_BOOK_TITLE_RE = re.compile(
    r"\((DVD|Blu[-\s]?ray|CD|MP3|VHS|USB|Vinyl)\)"  # parenthesised format markers
    r"|\b(rinkinys|komplektas|set|bundle)\b"  # bundle / set markers
    r"|kompaktine|audioknyga|audio kasete|garsine knyga",  # audio formats
    re.IGNORECASE,
)


def _title_indicates_non_book(title: str | None) -> bool:
    """True iff the title contains a marker that the item is not a book
    (DVD/CD/bundle, etc.). See `_NON_BOOK_TITLE_RE`."""
    if not title:
        return False
    return bool(_NON_BOOK_TITLE_RE.search(title))


# Lithuanian diacritic-bearing characters.  When a shop's slug generator
# drops these instead of transliterating, the slug fragments into short
# letter runs ("Kalėdų pūga" → "kale-du-pu-ga") — distinct from a normal
# slug like "kaledu-puga".  Flagged via `check_slug_diacritic_loss`.
_LT_DIACRITICS: frozenset[str] = frozenset("ąčęėįšųūžĄČĘĖĮŠŲŪŽ")

# Match alphabetic runs in the title to count "words" (independent of
# diacritics — `Kalėdų` is one word). We don't care about case here.
_TITLE_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Strip the trailing numeric SKU suffix (e.g. "-2196148") so we can count
# the alphabetic pieces of the slug fairly against the title's word count.
_SLUG_SKU_SUFFIX_RE = re.compile(r"-\d+$")


def _looks_diacritic_lossy(slug: str | None, title: str | None) -> bool:
    """True iff the slug has more alphabetic pieces than the title has
    words, AND the title contains Lithuanian diacritics.

    The smoking gun for a diacritic-loss bug:
    - Title `Kalėdų pūga` has 2 words; the correct slug is `kaledu-puga`
      (2 pieces).  The buggy slug `kale-du-pu-ga` has 4 pieces, meaning
      the shop's slug generator split a single word at each dropped
      diacritic.
    - Title `Tu. Aš. Mes` has 3 words; slug `tu-as-mes` has 3 pieces.
      3 ≤ 3 → not flagged (correctly transliterated short words).
    - Title `Kodėl gi ne` has 3 words; slug `kodel-gi-ne` has 3 pieces.
      3 ≤ 3 → not flagged.

    The diacritic gate restricts the check to LT-flavoured titles, the
    only place we've seen the bug in the wild.
    """
    if not slug or not title:
        return False
    # Normalise to NFC so combining-mark sequences (`e` + U+0307) collapse
    # into precomposed chars (`ė`). The DB stores titles in NFD form;
    # without normalisation the diacritic membership check fails AND the
    # title-word regex treats each combining mark as a word boundary,
    # tripling the apparent word count and masking the bug.
    title_nfc = unicodedata.normalize("NFC", title)
    if not any(c in _LT_DIACRITICS for c in title_nfc):
        return False
    cleaned = _SLUG_SKU_SUFFIX_RE.sub("", slug.lower().strip("/"))
    slug_pieces = [p for p in cleaned.split("-") if p.isalpha()]
    if len(slug_pieces) < 3:
        # Below 3 pieces, the count comparison is too noisy. The bug
        # always manifests as ≥4 pieces (the title has ≥2 multi-syllable
        # diacritic words).
        return False
    title_word_count = len(_TITLE_WORD_RE.findall(title_nfc))
    return len(slug_pieces) > title_word_count


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
        issues.extend(self.check_slug_diacritic_loss(shop_id, run_id))
        issues.extend(self.check_data_completeness(shop_id, run_id))
        issues.extend(self.check_data_correctness(shop_id, run_id))
        issues.extend(self.check_classification_consistency(shop_id, run_id))
        issues.extend(self.check_staleness(shop_id, run_id))
        issues.extend(self.check_match_readiness(shop_id, run_id))
        issues.extend(self.check_relationship_integrity(shop_id, run_id))

        if issues:
            upsert_validation_issues(
                self._session, issues, shop_id=shop_id, run_id=run_id
            )

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

        # ISBN duplicates — only real ISBNs (non-empty) so stale '' values
        # stored before the pipeline's isbn-null-out logic don't collide.
        # Restricted to is_active=true rows on both sides: when an operator
        # (or the auto-dedup cleanup, 2026-05-19) deactivates one row of a
        # duplicate pair, the issue is by definition resolved — the active
        # catalogue no longer has a duplicate. Without this filter,
        # historical dedup work doesn't clear the open issues.
        isbn_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url, sb.isbn "
                "FROM shop_books sb "
                "WHERE sb.shop_id = :shop_id "
                "  AND sb.is_active = true "
                "  AND sb.isbn IS NOT NULL AND sb.isbn != '' "
                "  AND EXISTS ("
                "      SELECT 1 FROM shop_books sb2 "
                "      WHERE sb2.shop_id = :shop_id "
                "        AND sb2.is_active = true "
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

        # Title + author duplicates (case-insensitive, both non-null).
        # Only flag when ISBNs also match (or both are null) — same title+author
        # with DIFFERENT ISBNs is a legitimate re-edition, not a duplicate URL.
        # is_active filter — see comment above for rationale.
        title_author_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url, sb.title, sb.author "
                "FROM shop_books sb "
                "WHERE sb.shop_id = :shop_id "
                "  AND sb.is_active = true "
                "  AND sb.title IS NOT NULL "
                "  AND sb.author IS NOT NULL "
                "  AND EXISTS ("
                "      SELECT 1 FROM shop_books sb2 "
                "      WHERE sb2.shop_id = :shop_id "
                "        AND sb2.is_active = true "
                "        AND lower(sb2.title) = lower(sb.title) "
                "        AND lower(sb2.author) = lower(sb.author) "
                "        AND sb2.id != sb.id "
                "        AND (sb2.isbn = sb.isbn "
                "             OR (sb2.isbn IS NULL AND sb.isbn IS NULL))"
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

        # SKU duplicates (non-null). is_active filter — see ISBN block above.
        sku_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url, sb.sku "
                "FROM shop_books sb "
                "WHERE sb.shop_id = :shop_id "
                "  AND sb.is_active = true "
                "  AND sb.sku IS NOT NULL "
                "  AND EXISTS ("
                "      SELECT 1 FROM shop_books sb2 "
                "      WHERE sb2.shop_id = :shop_id "
                "        AND sb2.is_active = true "
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
                "WHERE shop_id = :shop_id AND title IS NOT NULL "
                "  AND is_active = true"
            ),
            {"shop_id": shop_id},
        ).all()

        results: list[dict[str, str | int | None]] = []
        for row in rows:
            slug = row.url.rstrip("/").rsplit("/", 1)[-1]
            if not _should_flag_slug_title(slug, row.title):
                continue
            # Supersession: if the slug-title mismatch is explained by
            # diacritic-loss (a more specific, actionable issue type),
            # don't also fire the broader slug_title_mismatch on the same
            # book — `check_slug_diacritic_loss` raises that pattern with
            # its own dedicated issue. The historical slug_title_mismatch
            # entry on these books then auto-closes via resolve_gone_issues
            # because this validate run no longer re-emits it.
            if _looks_diacritic_lossy(slug, row.title):
                continue
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

    def check_slug_diacritic_loss(
        self, shop_id: int, run_id: int
    ) -> list[dict[str, str | int | None]]:
        """Return ValidationIssue dicts for slugs that look diacritic-lossy.

        Catches the pegasas-style "Kalėdų pūga" → "kale-du-pu-ga-2196148"
        pattern where the shop's slug generator drops Lithuanian diacritic
        characters entirely instead of transliterating them.  These slugs
        already trigger slug_title_mismatch via token-overlap zero, but
        the dedicated issue type makes the shop-side bug pattern
        trendable and reportable separately. Severity is `info`.
        """
        rows = self._session.execute(
            text(
                "SELECT id, url, title FROM shop_books "
                "WHERE shop_id = :shop_id AND title IS NOT NULL "
                "  AND is_active = true"
            ),
            {"shop_id": shop_id},
        ).all()

        results: list[dict[str, str | int | None]] = []
        for row in rows:
            slug = row.url.rstrip("/").rsplit("/", 1)[-1]
            if _looks_diacritic_lossy(slug, row.title):
                results.append(
                    {
                        "scrape_run_id": run_id,
                        "url": row.url,
                        "field": "slug",
                        "issue": "slug_diacritic_loss",
                        "raw_value": slug,
                        "shop_book_id": row.id,
                        # The diacritic-loss pattern is a shop-side bug in
                        # the slug generator — we will never fix it on our
                        # side.  Start as "acknowledged" so the issue never
                        # lands in the "new" queue and requires manual ack.
                        "initial_state": "acknowledged",
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

        # active_no_price: is_active=true AND in_stock=true AND price IS NULL.
        # `in_stock=true` filter mirrors the suppression already applied to
        # `zero_price` and `missing_price`: out-of-stock books are
        # legitimately unbuyable and don't need a current price — flagging
        # them is noise. With this filter the check overlaps with
        # `in_stock_no_price` (it adds nothing beyond what that check
        # already surfaces). Kept as a distinct issue type for backward
        # compatibility — operators with existing acknowledgements keep
        # them tied to the same issue key.
        active_no_price_rows = self._session.execute(
            text(
                "SELECT id, url FROM shop_books "
                "WHERE shop_id = :shop_id AND is_active = true "
                "  AND in_stock = true AND price IS NULL"
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

        # no_price_history: is_active=true AND in_stock=true AND no prices
        # row. `in_stock=true` filter — same rationale as active_no_price
        # above. An out-of-stock book with no historical price isn't a
        # data-quality problem worth surfacing; it's a never-listed item.
        no_price_history_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url FROM shop_books sb "
                "LEFT JOIN prices p ON p.shop_book_id = sb.id "
                "WHERE sb.shop_id = :shop_id AND sb.is_active = true "
                "  AND sb.in_stock = true AND p.id IS NULL"
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
                "  AND is_active = true "
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

        # price_zero: price = 0 AND item is active/in-stock.
        # Out-of-stock items on some shops (pegasas) legitimately return price=0
        # when no listing price is available — suppress those to avoid noise.
        price_zero_rows = self._session.execute(
            text(
                "SELECT id, url FROM shop_books "
                "WHERE shop_id = :shop_id AND price = 0 AND in_stock = true"
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

        # non_book_has_isbn: type='non_book' AND real ISBN (978/979 prefix)
        # EAN barcodes (non-978/979) on non-book items are expected and not
        # suspicious — they're just product GTINs. Only real ISBNs indicate
        # a potential misclassification worth investigating.
        #
        # BUT: many Lithuanian publishers register non-book products
        # (jigsaw puzzles, board games, learning cards, notebooks, maps,
        # children's activity sets) under ISBN. Those items have correct
        # type='non_book' AND a legitimate publisher ISBN — flagging them
        # generates noise (~44 vaga + 12 pegasas, all genuine non-books).
        #
        # Filter: skip rows whose categories OR titles clearly indicate
        # a non-book product. The title-pattern filter (added 2026-05-20)
        # catches patogupirkti's DVD/CD/bundle listings whose categories
        # are mis-labelled "Grožinė literatūra" but title says "(DVD)" /
        # "(CD)" / "rinkinys".
        non_book_isbn_rows = self._session.execute(
            text(
                "SELECT id, url, isbn, title, categories FROM shop_books "
                "WHERE shop_id = :shop_id AND type = 'non_book' AND isbn IS NOT NULL "
                "AND isbn ~ '^97[89]'"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in non_book_isbn_rows:
            if _categories_indicate_non_book(row.categories):
                continue
            if _title_indicates_non_book(row.title):
                continue
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
        #
        # Auto-heal step: when ALL of a shop_book's discovered_urls are
        # non_product, the scan has confirmed the listing is gone (delisted,
        # out-of-scope, or a non-book that leaked through discover). The
        # shop_book should be flipped to is_active=false to match reality.
        # This is the common case (~99% of these issues — see pegasas
        # cleanup, 2026-05-17, 1,945 rows). We deactivate first, then only
        # flag the residual cases where SOME (but not all) URLs are
        # non_product — those need human investigation.
        self._session.execute(
            text(
                "UPDATE shop_books sb "
                "SET is_active = false, inactive_since = NOW() "
                "WHERE sb.shop_id = :shop_id AND sb.is_active = true "
                "  AND NOT EXISTS ("
                "      SELECT 1 FROM discovered_urls du "
                "      WHERE du.shop_book_id = sb.id "
                "        AND du.url_type != 'non_product'"
                "  ) "
                "  AND EXISTS ("
                "      SELECT 1 FROM discovered_urls du "
                "      WHERE du.shop_book_id = sb.id "
                "        AND du.url_type = 'non_product'"
                "  )"
            ),
            {"shop_id": shop_id},
        )

        # Flag the residual cases — shop_books that are still active but
        # have at least one non_product URL alongside still-good ones.
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
                "  AND is_active = true "
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

        # match_isbn_drift: matched shop_book isbn is not present in book_isbns at all.
        # A book can have both isbn13 and isbn10 — only flag drift when the shop's ISBN
        # matches none of the canonical book's ISBN records (NOT EXISTS), not just one.
        # Normalise ISBN-13 vs ISBN-10: compare the first 9 body digits so that
        # e.g. '9789986092476' (ISBN-13) and '9986092476' (ISBN-10) are treated as
        # equivalent (they share the same 9-digit body '998609247').
        drift_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url, sb.isbn AS sb_isbn, "
                "  (SELECT bi2.isbn FROM book_isbns bi2 WHERE bi2.book_id = b.id "
                "   ORDER BY bi2.isbn_type DESC LIMIT 1) AS book_isbn "
                "FROM shop_books sb "
                "JOIN books b ON b.id = sb.book_id "
                "WHERE sb.shop_id = :shop_id "
                "  AND sb.is_active = true "
                "  AND sb.match_status = 'matched' "
                "  AND sb.isbn IS NOT NULL "
                "  AND NOT EXISTS ("
                "    SELECT 1 FROM book_isbns bi "
                "    WHERE bi.book_id = b.id "
                "      AND ("
                "        bi.isbn = sb.isbn "
                "        OR (length(bi.isbn) = 10 AND length(sb.isbn) = 13 "
                "            AND substring(sb.isbn, 4, 9) = substring(bi.isbn, 1, 9)) "
                "        OR (length(sb.isbn) = 10 AND length(bi.isbn) = 13 "
                "            AND substring(bi.isbn, 4, 9) = substring(sb.isbn, 1, 9))"
                "      )"
                "  )"
            ),
            {"shop_id": shop_id},
        ).all()
        for row in drift_rows:
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

        Issue keys: url_aliases.
        """
        results: list[dict[str, str | int | None]] = []

        # url_aliases: shop_books with >1 discovered_urls row where the alias URL
        # is not just a category-prefixed variant of the canonical URL.
        # vaga.lt exposes products at both /slug and /cat/subcat/slug — both end
        # with the same final path segment and are the same product, not a real alias.
        # Only flag when there's an alias URL whose final segment differs from the
        # canonical URL's final segment (genuinely different URL shapes).
        # rtrim('/') normalises trailing slashes so /slug and /slug/ aren't
        # treated as different shapes (pegasas serves both, same content).
        #
        # Python post-filter handles two real-world false positive classes
        # uncovered during the 2026-05-18 cleanup:
        #
        # 1. URL-encoding mismatches. Vaga has rows where the canonical URL
        #    contains percent-encoded Lithuanian chars (e.g. `mi%C5%A1ku-...`)
        #    while a discovered_urls row contains the decoded form
        #    (`mišku-...`). They're identical URLs, just different encodings.
        # 2. OpenCart legacy route URLs (vaga.lt's underlying platform).
        #    Every product is reachable via both a SEO slug
        #    (`/uzrasu-knygele-lotus-river-...`) AND an `index.php?route=
        #    product/product&product_id=NNN` URL. These are platform-level
        #    aliases for the same product, not data-quality issues.
        candidate_rows = self._session.execute(
            text(
                "SELECT sb.id, sb.url, du.url AS alias_url "
                "FROM shop_books sb "
                "JOIN discovered_urls du ON du.shop_book_id = sb.id "
                "WHERE sb.shop_id = :shop_id "
                "  AND rtrim(du.url, '/') != rtrim(sb.url, '/') "
                "  AND regexp_replace(rtrim(du.url, '/'), '^.+/', '') "
                "    != regexp_replace(rtrim(sb.url, '/'), '^.+/', '')"
            ),
            {"shop_id": shop_id},
        ).all()
        per_sb: dict[int, tuple[str, int]] = {}
        for row in candidate_rows:
            if not _is_genuine_url_alias(row.url, row.alias_url):
                continue
            existing = per_sb.get(row.id)
            if existing is None:
                per_sb[row.id] = (row.url, 1)
            else:
                per_sb[row.id] = (existing[0], existing[1] + 1)
        for sb_id, (canon_url, count) in per_sb.items():
            results.append(
                {
                    "scrape_run_id": run_id,
                    "url": canon_url,
                    "field": "url",
                    "issue": "url_aliases",
                    "raw_value": str(count),
                    "shop_book_id": sb_id,
                }
            )

        return results
