import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from itemadapter import ItemAdapter
from markdownify import markdownify as _html_to_markdown
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from book_scraper.db.models import ScrapeUrlItem as ScrapeUrlItemModel
from book_scraper.db.repo import (
    increment_scrape_run_stats,
    insert_price,
    link_discovered_url_to_shop_book,
    record_scrape_failure,
    touch_shop_book_field_updates,
    update_scrape_run_progress,
    upsert_discovered_url,
    upsert_shop,
    upsert_shop_book,
    upsert_validation_issues,
)
from book_scraper.db.session import get_session_factory
from book_scraper.isbn import is_valid_isbn
from book_scraper.items import BookItem, DiscoveredUrlItem, PriceItem, ShopBookItem
from book_scraper.url_utils import normalize_url

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

    # Possible swap: year has page count, pages has year.
    # Pages may live in properties dict (most shops) or at top level
    # (patogupirkti uses item["pages"] directly, not item["properties"]["pages"]).
    props = adapter.get("properties")
    pages_val: object = None
    if isinstance(props, dict) and "pages" in props:
        pages_val = props["pages"]
    elif adapter.get("pages") is not None:
        pages_val = adapter.get("pages")

    if pages_val is not None:
        try:
            pages = int(pages_val)
        except (ValueError, TypeError):
            pages = None
        if pages is not None and _MIN_YEAR <= pages <= _MAX_YEAR:
            adapter["year"] = pages
            if isinstance(props, dict) and "pages" in props:
                props["pages"] = year
            else:
                adapter["pages"] = year
            return

    # Year out of range and no swap possible — clear it
    adapter["year"] = None


# markdownify drops everything after a `<br/>` that follows a `<br>` in the
# same paragraph — an html.parser artifact, not an intention:
#   <p>One<br>Two<br/>Three</p>  ->  "One  \nTwo"
#   <p>One<br>Two<br>Three</p>   ->  "One  \nTwo  \nThree"
# Normalising the self-closing form away first costs nothing and keeps the text.
_SELF_CLOSING_BR = re.compile(r"<br\s*/\s*>", re.IGNORECASE)


def html_to_markdown(html: str) -> str | None:
    """Convert an inbound HTML description to the Markdown we store.

    Returns None for an empty conversion, so the column ends up NULL rather
    than holding an empty string. php/tools/dump_markdown_golden.py calls this
    rather than markdownify directly, so the golden records what is stored.
    """
    converted = _html_to_markdown(
        _SELF_CLOSING_BR.sub("<br>", html), heading_style="ATX"
    ).strip()
    return converted or None


