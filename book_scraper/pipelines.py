import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from itemadapter import ItemAdapter
from markdownify import markdownify as _html_to_markdown
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from sqlalchemy.orm import Session, sessionmaker

from book_scraper.db.repo import (
    bulk_insert_validation_issues,
    increment_scrape_run_stats,
    insert_price,
    link_discovered_url_to_shop_book,
    touch_shop_book_field_updates,
    update_scrape_run_progress,
    upsert_discovered_url,
    upsert_shop,
    upsert_shop_book,
)
from book_scraper.db.session import get_session_factory
from book_scraper.isbn import is_valid_isbn
from book_scraper.items import DiscoveredUrlItem, PriceItem, ShopBookItem

logger = logging.getLogger(__name__)

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
    return is_valid_isbn(raw)


class ValidationPipeline:
    def __init__(self, stats: Any = None):
        self.stats = stats
        self.issues: list[dict[str, str | int | None]] = []
        self.crawler: Crawler | None = None
        # Compiled regexes for attribute value checks, keyed by key name.
        self._attr_patterns: dict[str, re.Pattern[str]] = {}

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "ValidationPipeline":
        pipeline = cls(stats=crawler.stats)
        pipeline.crawler = crawler
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
        # description intentionally stores sanitised rich HTML now, so
        # skip it here — only flag HTML bleeding into title/author.
        for field in ("title", "author"):
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
        # (Multi-author detection removed — upsert_shop_book now splits
        # the raw author string into shop_authors + shop_book_authors, so
        # flagging a raw multi-author string is redundant noise.)

    def _check_attributes(self, adapter: ItemAdapter, url: str) -> None:
        """Validate `properties` against the per-shop schema, if any.

        Unknown keys fire `attribute_unknown_key`; values that don't
        satisfy the rule's enum/pattern fire `attribute_invalid_value`.
        Valid attributes pass through unchanged for the storage layer.
        """
        spider = getattr(self.crawler, "spider", None) if self.crawler else None
        shop_conf = getattr(spider, "conf", None)
        attrs_conf = getattr(shop_conf, "attributes", None)
        if attrs_conf is None:
            return
        props = adapter.get("properties") or {}
        if not isinstance(props, dict):
            return
        allowed = set(attrs_conf.allowed_keys)
        for key, value in props.items():
            if key not in allowed:
                self._warn(
                    "attribute_unknown_key",
                    "properties",
                    url,
                    f"{key}={value}",
                )
                continue
            rule = attrs_conf.rules.get(key)
            if rule is None or value is None:
                continue
            str_value = str(value)
            if rule.enum is not None and str_value not in rule.enum:
                self._warn(
                    "attribute_invalid_value",
                    key,
                    url,
                    f"not in enum: {str_value}",
                )
            if rule.pattern is not None:
                regex = self._attr_patterns.get(key)
                if regex is None:
                    regex = re.compile(rule.pattern)
                    self._attr_patterns[key] = regex
                if not regex.fullmatch(str_value):
                    self._warn(
                        "attribute_invalid_value",
                        key,
                        url,
                        f"pattern mismatch: {str_value}",
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

        if isinstance(item, (ShopBookItem, PriceItem)):
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

        if isinstance(item, ShopBookItem):
            # Convert any inbound HTML description to Markdown at the
            # boundary. Shops vary in their source markup; keeping the
            # stored form as Markdown is portable, diff-friendly, and
            # safe to re-render as HTML via the dashboard Jinja filter.
            desc = adapter.get("description")
            if isinstance(desc, str) and "<" in desc and ">" in desc:
                converted = _html_to_markdown(desc, heading_style="ATX").strip()
                adapter["description"] = converted or None

            if not adapter.get("title"):
                self._warn("missing_title", "title", url)
                raise DropItem("Missing title")

            year_before = adapter.get("year")
            _validate_year(adapter)
            year_after = adapter.get("year")
            if year_before is not None and year_after is None:
                self._warn("invalid_year", "year", url, str(year_before))
            elif year_before is not None and year_before != year_after:
                self._warn("year_pages_swap", "year", url, str(year_before))

            isbn = adapter.get("isbn")
            if isbn is not None and not _is_valid_isbn(isbn):
                self._warn("invalid_isbn", "isbn", url, str(isbn))
                adapter["isbn"] = None

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

            # Per-shop attribute schema (opt-in via TOML)
            self._check_attributes(adapter, url)

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
        # The shop is the same for every item in a run, so the first
        # cached shop id is always correct.
        shop_id: int | None = None
        if self.shop_cache:
            shop_id = next(iter(self.shop_cache.values()))
        bulk_insert_validation_issues(self.session, issues, shop_id=shop_id)

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

    _TRACKED_FIELDS = frozenset(
        {
            "price",
            "description",
            "image_url",
            "author",
            "isbn",
            "publisher",
            "year",
            "format",
        }
    )

    def _report_field_changes(
        self,
        url: str,
        shop_book_id: int,
        changes: list[dict[str, object]],
    ) -> None:
        if not changes:
            return
        # Save to shop_book_changes table
        from book_scraper.db.models import ShopBookChange

        assert self.session is not None
        for change in changes:
            self.session.add(
                ShopBookChange(
                    shop_book_id=shop_book_id,
                    scrape_run_id=self._run_id,
                    field=str(change["field"]),
                    old_value=str(change["old"]) if change["old"] is not None else None,
                    new_value=str(change["new"]) if change["new"] is not None else None,
                )
            )

        # Advance per-field "last updated" timestamps for any tracked
        # field that actually changed.
        touched = [
            str(c["field"]) for c in changes if str(c["field"]) in self._TRACKED_FIELDS
        ]
        if touched:
            touch_shop_book_field_updates(self.session, shop_book_id, touched)

        vp: ValidationPipeline | None = getattr(
            self.crawler, "validation_pipeline", None
        )
        if vp is None:
            return
        for change in changes:
            if change["old"] is not None and change["new"] is None:
                vp._warn(
                    "field_cleared",
                    str(change["field"]),
                    url,
                    f"was: {change['old']}",
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

        if isinstance(item, ShopBookItem):
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

            raw_rating = adapter.get("rating")
            rating = Decimal(str(raw_rating)) if raw_rating is not None else None
            review_count_raw = adapter.get("review_count")
            review_count = (
                int(review_count_raw) if review_count_raw is not None else None
            )

            shop_book, created, old_price, changes = upsert_shop_book(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                title=adapter["title"],
                type=adapter.get("type"),
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
                planned_availability_date=adapter.get("planned_availability_date"),
                rating=rating,
                review_count=review_count,
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
                    shop_book.id,
                    changes,
                )
            if price is not None:
                insert_price(
                    self.session,
                    shop_book_id=shop_book.id,
                    price=price,
                    price_original=price_original,
                    in_stock=adapter.get("in_stock", True),
                    run_id=self._run_id,
                )
            link_discovered_url_to_shop_book(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                shop_book_id=shop_book.id,
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
            shop_book, created, old_price, changes = upsert_shop_book(
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
                self._report_field_changes(
                    adapter["url"],
                    shop_book.id,
                    changes,
                )
            insert_price(
                self.session,
                shop_book_id=shop_book.id,
                price=price,
                price_original=price_original,
                in_stock=adapter.get("in_stock", True),
                run_id=self._run_id,
            )
            link_discovered_url_to_shop_book(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                shop_book_id=shop_book.id,
                run_id=self._run_id,
            )

        elif isinstance(item, DiscoveredUrlItem):
            shop_id = self._get_shop_id(shop_name)
            record = upsert_discovered_url(
                self.session,
                shop_id=shop_id,
                url=item["url"],
                source=item["source"],
                run_id=self._run_id,
            )
            spider = self.spider
            # Second-pass hook: fires only when a DiscoveredUrlItem reaches
            # the pipeline. Scan spider does not yet yield these — this path
            # becomes active in Phase 2.
            if (
                spider is not None
                and getattr(spider, "name", "") == "scan"
                and getattr(spider, "_rescrape", False)
            ):
                from book_scraper.services.scan import ScanService

                scan_run_id = getattr(spider, "_run_id", None)
                if scan_run_id is not None:
                    ScanService(self.session).enqueue_new_url(
                        run_id=scan_run_id,
                        shop_id=shop_id,
                        discovered_url_id=record.id,
                        url=record.url,
                        url_type=record.url_type or "product",
                    )
                    # Commit so spider_idle's fresh session can see the new
                    # queue row (fresh sessions only see committed data).
                    self.session.commit()

        # Commit every 10 items so the dashboard's `urls_processed`
        # counter advances visibly during slow runs. Used to be every
        # 100, which on pegasas's concurrency=2 + slow-cold-cache deep
        # pages meant the counter sat at 0 for minutes — operators
        # couldn't tell if the run was making progress.
        self._item_count += 1
        if self._item_count % 10 == 0:
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
                # Commit again so the scrape_runs row lock is released
                # before the next item. The spider's own progress
                # session (used by _flush_progress inside parse_product)
                # also writes to scrape_runs; without this commit the
                # pipeline sits `idle in transaction` between item-100
                # boundaries holding the row lock, and the spider
                # deadlocks the moment it tries to flush its own
                # heartbeat.
                self.session.commit()

        return item
