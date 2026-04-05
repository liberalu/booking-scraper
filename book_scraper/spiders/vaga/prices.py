import scrapy

from book_scraper.items import PriceItem
from book_scraper.spiders.vaga.parsers import parse_category_page


class VagaPricesSpider(scrapy.Spider):
    name = "vaga_prices"
    allowed_domains = ["vaga.lt"]

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 0.5,
    }

    def start_requests(self):
        yield scrapy.Request(
            "https://vaga.lt/knygos?limit=100&page=1",
            meta={"page": 1},
        )

    def parse(self, response):
        products = parse_category_page(response.text)
        if not products:
            return

        for product in products:
            if product["price"] is not None:
                yield PriceItem(
                    url=product["url"],
                    shop_name="vaga",
                    price=product["price"],
                    price_original=product["price_original"],
                    in_stock=True,
                )

        page = response.meta["page"] + 1
        yield scrapy.Request(
            f"https://vaga.lt/knygos?limit=100&page={page}",
            callback=self.parse,
            meta={"page": page},
        )