def _as_int(value: object) -> int | None:
    """int(value) or None — for comparing a parsed field against its raw form."""
    if isinstance(value, int | float | str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


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
            # Out-of-stock items on some shops return no price — suppress the
            # warning for items explicitly marked as not in stock so we only
            # flag genuinely missing prices for available books.
            if adapter.get("in_stock") is not False:
                self._warn("missing_price", "price", url)
            return
        price_dec = Decimal(str(price))
        if price_dec == 0 and adapter.get("in_stock") is not False:
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
                adapter["description"] = html_to_markdown(desc)

            if not adapter.get("title"):
                self._warn("missing_title", "title", url)
                raise DropItem("Missing title")

            year_before = adapter.get("year")
            _validate_year(adapter)
            year_after = adapter.get("year")
            if year_before is not None and year_after is None:
                self._warn("invalid_year", "year", url, str(year_before))
            # Compare numerically: _validate_year turns "2024" into 2024, and
            # comparing by identity read that as a year/pages swap.
            elif year_before is not None and _as_int(year_before) != year_after:
                self._warn("year_pages_swap", "year", url, str(year_before))

            isbn = adapter.get("isbn")
            if isbn is not None:
                if _is_valid_isbn(isbn):
                    from book_scraper.isbn import normalize_isbn
                    adapter["isbn"] = normalize_isbn(isbn)
                else:
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
        # The shop is the same for every item in a run, so the first
        # cached shop id is always correct.
        shop_id: int | None = None
        if self.shop_cache:
            shop_id = next(iter(self.shop_cache.values()))
        if issues and shop_id is not None and run_id is not None:
            upsert_validation_issues(
                self.session, issues, shop_id=shop_id, run_id=run_id
            )

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

        try:
            return self._process_item_inner(item)
        except SQLAlchemyError as exc:
            # One bad item used to poison the rest of the run: a single
            # statement_timeout / NotNullViolation / IntegrityError left
            # the shared session in PendingRollbackError state, and every
            # subsequent item failed with the same cited cause until
            # close_spider. Rolling back here restores the session to a
            # clean state so the *next* item starts fresh; only the
            # offending item is dropped. (Verified during humanitas
            # smoke: pre-fix the first OOS-row NotNullViolation killed
            # the entire run; post-fix individual failures are isolated.)
            self.session.rollback()
            # The same rollback also reverts any in-flight `shops`
            # INSERT performed by `_get_shop_id` while caching, so
            # the now-stale id would FK-violate on the next item.
            # Cheapest correct fix: drop the cache and re-upsert on
            # the next item — for an existing shop that's a single
            # SELECT, free at scale.
            self.shop_cache.clear()
            url = ItemAdapter(item).get("url", "<no url>")
            logger.error(
                "PostgresPipeline: dropping %s item (%s) — DB error: %s",
                type(item).__name__,
                url,
                exc,
            )
            # Surface the failure in the dashboard: without this, a DB
            # error produces items_updated=0 with no explanation — the
            # run's Runs tab on the shop book page stays blank and the
            # operator has to hunt through Scrapy logs.
            # Session is clean after rollback so this write is safe.
            run_id = self._run_id
            if run_id is not None and url != "<no url>":
                try:
                    sui = (
                        self.session.query(ScrapeUrlItemModel)
                        .filter_by(run_id=run_id, url=normalize_url(url))
                        .one_or_none()
                    )
                    if sui is not None:
                        record_scrape_failure(
                            self.session,
                            scrape_url_item=sui,
                            error_reason="pipeline_db_error",
                            http_status=None,
                            error_detail=f"{type(exc).__name__}: {exc}",
                        )
                        self.session.commit()
                except Exception as inner_exc:
                    logger.error(
                        "PostgresPipeline: failed to record scrape_failure "
                        "for %s: %s",
                        url,
                        inner_exc,
                    )
                    self.session.rollback()
            raise DropItem(f"DB error for {url}: {exc.__class__.__name__}") from exc

    def _process_item_inner(self, item: Any) -> Any:  # pragma: no cover
        # Caller (`process_item`) guarantees self.session is not None;
        # the assert is here so mypy can narrow the type across the
        # function boundary without a sea of `# type: ignore`s.
        assert self.session is not None
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
            # Mark the URL as `product_partial` when the persisted
            # shop_book has no ISBN — typically because the discovery
            # source didn't return one (lupasearch, some category-page
            # parsers). Reading from `shop_book.isbn` (not the adapter)
            # respects the case where a previous run already captured
            # ISBN and this lighter item just refreshes price/title.
            #
            # The delta scan picks `product_partial` rows up; the scan
            # spider promotes them to `product` on the first successful
            # fetch regardless of whether ISBN ends up filled — so books
            # whose product page genuinely has no ISBN do not loop
            # indefinitely.
            link_discovered_url_to_shop_book(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                shop_book_id=shop_book.id,
                run_id=self._run_id,
                is_partial=shop_book.isbn is None,
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
            # PriceItem carries no ISBN field — gauge partial-ness from
            # the persisted shop_book. Same rationale as the ShopBookItem
            # branch above.
            link_discovered_url_to_shop_book(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                shop_book_id=shop_book.id,
                run_id=self._run_id,
                is_partial=shop_book.isbn is None,
            )

        elif isinstance(item, BookItem):
            self._upsert_book(adapter)
            return item

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

        # Commit per item. Used to be every 10 (and originally every
        # 100) for throughput, but a single statement_timeout in a
        # batch was rolling back nine prior successful items along
        # with the offender. Empirically (200-item bench against the
        # test DB on 2026-05-07) per-item commits are actually *faster*
        # than every-10 by ~5 % — smaller transactions push less WAL
        # per fsync, so the batch boundaries weren't the win they used
        # to be. We get the resilience for free.
        self.session.commit()
        self._item_count += 1
        # Progress + stats every 10 items: small enough that operators
        # see the urls_processed counter move within seconds on a slow
        # crawl, large enough that we don't burn write budget on
        # scrape_runs UPDATEs every item.
        if self._item_count % 10 == 0:
            spider = self.spider
            if spider and hasattr(spider, "_run_id") and spider._run_id:
                update_scrape_run_progress(
                    self.session,
                    spider._run_id,
                    spider._urls_processed,
                )
                self._flush_stats(spider._run_id)
                self._flush_validation_issues(spider._run_id)
                # Release the scrape_runs row lock before the next item.
                # The spider's own progress session (_flush_progress
                # inside parse_product) also writes scrape_runs; without
                # this commit the pipeline sits `idle in transaction`
                # holding the row lock and the spider deadlocks on its
                # next heartbeat.
                self.session.commit()

        return item

    def _upsert_book(self, adapter: ItemAdapter) -> None:
        """Insert or update a Book row with its publisher, series, ISBNs, authors.

        Resolution order to find target books.id:
          1. By any incoming ISBN (normalized) — catches shop_inferred
             → ibiblioteka upgrade.
          2. By libis_code — for re-scrapes where ISBNs may have changed.
          3. Otherwise INSERT a new books row.
        """
        from sqlalchemy import select

        from book_scraper.db.models import (
            Book,
            BookIsbn,
            Publisher,
            Series,
        )
        from book_scraper.isbn import normalize_isbn, to_isbn10, to_isbn13

        if self.session_factory is None:
            return
        session = self.session_factory()
        try:
            incoming_isbns_raw = adapter.get("isbns") or []
            incoming_isbns_norm: list[str] = []
            for entry in incoming_isbns_raw:
                norm = normalize_isbn(entry.get("isbn") or "")
                if norm:
                    incoming_isbns_norm.append(norm)

            target: Book | None = None
            if incoming_isbns_norm:
                target = session.execute(
                    select(Book).join(BookIsbn)
                    .where(BookIsbn.isbn.in_(incoming_isbns_norm))
                    .limit(1)
                ).scalar_one_or_none()

            libis_code = adapter.get("libis_code")
            if target is None and libis_code:
                target = session.execute(
                    select(Book).where(Book.libis_code == libis_code)
                ).scalar_one_or_none()

            publisher_id: int | None = None
            pub_name = adapter.get("publisher")
            if pub_name:
                pub_name = pub_name.strip()
                pub = session.execute(
                    select(Publisher).where(Publisher.name == pub_name)
                ).scalar_one_or_none()
                if pub is None:
                    pub = Publisher(name=pub_name)
                    session.add(pub)
                    session.flush()
                publisher_id = pub.id

            series_id: int | None = None
            ser_name = adapter.get("series")
            if ser_name:
                ser_name = ser_name.strip()
                ser = session.execute(
                    select(Series).where(Series.title == ser_name)
                ).scalar_one_or_none()
                if ser is None:
                    ser = Series(title=ser_name)
                    session.add(ser)
                    session.flush()
                series_id = ser.id

            field_map = {
                "title": adapter.get("title"),
                "title_full": adapter.get("title_full"),
                "year": adapter.get("year"),
                "release_place": adapter.get("release_place"),
                "type": adapter.get("type"),
                "format": adapter.get("format"),
                "pages": adapter.get("pages"),
                "duration": adapter.get("duration"),
                "dimensions": adapter.get("dimensions"),
                "language": adapter.get("language"),
                "translated_from": adapter.get("translated_from"),
                "description": adapter.get("description"),
                "cover_url": adapter.get("cover_url"),
                "upcoming_release": adapter.get("upcoming_release", False),
                "udc_codes": adapter.get("udc_codes"),
                "subjects": adapter.get("subjects"),
                "audience": adapter.get("audience"),
                "libis_rating": adapter.get("libis_rating"),
                "libis_review_count": adapter.get("libis_review_count"),
                "source_url": adapter.get("source_url"),
                "series_id": series_id,
            }
            if target is None:
                target = Book(
                    data_source=adapter.get("data_source"),
                    libis_code=libis_code,
                    publisher_id=publisher_id,
                    **{k: v for k, v in field_map.items() if v is not None},
                )
                session.add(target)
                session.flush()
            else:
                if (target.data_source == "shop_inferred"
                        and adapter.get("data_source") == "ibiblioteka"):
                    target.data_source = "ibiblioteka"
                    target.libis_code = libis_code
                for k, v in field_map.items():
                    if v is not None:
                        setattr(target, k, v)
                if target.publisher_id is None and publisher_id is not None:
                    target.publisher_id = publisher_id
                if libis_code and target.libis_code is None:
                    target.libis_code = libis_code

            seen: set[str] = set()
            for entry in incoming_isbns_raw:
                raw = entry.get("isbn") or ""
                norm = normalize_isbn(raw)
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                self._upsert_book_isbn(
                    session, target.id, norm, entry.get("type") or "unknown"
                )
                opp = to_isbn10(norm) if len(norm) == 13 else to_isbn13(norm)
                if opp and opp != norm and opp not in seen:
                    seen.add(opp)
                    opp_type = "isbn10" if len(opp) == 10 else "isbn13"
                    self._upsert_book_isbn(session, target.id, opp, opp_type)

            for entry in adapter.get("authors") or []:
                self._upsert_book_author(session, target.id, entry)

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _upsert_book_isbn(
        self, session: "Session", book_id: int, isbn: str, isbn_type: str
    ) -> None:
        from sqlalchemy.dialects.postgresql import insert

        from book_scraper.db.models import BookIsbn

        stmt = insert(BookIsbn).values(book_id=book_id, isbn=isbn, isbn_type=isbn_type)
        stmt = stmt.on_conflict_do_update(
            index_elements=["isbn"],
            set_={"book_id": book_id, "isbn_type": isbn_type},
        )
        session.execute(stmt)

    def _upsert_book_author(
        self, session: "Session", book_id: int, entry: dict
    ) -> None:
        """Resolve or create the canonical Author row, then ensure book_authors row."""
        from sqlalchemy import select

        from book_scraper.db.models import Author, BookAuthor

        name = (entry.get("name") or "").strip()
        if not name:
            return
        libis_code = entry.get("libis_code")
        normalized = name.lower().replace(",", "").strip()

        author: Author | None = None
        if libis_code:
            author = session.execute(
                select(Author).where(Author.libis_code == libis_code)
            ).scalar_one_or_none()
        if author is None:
            author = session.execute(
                select(Author).where(Author.normalized_name == normalized)
            ).scalar_one_or_none()
        if author is None:
            author = Author(
                name=name, normalized_name=normalized, libis_code=libis_code,
            )
            session.add(author)
            session.flush()
        elif libis_code and not author.libis_code:
            author.libis_code = libis_code

        role = entry.get("role") or "author"
        position = int(entry.get("position") or 0)
        existing = session.execute(
            select(BookAuthor).where(
                BookAuthor.book_id == book_id,
                BookAuthor.author_id == author.id,
                BookAuthor.role == role,
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(BookAuthor(
                book_id=book_id, author_id=author.id, role=role, position=position,
            ))
        else:
            existing.position = position
