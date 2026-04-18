import re
from collections.abc import AsyncGenerator, Generator
from typing import Any

import scrapy
from scrapy import signals

from book_scraper.config import load_shop_config
from book_scraper.db.repo import (
    get_pending_scrape_url_items,
    insert_scrape_url_item,
    mark_scrape_url_item_done,
    reset_processing_scrape_url_items,
)
from book_scraper.db.session import get_session_factory
from book_scraper.items import DiscoveredUrlItem, ShopBookItem
from book_scraper.services.discover import DiscoverService
from book_scraper.spiders.registry import load_parsers


class DiscoverSpider(scrapy.Spider):
    name = "discover"

    def __init__(
        self,
        shop: str | None = None,
        strategy: str = "sitemap",
        max_pages: str | int = "",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        if not shop:
            raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
        self.shop_name = shop
        self.strategy = strategy
        # 0 / empty → no cap. Applies to `categories` (page count) and
        # `full_crawl` (per-host link follow count). Sitemap is a single
        # request so the cap is a no-op there.
        self._max_pages: int = int(max_pages) if str(max_pages).strip() else 0
        self.conf = load_shop_config(shop)
        self.parsers = load_parsers(shop)
        self.allowed_domains = [
            self.conf.shop.base_url.replace("https://", "").replace("http://", "")
        ]

        # Load URL filter pattern
        discover_conf = self.conf.discover
        pattern = discover_conf.url_include_pattern
        self.url_pattern: re.Pattern[str] | None = (
            re.compile(pattern) if pattern else None
        )

        # Load strategy-specific config
        strategy_conf = getattr(discover_conf, strategy, None)
        if strategy_conf is None:
            raise ValueError(f"Strategy '{strategy}' not configured for shop '{shop}'")
        self.strategy_conf: Any = strategy_conf

        self._run_id: int | None = None
        self._shop_id: int | None = None
        self._urls_processed: int = 0
        self._urls_filtered: int = 0
        # URLs discovered this run, used for change detection on the
        # sitemap strategy (sitemap is comprehensive per shop).
        self._sitemap_urls: set[str] = set()
        # Set when handle_start_error or parse_categories already reported a
        # more specific zero-yield cause — avoids duplicate noise from the
        # generic closed() check.
        self._zero_yield_suppressed: bool = False

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):  # type: ignore[no-untyped-def]
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_idle, signal=signals.spider_idle)
        return spider

    def _url_passes_filter(self, url: str) -> bool:
        if self.url_pattern is None:
            return True
        return bool(self.url_pattern.match(url))

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )

        if not database_url:
            # Test / no-DB path: preserve the legacy behavior of yielding the
            # strategy's seed URL directly, so unit tests that call start()
            # without a database keep working.
            yield self._legacy_seed_request()
            return

        session_factory = get_session_factory(database_url)
        session = session_factory()
        try:
            service = DiscoverService(session)
            plan = service.prepare_discover(
                self.shop_name,
                self.conf.shop.base_url,
                self.strategy,
                self.conf,
            )
            self._run_id = plan.run_id
            self._shop_id = plan.shop_id

            reset_processing_scrape_url_items(session, plan.run_id)
            url_items = get_pending_scrape_url_items(session, plan.run_id)
            session.commit()
        finally:
            session.close()

        for item in url_items:
            yield scrapy.Request(
                item["url"],
                callback=self.dispatch,
                errback=self.handle_start_error,
                meta={
                    "scrape_url_item_id": item["id"],
                    "url_type": item["url_type"],
                    "page": 1 if item["url_type"] == "category_page" else None,
                },
            )

    def _legacy_seed_request(self) -> scrapy.Request:
        """Build the strategy's seed Request without touching the DB.

        Used only by unit tests that call ``start()`` on a spider constructed
        outside the Scrapy crawler pipeline.
        """
        if self.strategy == "sitemap":
            return scrapy.Request(
                self.strategy_conf.url,
                callback=self.parse_sitemap,
                errback=self.handle_start_error,
            )
        if self.strategy == "categories":
            url = self.strategy_conf.url.format(page=1)
            return scrapy.Request(
                url,
                callback=self.parse_categories,
                errback=self.handle_start_error,
                meta={"page": 1},
            )
        # full_crawl
        return scrapy.Request(
            self.strategy_conf.start_url,
            callback=self.parse_full_crawl,
            errback=self.handle_start_error,
        )

    def dispatch(
        self, response: scrapy.http.Response
    ) -> Generator[Any, None, None]:
        """Route a downloaded response to the correct parser based on url_type."""
        url_type = response.meta.get("url_type") or "crawl"
        try:
            if url_type == "sitemap":
                yield from self.parse_sitemap(response)
            elif url_type == "category_page":
                yield from self.parse_categories(response)
            else:
                # "crawl" or "product" — both handled by full_crawl parser,
                # which already branches on whether the URL is a product page.
                yield from self.parse_full_crawl(response)
        finally:
            item_id = response.meta.get("scrape_url_item_id")
            if item_id is not None and self._run_id is not None:
                database_url = self.settings.get("DATABASE_URL")
                factory = get_session_factory(database_url)
                session = factory()
                try:
                    mark_scrape_url_item_done(session, item_id)
                    session.commit()
                finally:
                    session.close()

    def spider_idle(self, spider) -> None:  # type: ignore[no-untyped-def]
        """Pick up items enqueued mid-run (e.g. via parse_categories dual-write).

        Mirrors the scan spider pattern: when the engine runs dry, re-check
        the queue for newly-inserted pending items and schedule them.
        """
        if self._run_id is None:
            return
        database_url = self.settings.get("DATABASE_URL")
        factory = get_session_factory(database_url)
        session = factory()
        try:
            reset_processing_scrape_url_items(session, self._run_id)
            new_items = get_pending_scrape_url_items(session, self._run_id)
            session.commit()
        finally:
            session.close()

        if not new_items:
            return

        from scrapy.exceptions import DontCloseSpider

        engine = self.crawler.engine
        assert engine is not None
        for item in new_items:
            req = scrapy.Request(
                item["url"],
                callback=self.dispatch,
                errback=self.handle_start_error,
                meta={
                    "scrape_url_item_id": item["id"],
                    "url_type": item["url_type"],
                },
            )
            engine.crawl(req)
        raise DontCloseSpider

    def handle_start_error(self, failure: Any) -> None:
        """Surface discovery fetch failures as validation issues.

        Without this a 4xx/5xx/timeout on the first category or sitemap
        request leaves the run silently "completed with 0 URLs", which
        hides broken URL patterns for hours at a time.
        """
        request = failure.request
        status_obj = getattr(failure.value, "response", None)
        http_status = status_obj.status if status_obj else None
        detail = f"{type(failure.value).__name__}"
        if http_status is not None:
            detail = f"HTTP {http_status}"
        self._report_validation(
            "discover_fetch_failed",
            "url",
            str(request.url),
            detail,
        )
        self._zero_yield_suppressed = True
        self.logger.error(
            "Discover %s failed to fetch %s: %s",
            self.strategy,
            request.url,
            detail,
        )

    def _report_validation(
        self,
        issue: str,
        field: str,
        url: str,
        raw_value: str = "",
    ) -> None:
        """Report a validation issue to the ValidationPipeline."""
        crawler = getattr(self, "crawler", None)
        vp = getattr(crawler, "validation_pipeline", None) if crawler else None
        if vp is not None:
            vp._warn(issue, field, url, raw_value)
        else:
            self.logger.warning(
                "Validation [%s] field=%s url=%s %s",
                issue,
                field,
                url,
                raw_value,
            )

    def _enqueue_url(self, url: str, url_type: str) -> int | None:
        """Dual-write helper: insert a queue item and return its id.

        No-op (returns None) when ``_run_id`` is None — unit tests construct
        the spider without a run and call the callbacks directly.
        """
        if self._run_id is None or self._shop_id is None:
            return None
        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )
        if not database_url:
            return None
        factory = get_session_factory(database_url)
        session = factory()
        try:
            item = insert_scrape_url_item(
                session,
                run_id=self._run_id,
                shop_id=self._shop_id,
                discovered_url_id=None,
                url=url,
                url_type=url_type,
            )
            session.commit()
            return item.id
        finally:
            session.close()

    def parse_sitemap(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem, None, None]:
        urls: list[str] = self.parsers.parse_sitemap_urls(response.text)
        self.logger.info("Found %d URLs in sitemap", len(urls))

        # Check for duplicates
        seen: set[str] = set()
        duplicates = 0
        for url in urls:
            if url in seen:
                duplicates += 1
            else:
                seen.add(url)
        if duplicates:
            self._report_validation(
                "duplicate_sitemap_url",
                "url",
                response.url,
                f"{duplicates} duplicates in {len(urls)} URLs",
            )

        for url in seen:
            if self._url_passes_filter(url):
                self._urls_processed += 1
                self._sitemap_urls.add(url)
                yield DiscoveredUrlItem(
                    url=url, shop_name=self.shop_name, source="sitemap"
                )
            else:
                self._urls_filtered += 1

    def parse_categories(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem | ShopBookItem | scrapy.Request, None, None]:
        products: list[dict[str, str | None]] = self.parsers.parse_category_page(
            response.text
        )
        if not products:
            # If we hit an empty response on page 1, the upstream URL
            # pattern is probably broken — warn so the next run isn't
            # another silent "completed with 0 URLs" outcome.
            page = response.meta.get("page", 0)
            if page == 1:
                self._report_validation(
                    "discover_empty_first_page",
                    "url",
                    response.url,
                    f"page 1 returned 0 products (len={len(response.text)})",
                )
                self._zero_yield_suppressed = True
            return  # No more pages

        base_url: str = self.conf.shop.base_url
        for product in products:
            url = product["url"]
            if url and not url.startswith("http"):
                url = base_url + url

            if not url:
                continue
            if self._url_passes_filter(url):
                self._urls_processed += 1
                yield DiscoveredUrlItem(
                    url=url, shop_name=self.shop_name, source="category"
                )

                # Yield product data when we have at least a title and price
                if product.get("title") and product.get("price"):
                    yield ShopBookItem(
                        url=url,
                        shop_name=self.shop_name,
                        title=product["title"],
                        author=product.get("author"),
                        price=product.get("price"),
                        price_original=product.get("price_original"),
                        in_stock=True,
                        type=None,
                        sku=None,
                        isbn=None,
                        publisher=None,
                        year=None,
                        format=None,
                        description=None,
                        image_url=product.get("image_url"),
                        categories=product.get("categories", []),
                        properties=None,
                    )
            else:
                self._urls_filtered += 1

        # Paginate. Respect max_pages when the user set a cap so dev
        # runs don't always exhaust the whole catalog.
        page = (response.meta.get("page") or 1) + 1
        if self._max_pages and page > self._max_pages:
            self.logger.info("max_pages cap: stopping at page %d", self._max_pages)
            return
        next_url = self.strategy_conf.url.format(page=page)

        # Dual-write: persist the next page to scrape_url_items so the run
        # can resume after a crash, THEN yield the Request so Scrapy fetches
        # it immediately. When we have no run (unit tests), skip the insert
        # and just yield — dispatch routes back to parse_categories.
        new_item_id = self._enqueue_url(next_url, "category_page")
        cb = self.dispatch if new_item_id is not None else self.parse_categories
        yield scrapy.Request(
            next_url,
            callback=cb,
            errback=self.handle_start_error,
            meta={
                "page": page,
                "scrape_url_item_id": new_item_id,
                "url_type": "category_page",
            },
        )

    def parse_full_crawl(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem | ShopBookItem | scrapy.Request, None, None]:
        """Follow all internal links, yield product URLs and parse product data."""
        base_url: str = self.conf.shop.base_url
        seen: set[str] = getattr(self, "_seen_urls", set())
        self._seen_urls = seen
        if self._max_pages and len(seen) >= self._max_pages:
            return

        # If the current page matches the product URL pattern, extract product data
        current_url = response.url.split("?")[0]
        if self._url_passes_filter(current_url):
            data = self.parsers.parse_product_page(response.text)
            if data.get("title"):
                props: dict[str, object] = {}
                for key in (
                    "pages", "cover_type", "duration", "narrator", "translator"
                ):
                    if data.get(key) is not None:
                        props[key] = data[key]
                yield ShopBookItem(
                    url=current_url,
                    shop_name=self.shop_name,
                    type=data.get("type"),
                    title=data["title"],
                    author=data.get("author"),
                    sku=data.get("sku"),
                    isbn=data.get("isbn"),
                    publisher=data.get("publisher"),
                    year=data.get("year"),
                    format=data.get("format"),
                    description=data.get("description"),
                    image_url=data.get("image_url"),
                    categories=data.get("categories", []),
                    properties=props or None,
                    price=data.get("price"),
                    price_original=data.get("price_original"),
                    in_stock=data.get("in_stock"),
                )

        for link in response.css("a::attr(href)").getall():
            if not link.startswith("http"):
                link = response.urljoin(link)

            if not link.startswith(base_url):
                continue
            if link in seen:
                continue
            seen.add(link)

            is_product = self._url_passes_filter(link)
            if is_product:
                self._urls_processed += 1
                yield DiscoveredUrlItem(
                    url=link, shop_name=self.shop_name, source="full_crawl"
                )

            # Dual-write: categorize by URL shape so dispatch can route on
            # resume. Product pages re-enter parse_full_crawl too (which
            # extracts product data when the URL matches the filter).
            url_type = "product" if is_product else "crawl"
            new_item_id = self._enqueue_url(link, url_type)
            yield scrapy.Request(
                link,
                callback=self.dispatch
                if new_item_id is not None
                else self.parse_full_crawl,
                dont_filter=False,
                meta={
                    "scrape_url_item_id": new_item_id,
                    "url_type": url_type,
                },
            )

    def closed(self, reason: str) -> None:
        if self._urls_filtered:
            self._report_validation(
                "url_pattern_filtered",
                "url",
                "",
                f"{self._urls_filtered} URLs excluded by pattern",
            )
            self.logger.info(
                "URL filter: %d passed, %d filtered",
                self._urls_processed,
                self._urls_filtered,
            )

        if self._run_id is None:
            return

        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )
        if not database_url:
            return
        factory = get_session_factory(database_url)
        session = factory()
        try:
            # Change detection and zero-yield checks still live here because
            # they need spider-local state (_sitemap_urls, _urls_processed,
            # _zero_yield_suppressed). finish_discover handles the generic
            # parts: status, urls_processed, cron last_run_at, cleanup.
            status = "completed" if reason == "finished" else "failed"
            if (
                status == "completed"
                and self.strategy == "sitemap"
                and self._sitemap_urls
                and self._shop_id is not None
            ):
                from book_scraper.db.repo import mark_shop_books_inactive

                deactivated = mark_shop_books_inactive(
                    session,
                    shop_id=self._shop_id,
                    active_urls=self._sitemap_urls,
                )
                if deactivated:
                    self.logger.info(
                        "Change detection: marked %d shop_book(s) inactive",
                        deactivated,
                    )

            if (
                status == "completed"
                and self._urls_processed == 0
                and not self._zero_yield_suppressed
                and self._shop_id is not None
            ):
                from book_scraper.db.models import DiscoveredUrl

                prior_count = (
                    session.query(DiscoveredUrl)
                    .filter(DiscoveredUrl.shop_id == self._shop_id)
                    .count()
                )
                if prior_count > 0:
                    self._report_validation(
                        "discover_zero_yield",
                        "run",
                        self.conf.shop.base_url,
                        f"phase=discover_{self.strategy}, "
                        f"shop had {prior_count} URLs pre-run",
                    )

            session.commit()

            DiscoverService(session).finish_discover(
                self._run_id,
                self._urls_processed,
                reason,
            )
        finally:
            session.close()
