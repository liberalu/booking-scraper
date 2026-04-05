BOT_NAME = "book_scraper"

SPIDER_MODULES = ["book_scraper.spiders"]
NEWSPIDER_MODULE = "book_scraper.spiders"

# Required for scrapy-impersonate and scrapy-playwright
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

ROBOTSTXT_OBEY = True

CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 1

FEED_EXPORT_ENCODING = "utf-8"

# Item pipelines (enabled later when DB is set up)
# ITEM_PIPELINES = {
#     "book_scraper.pipelines.ValidationPipeline": 100,
#     "book_scraper.pipelines.PostgresPipeline": 200,
# }

# Database connection
DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/book_scraper"
