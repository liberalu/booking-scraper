import logging  # pragma: no cover
import time  # pragma: no cover
from typing import Any  # pragma: no cover

from scrapy.crawler import Crawler  # pragma: no cover
from twisted.internet import reactor  # pragma: no cover

logger = logging.getLogger(__name__)  # pragma: no cover


class HardTimeoutMiddleware:  # pragma: no cover
    """Kill any request that exceeds a hard total time limit.

    DOWNLOAD_TIMEOUT only resets on each received byte, so a server
    that trickles data can hold a connection open forever. This
    middleware enforces an absolute wall-clock limit per request.
    """

    def __init__(self, hard_timeout: float = 30.0):
        self.hard_timeout = hard_timeout

    @classmethod
    def from_crawler(
        cls, crawler: Crawler
    ) -> "HardTimeoutMiddleware":
        timeout = crawler.settings.getfloat("HARD_TIMEOUT", 30.0)
        return cls(hard_timeout=timeout)

    def process_request(self, request: Any) -> None:
        request.meta["_hard_timeout_start"] = time.monotonic()
        delayed_call = reactor.callLater(
            self.hard_timeout,
            self._cancel_request,
            request,
        )
        request.meta["_hard_timeout_call"] = delayed_call

    def process_response(
        self, request: Any, response: Any
    ) -> Any:
        self._cancel_timer(request)
        return response

    def process_exception(
        self, request: Any, exception: Any
    ) -> None:
        self._cancel_timer(request)

    def _cancel_timer(self, request: Any) -> None:
        delayed_call = request.meta.pop("_hard_timeout_call", None)
        if delayed_call and delayed_call.active():
            delayed_call.cancel()

    def _cancel_request(self, request: Any) -> None:
        elapsed = time.monotonic() - request.meta.get(
            "_hard_timeout_start", 0
        )
        logger.warning(
            "Hard timeout (%.0fs) for %s", elapsed, request.url
        )
        if hasattr(request, "_txresponse") and request._txresponse:
            request._txresponse._transport.loseConnection()
