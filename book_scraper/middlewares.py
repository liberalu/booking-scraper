import time  # pragma: no cover
from collections.abc import Generator  # pragma: no cover
from typing import Any  # pragma: no cover

from scrapy import signals  # pragma: no cover
from twisted.internet import reactor  # pragma: no cover


class HardTimeoutMiddleware:  # pragma: no cover
    """Kill any request that exceeds a hard total time limit.

    DOWNLOAD_TIMEOUT only resets on each received byte, so a server
    that trickles data can hold a connection open forever. This
    middleware enforces an absolute wall-clock limit per request.
    """

    def __init__(self, hard_timeout: float = 30.0):
        self.hard_timeout = hard_timeout

    @classmethod
    def from_crawler(cls, crawler: Any) -> "HardTimeoutMiddleware":
        timeout = crawler.settings.getfloat(
            "HARD_TIMEOUT", 30.0
        )
        return cls(hard_timeout=timeout)

    def process_request(
        self, request: Any, spider: Any
    ) -> None:
        request.meta["_hard_timeout_start"] = time.monotonic()
        delayed_call = reactor.callLater(
            self.hard_timeout,
            self._cancel_request,
            request,
            spider,
        )
        request.meta["_hard_timeout_call"] = delayed_call

    def process_response(
        self, request: Any, response: Any, spider: Any
    ) -> Any:
        self._cancel_timer(request)
        return response

    def process_exception(
        self, request: Any, exception: Any, spider: Any
    ) -> None:
        self._cancel_timer(request)

    def _cancel_timer(self, request: Any) -> None:
        delayed_call = request.meta.pop("_hard_timeout_call", None)
        if delayed_call and delayed_call.active():
            delayed_call.cancel()

    def _cancel_request(
        self, request: Any, spider: Any
    ) -> None:
        elapsed = time.monotonic() - request.meta.get(
            "_hard_timeout_start", 0
        )
        spider.logger.warning(
            "Hard timeout (%.0fs) for %s", elapsed, request.url
        )
        # Cancel via the Twisted transport if accessible
        if hasattr(request, "_txresponse") and request._txresponse:
            request._txresponse._transport.loseConnection()


class BookScraperSpiderMiddleware:  # pragma: no cover
    @classmethod
    def from_crawler(
        cls, crawler: Any
    ) -> "BookScraperSpiderMiddleware":
        s = cls()
        crawler.signals.connect(
            s.spider_opened, signal=signals.spider_opened
        )
        return s

    def process_spider_input(
        self, response: Any, spider: Any
    ) -> None:
        return None

    def process_spider_output(
        self, response: Any, result: Any, spider: Any
    ) -> Generator[Any, None, None]:
        yield from result

    def process_spider_exception(
        self, response: Any, exception: Any, spider: Any
    ) -> None:
        pass

    def spider_opened(self, spider: Any) -> None:
        spider.logger.info(f"Spider opened: {spider.name}")
