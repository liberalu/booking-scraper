from collections.abc import Generator
from typing import Any

import scrapy

from book_scraper.config import load_shop_config
from book_scraper.items import PriceItem
from book_scraper.spiders.vaga.parsers import parse_category_page

_conf = load_shop_config("vaga")
_scraping = _conf.get("scraping", {})
_prices = _conf.get("prices", {})


class VagaPricesSpider(scrapy.Spider):
    name = "vaga_prices"
    allowed_domains = ["vaga.lt"]

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": _prices.get(
            "concurrent_requests_per_domain",
            _scraping.get("concurrent_requests_per_domain", 2),
        ),
        "DOWNLOAD_DELAY": _scraping.get("download_delay", 0.5),
    }

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        url = _prices.get(
            "category_url", "https://vaga.lt/knygos?limit=100&page={page}"
        )
        yield scrapy.Request(
            url.format(page=1),
            meta={"page": 1},
        )

    def parse(
        self, response: Any, **kwargs: Any
    ) -> Generator[PriceItem | scrapy.Request, None, None]:
        products = parse_category_page(response.text)
        if not products:
            return

        shop_name = _conf.get("shop", {}).get("name", "vaga")
        for product in products:
            if product["price"] is not None:
                yield PriceItem(
                    url=product["url"],
                    shop_name=shop_name,
                    title=product["title"],
                    price=product["price"],
                    price_original=product["price_original"],
                    in_stock=True,
                )

        page = response.meta["page"] + 1
        url = _prices.get(
            "category_url", "https://vaga.lt/knygos?limit=100&page={page}"
        )
        yield scrapy.Request(
            url.format(page=page),
            callback=self.parse,
            meta={"page": page},
        )
