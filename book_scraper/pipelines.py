import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from itemadapter import ItemAdapter
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from sqlalchemy.orm import Session, sessionmaker

from book_scraper.db.repo import (
    bulk_insert_validation_issues,
    increment_scrape_run_stats,
    insert_price,
    update_scrape_run_progress,
    upsert_discovered_url,
    upsert_listing,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory
from book_scraper.items import DiscoveredUrlItem, ListingItem, PriceItem

logger = logging.getLogger(__name__)

_ISBN_13_RE = re.compile(r"^97[89]\d{10}$")
_ISBN_10_RE = re.compile(r"^\d{9}[\dXx]$")
_HTML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")

_MIN_YEAR = 1800
_MAX_YEAR = 2030


def _validate_year(adapter: ItemAdapter) -> None:
    """Validate and fix year field. Detect year/pages swap."""
    year = adapter.get("year")
    if year is None:
        return

    try:
        year = int(year)
    except (ValueError, TypeError):
        adapter["year"] = None
        return

    if _MIN_YEAR <= year <= _MAX_YEAR:
        adapter["year"] = year
        return

    # Possible swap: year has page count, pages has year
    props = adapter.get("properties")
    if isinstance(props, dict) and "pages" in props:
        try:
            pages = int(props["pages"])
        except (ValueError, TypeError):
            pages = None
        if pages is not None and _MIN_YEAR <= pages <= _MAX_YEAR:
            adapter["year"] = pages
            props["pages"] = year
            return

    # Year out of range and no swap possible — clear it
    adapter["year"] = None


def _is_valid_isbn(raw: str) -> bool:
    """Check if a string is a valid ISBN-10 or ISBN-13."""
    cleaned = raw.replace("-", "").replace(" ", "")
    if _ISBN_13_RE.match(cleaned):
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(cleaned))
        return total % 10 == 0
    if _ISBN_10_RE.match(cleaned):
        total = sum(
            (10 if c in "Xx" else int(c)) * (10 - i) for i, c in enumerate(cleaned)
        )
        return total % 11 == 0
    return False


