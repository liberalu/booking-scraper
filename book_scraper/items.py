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
    format = scrapy.Field()
    description = scrapy.Field()
    image_url = scrapy.Field()
    categories = scrapy.Field()
    properties = (
        scrapy.Field()
    )  # JSONB: format-specific fields (pages, cover_type, duration, narrator, etc.)
    price = scrapy.Field()
    price_original = scrapy.Field()
    in_stock = scrapy.Field()


class PriceItem(scrapy.Item):
    """Lightweight price-only data for re-scraping."""

    url = scrapy.Field()
    shop_name = scrapy.Field()
    title = scrapy.Field()
    author = scrapy.Field()
    price = scrapy.Field()
    price_original = scrapy.Field()
    in_stock = scrapy.Field()


class DiscoveredUrlItem(scrapy.Item):
    """A URL found during discovery phase."""

    url = scrapy.Field()
    shop_name = scrapy.Field()
    source = scrapy.Field()  # "sitemap", "category", or "full_crawl"
