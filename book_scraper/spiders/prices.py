from typing import Any

from book_scraper.spiders.discover import DiscoverSpider


class PricesSpider(DiscoverSpider):
    """Shortcut for: discover -a strategy=categories.

    Performs a price scan from category pages.
    """

    name = "prices"

    def __init__(self, shop: str | None = None, **kwargs: Any):
        super().__init__(shop=shop, strategy="categories", **kwargs)
