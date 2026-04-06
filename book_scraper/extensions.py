import logging  # pragma: no cover
import time  # pragma: no cover
from typing import Any  # pragma: no cover

from scrapy import signals  # pragma: no cover
from scrapy.crawler import Crawler  # pragma: no cover
from scrapy.exceptions import NotConfigured  # pragma: no cover

logger = logging.getLogger(__name__)  # pragma: no cover


class StallDetector:  # pragma: no cover
    """Close the spider if no responses arrive for STALL_TIMEOUT seconds.

    Checks every 10 seconds. If the last response was more than
    STALL_TIMEOUT seconds ago, forces a graceful shutdown.
    """

    def __init__(self, crawler: Crawler, stall_timeout: float):
        self.crawler = crawler
        self.stall_timeout = stall_timeout
        self._last_activity = time.monotonic()
        self._check_interval = 10.0
        self._task: Any = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "StallDetector":
        timeout = crawler.settings.getfloat("STALL_TIMEOUT", 0)
        if not timeout:
            raise NotConfigured
        ext = cls(crawler, timeout)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(
            ext.response_received,
            signal=signals.response_received,
        )
        crawler.signals.connect(ext.item_scraped, signal=signals.item_scraped)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_opened(self) -> None:
        self._last_activity = time.monotonic()
        from twisted.internet import reactor

        self._task = reactor.callLater(  # type: ignore[attr-defined]
            self._check_interval, self._check_stall
        )

    def response_received(self, **kwargs: Any) -> None:
        self._last_activity = time.monotonic()

    def item_scraped(self, **kwargs: Any) -> None:
        self._last_activity = time.monotonic()

    def spider_closed(self) -> None:
        if self._task and self._task.active():
            self._task.cancel()

    def _check_stall(self) -> None:
        elapsed = time.monotonic() - self._last_activity
        if elapsed > self.stall_timeout:
            logger.warning(
                "Spider stalled for %.0fs — forcing shutdown",
                elapsed,
            )
            spider = self.crawler.spider
            if spider is None:
                logger.warning("Skipping stall shutdown because no spider is active")
                return
            engine = self.crawler.engine
            if engine is None:
                logger.warning("Skipping stall shutdown because no engine is active")
                return
            engine.close_spider(spider, "stall_timeout")
            return

        from twisted.internet import reactor

        self._task = reactor.callLater(  # type: ignore[attr-defined]
            self._check_interval, self._check_stall
        )
