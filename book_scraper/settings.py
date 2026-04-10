from book_scraper.config import load_default_config  # pragma: no cover

_config = load_default_config()  # pragma: no cover

BOT_NAME = "book_scraper"  # pragma: no cover

SPIDER_MODULES = ["book_scraper.spiders"]  # pragma: no cover
NEWSPIDER_MODULE = "book_scraper.spiders"  # pragma: no cover

# Required for scrapy-impersonate and scrapy-playwright
TWISTED_REACTOR = (  # pragma: no cover
    "twisted.internet.asyncioreactor.AsyncioSelectorReactor"  # pragma: no cover
)  # pragma: no cover

ROBOTSTXT_OBEY = _config.scrapy.robotstxt_obey  # pragma: no cover

# Sensible defaults — override per-spider via -s flag  # pragma: no cover
CONCURRENT_REQUESTS_PER_DOMAIN = 4  # pragma: no cover
DOWNLOAD_DELAY = 0.5  # pragma: no cover
DOWNLOAD_TIMEOUT = 15  # pragma: no cover

# Force fresh TCP connections — vaga.lt silently blocks  # pragma: no cover
# reused connections after ~150 requests  # pragma: no cover
DEFAULT_REQUEST_HEADERS = {  # pragma: no cover
    "Connection": "close",  # pragma: no cover
}  # pragma: no cover

# Auto-close spider if stalled (no responses for N seconds)  # pragma: no cover
STALL_TIMEOUT = 60  # pragma: no cover

EXTENSIONS = {  # pragma: no cover
    "book_scraper.extensions.StallDetector": 500,  # pragma: no cover
}  # pragma: no cover

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

DOWNLOADER_MIDDLEWARES = {  # pragma: no cover
    "book_scraper.download_handler.HttpxMiddleware": 1,  # pragma: no cover
}  # pragma: no cover

ITEM_PIPELINES = {  # pragma: no cover
    "book_scraper.pipelines.ValidationPipeline": 100,  # pragma: no cover
    "book_scraper.pipelines.PostgresPipeline": 200,  # pragma: no cover
}  # pragma: no cover

# Database connection (env var overrides config for Docker)
import os  # pragma: no cover  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", _config.database.url)  # pragma: no cover
