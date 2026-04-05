from book_scraper.config import load_default_config

_config = load_default_config()
_scrapy = _config.get("scrapy", {})
_db = _config.get("database", {})

BOT_NAME = "book_scraper"

SPIDER_MODULES = ["book_scraper.spiders"]
NEWSPIDER_MODULE = "book_scraper.spiders"

# Required for scrapy-impersonate and scrapy-playwright
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

ROBOTSTXT_OBEY = _scrapy.get("robotstxt_obey", True)

CONCURRENT_REQUESTS_PER_DOMAIN = _scrapy.get("concurrent_requests_per_domain", 1)
DOWNLOAD_DELAY = _scrapy.get("download_delay", 1)

FEED_EXPORT_ENCODING = "utf-8"

ITEM_PIPELINES = {
    "book_scraper.pipelines.ValidationPipeline": 100,
    "book_scraper.pipelines.PostgresPipeline": 200,
}

# Database connection
DATABASE_URL = _db.get("url", "postgresql+asyncpg://postgres:postgres@localhost:5432/book_scraper")
