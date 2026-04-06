from book_scraper.config import load_default_config  # pragma: no cover

_config = load_default_config()  # pragma: no cover
_scrapy = _config.get("scrapy", {})  # pragma: no cover
_db = _config.get("database", {})  # pragma: no cover

BOT_NAME = "book_scraper"  # pragma: no cover

SPIDER_MODULES = ["book_scraper.spiders"]  # pragma: no cover
NEWSPIDER_MODULE = "book_scraper.spiders"  # pragma: no cover

# Required for scrapy-impersonate and scrapy-playwright
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"  # pragma: no cover

ROBOTSTXT_OBEY = _scrapy.get("robotstxt_obey", True)  # pragma: no cover

CONCURRENT_REQUESTS_PER_DOMAIN = _scrapy.get("concurrent_requests_per_domain", 1)  # pragma: no cover
DOWNLOAD_DELAY = _scrapy.get("download_delay", 1)  # pragma: no cover

FEED_EXPORT_ENCODING = "utf-8"  # pragma: no cover

ITEM_PIPELINES = {  # pragma: no cover
    "book_scraper.pipelines.ValidationPipeline": 100,  # pragma: no cover
    "book_scraper.pipelines.PostgresPipeline": 200,  # pragma: no cover
}  # pragma: no cover

# Database connection
DATABASE_URL = _db.get(  # pragma: no cover
    "url", "postgresql+asyncpg://postgres:postgres@localhost:5432/book_scraper"  # pragma: no cover
)  # pragma: no cover
