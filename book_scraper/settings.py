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
# vaga.lt silently throttles bursts: with 4 concurrent + 0.5s delay,  # pragma: no cover
# scan run 156 saw ~0.6 responses/min before stall. Drop concurrency  # pragma: no cover
# to 1 and slow cadence so the server has breathing room.  # pragma: no cover
CONCURRENT_REQUESTS_PER_DOMAIN = 1  # pragma: no cover
DOWNLOAD_DELAY = 2.0  # pragma: no cover
DOWNLOAD_TIMEOUT = 15  # pragma: no cover

# Force fresh TCP connections — vaga.lt silently blocks  # pragma: no cover
# reused connections after ~150 requests  # pragma: no cover
DEFAULT_REQUEST_HEADERS = {  # pragma: no cover
    "Connection": "close",  # pragma: no cover
}  # pragma: no cover

# Auto-close spider if stalled (no responses for N seconds AND no
# in-flight requests). StallDetector now checks both conditions:  # pragma: no cover
# timer expired + downloader idle. With that fix, 180s is a generous
# safety net; a request that genuinely hangs forever (no response, no
# TCP error) will still be caught once the downloader drains.
STALL_TIMEOUT = 180  # pragma: no cover

# When StallDetector kills a run, automatically spawn a fresh scrapy
# process up to N times in a row. The spawned spider's
# `prepare_discover` finds the failed-resumable run and inherits its
# pending queue (with retryable failures reset to pending), so the
# crawl makes forward progress without operator intervention. Set to 0
# to disable. Counts via the `resumed_after_failure` event chain on
# scrape_run_events so a run that got resumed from outside (via the
# dashboard's Continue button) also counts toward the cap.
STALL_AUTO_RESUME_MAX = 10  # pragma: no cover

# After a stall fires, ``engine.close_spider()`` waits for the
# pipeline backlog to drain. With slow Postgres writes that can take
# many minutes — the auto-resume spawn (which runs in spider_closed)
# is blocked the whole time, leaving the queue stalled. If the spider
# hasn't actually closed within this many seconds of the stall, force
# the spawn now and `os._exit` the dying process. The new subprocess
# still passes the "another run already active?" precheck because the
# old run row is already `failed` by then.
STALL_FORCE_EXIT_S = 60  # pragma: no cover

EXTENSIONS = {  # pragma: no cover
    "book_scraper.extensions.StallDetector": 500,  # pragma: no cover
    "book_scraper.extensions.HeartbeatExtension": 510,  # pragma: no cover
}  # pragma: no cover

# Per-run heartbeat tick interval (seconds). Independent of request
# flow; the dashboard uses staleness to detect crashed scrapers.
HEARTBEAT_INTERVAL_S = 5.0  # pragma: no cover

# Periodic httpx.AsyncClient reset. vaga.lt (and likely others)
# silently stop responding after ~100 requests on the same client —
# TIME_WAIT pile-up client-side, server-side cumulative tracking, or
# both. Reset before either wall.
HTTPX_CLIENT_RESET_AFTER_REQUESTS = 80  # pragma: no cover

# AutoThrottle — adapts speed based on server response  # pragma: no cover
AUTOTHROTTLE_ENABLED = True  # pragma: no cover
AUTOTHROTTLE_START_DELAY = 2.0  # pragma: no cover
AUTOTHROTTLE_MAX_DELAY = 30  # pragma: no cover
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0  # pragma: no cover

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
