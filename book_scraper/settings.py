from book_scraper.config import load_default_config  # pragma: no cover

_config = load_default_config()  # pragma: no cover
_scrapy = _config.get("scrapy", {})  # pragma: no cover
_db = _config.get("database", {})  # pragma: no cover

BOT_NAME = "book_scraper"  # pragma: no cover

SPIDER_MODULES = ["book_scraper.spiders"]  # pragma: no cover
NEWSPIDER_MODULE = "book_scraper.spiders"  # pragma: no cover

# Required for scrapy-impersonate and scrapy-playwright
TWISTED_REACTOR = (  # pragma: no cover
    "twisted.internet.asyncioreactor.AsyncioSelectorReactor"  # pragma: no cover
)  # pragma: no cover

ROBOTSTXT_OBEY = _scrapy.get("robotstxt_obey", True)  # pragma: no cover

# Sensible defaults — override per-spider via -s flag  # pragma: no cover
CONCURRENT_REQUESTS_PER_DOMAIN = 4  # pragma: no cover
DOWNLOAD_DELAY = 0.5  # pragma: no cover
DOWNLOAD_TIMEOUT = 15  # pragma: no cover

# AutoThrottle — adapts speed based on server response  # pragma: no cover
AUTOTHROTTLE_ENABLED = True  # pragma: no cover
AUTOTHROTTLE_START_DELAY = 0.5  # pragma: no cover
AUTOTHROTTLE_MAX_DELAY = 10  # pragma: no cover
AUTOTHROTTLE_TARGET_CONCURRENCY = 4.0  # pragma: no cover

FEED_EXPORT_ENCODING = "utf-8"  # pragma: no cover

# Log warnings/errors to file (console output unaffected)  # pragma: no cover
import logging  # pragma: no cover  # noqa: E402

_file_handler = logging.FileHandler("scrapy_errors.log")  # pragma: no cover
_file_handler.setLevel(logging.WARNING)  # pragma: no cover
_fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"  # pragma: no cover
_file_handler.setFormatter(logging.Formatter(_fmt))  # pragma: no cover
logging.getLogger().addHandler(_file_handler)  # pragma: no cover

ITEM_PIPELINES = {  # pragma: no cover
    "book_scraper.pipelines.ValidationPipeline": 100,  # pragma: no cover
    "book_scraper.pipelines.PostgresPipeline": 200,  # pragma: no cover
}  # pragma: no cover

# Database connection
_default_db_url = (  # pragma: no cover
    "postgresql+asyncpg://postgres:postgres"  # pragma: no cover
    "@localhost:5432/book_scraper"  # pragma: no cover
)  # pragma: no cover
DATABASE_URL = _db.get("url", _default_db_url)  # pragma: no cover
