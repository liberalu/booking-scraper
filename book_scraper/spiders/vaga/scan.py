from collections.abc import Generator
from typing import Any

import scrapy

from book_scraper.items import ListingItem
from book_scraper.spiders.vaga.parsers import parse_product_page


class VagaScanSpider(scrapy.Spider):
    name = "vaga_scan"
    allowed_domains = ["vaga.lt"]

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 3,
        "DOWNLOAD_DELAY": 0.5,
    }

    def __init__(self, urls_file: str | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.urls_file = urls_file

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        if self.urls_file:
            with open(self.urls_file) as f:
                for line in f:
                    url = line.strip()
                    if url:
                        yield scrapy.Request(url, callback=self.parse_product)
        else:
            yield scrapy.Request(
                "https://vaga.lt/knygos?limit=100&page=1",
                callback=self.parse_category,
                meta={"page": 1},
            )

    def parse_category(self, response: Any) -> Generator[scrapy.Request, None, None]:
        links = response.css(".name a::attr(href)").getall()
        if not links:
            return
        for link in links:
            # Strip query params (e.g. ?limit=100) to get clean product URLs
            clean_url = link.split("?")[0]
            yield scrapy.Request(clean_url, callback=self.parse_product)

        page = response.meta["page"] + 1
        yield scrapy.Request(
            f"https://vaga.lt/knygos?limit=100&page={page}",
            callback=self.parse_category,
            meta={"page": page},
        )

    def parse_product(self, response: Any) -> Generator[ListingItem, None, None]:
        data = parse_product_page(response.text)
        if data["title"] is None:
            return

        yield ListingItem(
            url=response.url.split("?")[0],
            shop_name="vaga",
            title=data["title"],
            author=data.get("author"),
            sku=data.get("sku"),
            isbn=data.get("isbn"),
            publisher=data.get("publisher"),
            year=data.get("year"),
            pages=data.get("pages"),
            cover_type=data.get("cover_type"),
            description=data.get("description"),
            image_url=data.get("image_url"),
            price=data.get("price"),
            price_original=data.get("price_original"),
            in_stock=data.get("in_stock"),
            categories=data.get("categories", []),
        )