class ValidationPipeline:
    def __init__(self, stats: Any = None):
        self.stats = stats
        self.issues: list[dict[str, str | int | None]] = []

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "ValidationPipeline":
        pipeline = cls(stats=crawler.stats)
        crawler.validation_pipeline = pipeline  # type: ignore[attr-defined]
        return pipeline

    def _warn(self, issue: str, field: str, url: str, raw_value: str = "") -> None:
        if self.stats:
            self.stats.inc_value(f"validation/{issue}")
        self.issues.append(
            {
                "url": url,
                "field": field,
                "issue": issue,
                "raw_value": raw_value or None,
            }
        )
        logger.warning(
            "Validation [%s] field=%s url=%s %s",
            issue,
            field,
            url,
            raw_value,
        )

    def _check_price_anomalies(self, adapter: ItemAdapter, url: str) -> None:
        price = adapter.get("price")
        if price is None:
            self._warn("missing_price", "price", url)
            return
        price_dec = Decimal(str(price))
        if price_dec == 0:
            self._warn("zero_price", "price", url, str(price))
        price_original = adapter.get("price_original")
        if price_original is not None:
            orig_dec = Decimal(str(price_original))
            if orig_dec > 0 and price_dec > orig_dec:
                self._warn(
                    "price_higher_than_original",
                    "price",
                    url,
                    f"{price}>{price_original}",
                )

    def _check_content_quality(self, adapter: ItemAdapter, url: str) -> None:
        for field in ("title", "author", "description"):
            val = adapter.get(field)
            if isinstance(val, str) and _HTML_TAG_RE.search(val):
                self._warn("html_in_text", field, url, val[:100])
        title = adapter.get("title")
        if isinstance(title, str):
            if len(title) < 2:
                self._warn(
                    "suspicious_title",
                    "title",
                    url,
                    title,
                )
            elif len(title) > 300:
                self._warn(
                    "suspicious_title",
                    "title",
                    url,
                    f"len={len(title)}",
                )

    def _check_format_consistency(self, adapter: ItemAdapter, url: str) -> None:
        fmt = adapter.get("format")
        props = adapter.get("properties") or {}
        if fmt == "audiobook" and "pages" in props:
            self._warn(
                "format_mismatch",
                "format",
                url,
                "audiobook with pages",
            )
        if fmt in ("book", "hardcover", "paperback") and "duration" in props:
            self._warn(
                "format_mismatch",
                "format",
                url,
                f"{fmt} with duration",
            )

    def drain_issues(self) -> list[dict[str, str | int | None]]:
        """Return buffered issues and clear the buffer."""
        issues = self.issues
        self.issues = []
        return issues

    def process_item(self, item: Any) -> Any:
        adapter = ItemAdapter(item)
        url = adapter.get("url", "")

        if isinstance(item, (ListingItem, PriceItem)):
            price = adapter.get("price")
            if price is not None:
                try:
                    adapter["price"] = str(Decimal(str(price)))
                except (InvalidOperation, ValueError) as err:
                    self._warn("invalid_price", "price", url, str(price))
                    raise DropItem(f"Invalid price: {price}") from err

            price_original = adapter.get("price_original")
            if price_original is not None:
                try:
                    adapter["price_original"] = str(Decimal(str(price_original)))
                except (InvalidOperation, ValueError):
                    self._warn(
                        "invalid_price_original",
                        "price_original",
                        url,
                        str(price_original),
                    )
                    adapter["price_original"] = None

            # Price anomaly checks (after decimal conversion)
            self._check_price_anomalies(adapter, url)

        if isinstance(item, ListingItem):
            if not adapter.get("title"):
                self._warn("missing_title", "title", url)
                raise DropItem("Missing title")

            isbn = adapter.get("isbn")
            if isbn is not None and not _is_valid_isbn(isbn):
                self._warn("invalid_isbn", "isbn", url, str(isbn))
                adapter["isbn"] = None

            year_before = adapter.get("year")
            _validate_year(adapter)
            year_after = adapter.get("year")
            if year_before is not None and year_after is None:
                self._warn("invalid_year", "year", url, str(year_before))
            elif year_before is not None and year_before != year_after:
                self._warn("year_pages_swap", "year", url, str(year_before))

            # Strip whitespace from text fields
            for field in ("title", "author", "publisher"):
                val = adapter.get(field)
                if isinstance(val, str):
                    val = val.strip()
                    adapter[field] = val or None

            if not url or not url.startswith(("http://", "https://")):
                self._warn("invalid_url", "url", url)
                raise DropItem(f"Invalid URL: {url}")

            # Content quality checks
            self._check_content_quality(adapter, url)

            # Format consistency
            self._check_format_consistency(adapter, url)

        return item


