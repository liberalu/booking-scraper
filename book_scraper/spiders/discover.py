import re
from collections.abc import AsyncGenerator, Generator
from typing import Any

import scrapy
from sqlalchemy.orm import Session

from book_scraper.config import load_shop_config
from book_scraper.db.repo import (
    create_scrape_run,
    finish_scrape_run,
    mark_stale_runs_failed,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory
from book_scraper.items import DiscoveredUrlItem, PriceItem
from book_scraper.spiders.registry import load_parsers


class DiscoverSpider(scrapy.Spider):
    name = "discover"

    def __init__(
        self, shop: str | None = None, strategy: str = "sitemap", **kwargs: Any
    ):
        super().__init__(**kwargs)
        if not shop:
            raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
        self.shop_name = shop
        self.strategy = strategy
        self.conf = load_shop_config(shop)
        self.parsers = load_parsers(shop)
        self.allowed_domains = [
            self.conf["shop"]["base_url"].replace("https://", "").replace("http://", "")
        ]

        # Load URL filter pattern
        discover_conf = self.conf.get("discover", {})
        pattern = discover_conf.get("url_include_pattern")
        self.url_pattern: re.Pattern[str] | None = (
            re.compile(pattern) if pattern else None
        )

        # Load strategy-specific config
        strategy_conf = discover_conf.get(strategy)
        if strategy_conf is None:
            raise ValueError(f"Strategy '{strategy}' not configured for shop '{shop}'")
        self.strategy_conf: dict[str, Any] = strategy_conf

        self._run_id: int | None = None
        self._urls_processed: int = 0
        self._run_session: Session | None = None

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
                self.conf["shop"]["base_url"],
            )
            phase = f"discover_{self.strategy}"
            mark_stale_runs_failed(self._run_session, shop.id, phase)
            run = create_scrape_run(self._run_session, shop.id, phase)
            self._run_session.commit()
            self._run_id = run.id

        if self.strategy == "sitemap":
            yield scrapy.Request(self.strategy_conf["url"], callback=self.parse_sitemap)
        elif self.strategy == "categories":
            url = self.strategy_conf["url"].format(page=1)
            yield scrapy.Request(url, callback=self.parse_categories, meta={"page": 1})
        elif self.strategy == "full_crawl":
            yield scrapy.Request(
                self.strategy_conf["start_url"],
                callback=self.parse_full_crawl,
            )

    def parse_sitemap(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem, None, None]:
        urls: list[str] = self.parsers.parse_sitemap_urls(response.text)
        self.logger.info("Found %d URLs in sitemap", len(urls))
        for url in urls:
            if self._url_passes_filter(url):
                self._urls_processed += 1
                yield DiscoveredUrlItem(
                    url=url, shop_name=self.shop_name, source="sitemap"
                )

    def parse_categories(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem | PriceItem | scrapy.Request, None, None]:
        products: list[dict[str, str | None]] = self.parsers.parse_category_page(
            response.text
        )
        if not products:
            return  # No more pages

        base_url: str = self.conf["shop"]["base_url"]
        for product in products:
            url = product["url"]
            if url and not url.startswith("http"):
                url = base_url + url

            if url and self._url_passes_filter(url):
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
                        price=product.get("price"),
                        price_original=product.get("price_original"),
                        in_stock=True,
                    )

        # Paginate
        page = response.meta["page"] + 1
        next_url = self.strategy_conf["url"].format(page=page)
        yield scrapy.Request(
            next_url, callback=self.parse_categories, meta={"page": page}
        )

    def parse_full_crawl(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem | scrapy.Request, None, None]:
        """Follow all internal links, yield product URLs."""
        base_url: str = self.conf["shop"]["base_url"]
        seen: set[str] = getattr(self, "_seen_urls", set())
        self._seen_urls = seen

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
        if self._run_id is None or self._run_session is None:
            return
        try:
            status = "completed" if reason == "finished" else "failed"
            finish_scrape_run(self._run_session, self._run_id, status)
            self._run_session.commit()
        finally:
            self._run_session.close()
            self._run_session = None
