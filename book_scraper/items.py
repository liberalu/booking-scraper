import scrapy


class ListingItem(scrapy.Item):
    """Full product data from a shop."""

    url = scrapy.Field()
    shop_name = scrapy.Field()
    title = scrapy.Field()
    author = scrapy.Field()
    sku = scrapy.Field()
    isbn = scrapy.Field()
    publisher = scrapy.Field()
    year = scrapy.Field()
    pages = scrapy.Field()
    cover_type = scrapy.Field()
    format = scrapy.Field()
    duration = scrapy.Field()
    narrator = scrapy.Field()
    translator = scrapy.Field()
    description = scrapy.Field()
    image_url = scrapy.Field()
    price = scrapy.Field()
    price_original = scrapy.Field()
    in_stock = scrapy.Field()
    categories = scrapy.Field()


class PriceItem(scrapy.Item):
    """Lightweight price-only data for re-scraping."""

    url = scrapy.Field()
    shop_name = scrapy.Field()
    title = scrapy.Field()
    price = scrapy.Field()
    price_original = scrapy.Field()
    in_stock = scrapy.Field()


class DiscoveredUrlItem(scrapy.Item):
    """A URL found during discovery phase."""

    url = scrapy.Field()
    shop_name = scrapy.Field()
