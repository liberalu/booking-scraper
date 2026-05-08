import scrapy


class ShopBookItem(scrapy.Item):
    """Full product data from a shop."""

    url = scrapy.Field()
    shop_name = scrapy.Field()
    type = scrapy.Field()
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
    planned_availability_date = scrapy.Field()
    rating = scrapy.Field()
    review_count = scrapy.Field()


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


class BookItem(scrapy.Item):
    """Canonical bibliographic record. Goes to the books table.

    Distinct from ShopBookItem: no price, no shop, no URL — represents
    a book as it exists in the world (LIBIS catalogue or shop_inferred).
    """

    libis_code = scrapy.Field()
    data_source = scrapy.Field()
    title = scrapy.Field()
    title_full = scrapy.Field()
    year = scrapy.Field()
    publisher = scrapy.Field()
    series = scrapy.Field()
    isbns = scrapy.Field()
    authors = scrapy.Field()
    release_place = scrapy.Field()
    type = scrapy.Field()
    format = scrapy.Field()
    pages = scrapy.Field()
    duration = scrapy.Field()
    dimensions = scrapy.Field()
    language = scrapy.Field()
    translated_from = scrapy.Field()
    description = scrapy.Field()
    cover_url = scrapy.Field()
    upcoming_release = scrapy.Field()
    udc_codes = scrapy.Field()
    subjects = scrapy.Field()
    audience = scrapy.Field()
    libis_rating = scrapy.Field()
    libis_review_count = scrapy.Field()
