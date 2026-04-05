from collections.abc import Generator
from typing import Any

import scrapy

from book_scraper.items import DiscoveredUrlItem
from book_scraper.spiders.vaga.parsers import parse_sitemap_urls


class VagaDiscoverSpider(scrapy.Spider):
    name = "vaga_discover"
    allowed_domains = ["vaga.lt"]

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        yield scrapy.Request("https://vaga.lt/sitemap.xml")

    def parse(
        self, response: Any, **kwargs: Any
    ) -> Generator[DiscoveredUrlItem, None, None]:
        urls = parse_sitemap_urls(response.text)
        self.logger.info("Found %d URLs in sitemap", len(urls))
        for url in urls:
            yield DiscoveredUrlItem(url=url, shop_name="vaga")
