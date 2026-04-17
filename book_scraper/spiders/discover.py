import re
from collections.abc import AsyncGenerator, Generator
from typing import Any

import scrapy
from sqlalchemy.orm import Session

from book_scraper.config import load_shop_config
from book_scraper.db.models import DiscoveredUrl
from book_scraper.db.repo import (
    create_scrape_run,
    finish_scrape_run,
    mark_shop_books_inactive,
    mark_stale_runs_failed,
    update_scrape_run_progress,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory
from book_scraper.items import DiscoveredUrlItem, PriceItem
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
        self._run_session: Session | None = None
        # URLs discovered this run, used for change detection on the
        # sitemap strategy (sitemap is comprehensive per shop).
        self._sitemap_urls: set[str] = set()
        # Set when handle_start_error or parse_categories already reported a
        # more specific zero-yield cause — avoids duplicate noise from the
        # generic closed() check.
        self._zero_yield_suppressed: bool = False

    def _url_passes_filter(self, url: str) -> bool:
        if self.url_pattern is None:
            return True
        return bool(self.url_pattern.match(url))

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )
        if database_url:
            session_factory = get_session_factory(database_url)
            self._run_session = session_factory()
            shop = upsert_shop(
                self._run_session,
                self.shop_name,
                self.conf.shop.base_url,
            )
            phase = f"discover_{self.strategy}"
            mark_stale_runs_failed(self._run_session, shop.id, phase)
            run = create_scrape_run(self._run_session, shop.id, phase)
            self._run_session.commit()
            self._run_id = run.id
            self._shop_id = shop.id

        if self.strategy == "sitemap":
            yield scrapy.Request(
                self.strategy_conf.url,
                callback=self.parse_sitemap,
                errback=self.handle_start_error,
            )
        elif self.strategy == "categories":
            url = self.strategy_conf.url.format(page=1)
            yield scrapy.Request(
                url,
                callback=self.parse_categories,
                errback=self.handle_start_error,
                meta={"page": 1},
            )
        elif self.strategy == "full_crawl":
            yield scrapy.Request(
                self.strategy_conf.start_url,
                callback=self.parse_full_crawl,
                errback=self.handle_start_error,
            )

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
    ) -> Generator[DiscoveredUrlItem | PriceItem | scrapy.Request, None, None]:
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

                # Also yield price data if available
                if product.get("price"):
                    yield PriceItem(
                        url=url,
                        shop_name=self.shop_name,
                        title=product.get("title", ""),
                        author=product.get("author"),
                        price=product.get("price"),
                        price_original=product.get("price_original"),
                        in_stock=True,
                    )
            else:
                self._urls_filtered += 1

        # Paginate. Respect max_pages when the user set a cap so dev
        # runs don't always exhaust the whole catalog.
        page = response.meta["page"] + 1
        if self._max_pages and page > self._max_pages:
            self.logger.info("max_pages cap: stopping at page %d", self._max_pages)
            return
        next_url = self.strategy_conf.url.format(page=page)
        yield scrapy.Request(
            next_url,
            callback=self.parse_categories,
            errback=self.handle_start_error,
            meta={"page": page},
        )

    def parse_full_crawl(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem | scrapy.Request, None, None]:
        """Follow all internal links, yield product URLs."""
        base_url: str = self.conf.shop.base_url
        seen: set[str] = getattr(self, "_seen_urls", set())
        self._seen_urls = seen
        if self._max_pages and len(seen) >= self._max_pages:
            return

        for link in response.css("a::attr(href)").getall():
            if not link.startswith("http"):
                link = response.urljoin(link)

            if not link.startswith(base_url):
                continue
            if link in seen:
                continue
            seen.add(link)

            if self._url_passes_filter(link):
                self._urls_processed += 1
                yield DiscoveredUrlItem(
                    url=link, shop_name=self.shop_name, source="full_crawl"
                )

            # Follow all internal links for further crawling
            yield scrapy.Request(
                link, callback=self.parse_full_crawl, dont_filter=False
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

        if self._run_id is None or self._run_session is None:
            return
        try:
            status = "completed" if reason == "finished" else "failed"
            # Only the sitemap strategy enumerates every live URL in the
            # shop, so only it can reliably mark vanished shop_books inactive.
            if (
                status == "completed"
                and self.strategy == "sitemap"
                and self._sitemap_urls
                and self._shop_id is not None
            ):
                deactivated = mark_shop_books_inactive(
                    self._run_session,
                    shop_id=self._shop_id,
                    active_urls=self._sitemap_urls,
                )
                if deactivated:
                    self.logger.info(
                        "Change detection: marked %d shop_book(s) inactive",
                        deactivated,
                    )
            # Record final urls_processed — the pipeline only flushes
            # progress every 100 items, so short discover runs would
            # otherwise always show 0.
            update_scrape_run_progress(
                self._run_session,
                self._run_id,
                self._urls_processed,
            )
            # A completed run that found zero URLs on a shop that already
            # had some is almost always a parser break — surface it as a
            # validation issue so it appears in the Issues dashboard
            # instead of silently passing as "completed". Skip when a more
            # specific issue (fetch_failed / empty_first_page) already
            # fired, and on the legitimate first-ever discovery.
            if (
                status == "completed"
                and self._urls_processed == 0
                and not self._zero_yield_suppressed
                and self._shop_id is not None
            ):
                prior_count = (
                    self._run_session.query(DiscoveredUrl)
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
            finish_scrape_run(self._run_session, self._run_id, status)
            self._run_session.commit()
        finally:
            self._run_session.close()
            self._run_session = None
