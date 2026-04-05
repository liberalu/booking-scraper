from collections.abc import Generator
from typing import Any

import scrapy

from book_scraper.config import load_shop_config
from book_scraper.items import DiscoveredUrlItem
from book_scraper.spiders.vaga.parsers import parse_sitemap_urls

_conf = load_shop_config("vaga")
_discover = _conf.get("discover", {})


class VagaDiscoverSpider(scrapy.Spider):
    name = "vaga_discover"
    allowed_domains = ["vaga.lt"]

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        url = _discover.get("sitemap_url", "https://vaga.lt/sitemap.xml")
        yield scrapy.Request(url)

    def parse(
        self, response: Any, **kwargs: Any
    ) -> Generator[DiscoveredUrlItem, None, None]:
        urls = parse_sitemap_urls(response.text)
        self.logger.info("Found %d URLs in sitemap", len(urls))
        shop_name = _conf.get("shop", {}).get("name", "vaga")
        for url in urls:
            yield DiscoveredUrlItem(url=url, shop_name=shop_name)