class PostgresPipeline:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.session_factory: sessionmaker[Session] | None = None
        self.session: Session | None = None
        self.shop_cache: dict[str, int] = {}
        self.crawler: Crawler | None = None
        self._item_count: int = 0
        self._stats_added: int = 0
        self._stats_updated: int = 0

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "PostgresPipeline":  # pragma: no cover
        pipeline = cls(database_url=crawler.settings.get("DATABASE_URL"))
        pipeline.crawler = crawler
        return pipeline

    def open_spider(self) -> None:  # pragma: no cover
        self.session_factory = get_session_factory(self.database_url)
        self.session = self.session_factory()

    def close_spider(self) -> None:  # pragma: no cover
        if self.session:
            spider = self.spider
            if spider and hasattr(spider, "_run_id") and spider._run_id:
                self._flush_stats(spider._run_id)
                self._flush_validation_issues(spider._run_id)
            self.session.commit()
            self.session.close()

    @property
    def spider(self) -> Any:
        return self.crawler.spider if self.crawler else None

    @property
    def _run_id(self) -> int | None:
        spider = self.spider
        if spider and hasattr(spider, "_run_id"):
            run_id: int | None = spider._run_id
            return run_id
        return None

    def _flush_stats(self, run_id: int) -> None:
        if self._stats_added or self._stats_updated:
            assert self.session is not None
            increment_scrape_run_stats(
                self.session,
                run_id,
                items_added=self._stats_added,
                items_updated=self._stats_updated,
            )
            self._stats_added = 0
            self._stats_updated = 0

    def _flush_validation_issues(self, run_id: int) -> None:
        assert self.session is not None
        vp: ValidationPipeline | None = getattr(
            self.crawler, "validation_pipeline", None
        )
        if vp is None:
            return
        issues = vp.drain_issues()
        for issue in issues:
            issue["scrape_run_id"] = run_id
        bulk_insert_validation_issues(self.session, issues)

    _SPIKE_THRESHOLD = Decimal("0.5")  # 50%

    def _check_price_spike(
        self,
        url: str,
        old_price: Decimal | None,
        new_price: Decimal | None,
    ) -> None:
        if old_price is None or new_price is None or old_price == 0:
            return
        change = abs(new_price - old_price) / old_price
        if change > self._SPIKE_THRESHOLD:
            vp: ValidationPipeline | None = getattr(
                self.crawler, "validation_pipeline", None
            )
            if vp is not None:
                vp._warn(
                    "price_spike",
                    "price",
                    url,
                    f"{old_price}->{new_price} ({change:.0%})",
                )

    def _report_field_changes(
        self,
        url: str,
        listing_id: int,
        changes: list[dict[str, object]],
    ) -> None:
        if not changes:
            return
        # Save to listing_changes table
        from book_scraper.db.models import ListingChange

        assert self.session is not None
        for change in changes:
            self.session.add(
                ListingChange(
                    listing_id=listing_id,
                    scrape_run_id=self._run_id,
                    field=str(change["field"]),
                    old_value=str(change["old"]) if change["old"] is not None else None,
                    new_value=str(change["new"]) if change["new"] is not None else None,
                )
            )

        # Also report as validation issues
        vp: ValidationPipeline | None = getattr(
            self.crawler, "validation_pipeline", None
        )
        if vp is None:
            return
        for change in changes:
            field = change["field"]
            old = change["old"]
            new = change["new"]
            if old is not None and new is None:
                vp._warn(
                    "field_cleared",
                    str(field),
                    url,
                    f"was: {old}",
                )
            elif old != new and old is not None:
                vp._warn(
                    "field_changed",
                    str(field),
                    url,
                    f"{old} -> {new}",
                )

    _WATCHED_EMPTY_FIELDS = (
        "author",
        "isbn",
        "publisher",
        "year",
        "format",
        "description",
        "image_url",
    )

    def _report_empty_fields(
        self,
        url: str,
        adapter: ItemAdapter,
        prior_values: dict[str, Any],
    ) -> None:
        """Emit a validation issue when a full scrape returns None for a
        field that was previously populated.

        Covers the case where a product page parser silently regresses
        (e.g. selector breaks) — the upsert leaves the old value in
        place, so users never notice the scrape provided nothing.
        """
        if not prior_values:
            return
        vp: ValidationPipeline | None = getattr(
            self.crawler, "validation_pipeline", None
        )
        if vp is None:
            return
        for field in self._WATCHED_EMPTY_FIELDS:
            old = prior_values.get(field)
            new = adapter.get(field)
            if old is not None and new is None:
                vp._warn(
                    "field_missing",
                    field,
                    url,
                    f"was: {old}",
                )

    def _get_shop_id(self, shop_name: str) -> int:
        if shop_name not in self.shop_cache:
            assert self.session is not None
            shop = upsert_shop(
                self.session,
                name=shop_name,
                base_url=f"https://{shop_name}.lt",
            )
            self.shop_cache[shop_name] = shop.id
        return self.shop_cache[shop_name]

    def process_item(self, item: Any) -> Any:
        if self.session is None:  # pragma: no cover
            return item

        adapter = ItemAdapter(item)
        shop_name: str = adapter.get("shop_name") or ""

        if isinstance(item, ListingItem):
            shop_id = self._get_shop_id(shop_name)

            year = adapter.get("year")
            if year is not None:
                try:
                    year = int(year)
                except (ValueError, TypeError):
                    year = None

            price = (
                Decimal(adapter["price"]) if adapter.get("price") is not None else None
            )
            price_original = (
                Decimal(adapter["price_original"])
                if adapter.get("price_original")
                else None
            )

            # Capture existing values so we can detect fields the full
            # scrape failed to re-extract (empty-parse regression).
            from book_scraper.db.models import Listing as _Listing

            prior = (
                self.session.query(_Listing)
                .filter_by(shop_id=shop_id, url=adapter["url"])
                .first()
            )
            prior_values = (
                {
                    f: getattr(prior, f)
                    for f in (
                        "author",
                        "isbn",
                        "publisher",
                        "year",
                        "format",
                        "description",
                        "image_url",
                    )
                }
                if prior
                else {}
            )

            listing, created, old_price, changes = upsert_listing(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                title=adapter["title"],
                author=adapter.get("author"),
                sku=adapter.get("sku"),
                isbn=adapter.get("isbn"),
                publisher=adapter.get("publisher"),
                year=year,
                format=adapter.get("format"),
                description=adapter.get("description"),
                image_url=adapter.get("image_url"),
                categories=adapter.get("categories"),
                properties=adapter.get("properties"),
                price=price,
                price_original=price_original,
                in_stock=adapter.get("in_stock", True),
                run_id=self._run_id,
            )
            if created:
                self._stats_added += 1
            else:
                self._stats_updated += 1
                self._check_price_spike(
                    adapter["url"],
                    old_price,
                    price,
                )
                self._report_field_changes(
                    adapter["url"],
                    listing.id,
                    changes,
                )
                self._report_empty_fields(
                    adapter["url"],
                    adapter,
                    prior_values,
                )
            if price is not None:
                insert_price(
                    self.session,
                    listing_id=listing.id,
                    price=price,
                    price_original=price_original,
                    in_stock=adapter.get("in_stock", True),
                    run_id=self._run_id,
                )

        elif isinstance(item, PriceItem):
            shop_id = self._get_shop_id(shop_name)
            price = Decimal(adapter["price"])
            price_original = (
                Decimal(adapter["price_original"])
                if adapter.get("price_original")
                else None
            )
            listing, created, old_price, _ = upsert_listing(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                title=adapter.get("title") or adapter["url"],
                author=adapter.get("author"),
                price=price,
                price_original=price_original,
                in_stock=adapter.get("in_stock", True),
                run_id=self._run_id,
            )
            if created:
                self._stats_added += 1
            else:
                self._stats_updated += 1
                self._check_price_spike(adapter["url"], old_price, price)
            insert_price(
                self.session,
                listing_id=listing.id,
                price=price,
                price_original=price_original,
                in_stock=adapter.get("in_stock", True),
                run_id=self._run_id,
            )

        elif isinstance(item, DiscoveredUrlItem):
            shop_id = self._get_shop_id(shop_name)
            upsert_discovered_url(
                self.session,
                shop_id=shop_id,
                url=item["url"],
                source=item["source"],
            )

        # Commit every 100 items
        self._item_count += 1
        if self._item_count % 100 == 0:
            self.session.commit()
            # Update scrape_run progress if spider tracks it
            spider = self.spider
            if spider and hasattr(spider, "_run_id") and spider._run_id:
                update_scrape_run_progress(
                    self.session,
                    spider._run_id,
                    spider._urls_processed,
                )
                self._flush_stats(spider._run_id)
                self._flush_validation_issues(spider._run_id)

        return item
