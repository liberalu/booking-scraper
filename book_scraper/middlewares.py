import logging  # pragma: no cover
import time  # pragma: no cover
from typing import Any  # pragma: no cover

from scrapy.crawler import Crawler  # pragma: no cover
from scrapy.exceptions import IgnoreRequest  # pragma: no cover
from twisted.internet import reactor  # pragma: no cover

logger = logging.getLogger(__name__)  # pragma: no cover


class HardTimeoutMiddleware:  # pragma: no cover
    """Kill any request that exceeds a hard total time limit.

    DOWNLOAD_TIMEOUT only resets on each received byte, so a server
    that trickles data can hold a connection open forever. This
    middleware enforces an absolute wall-clock limit per request
    by raising IgnoreRequest after the deadline.
    """

    def __init__(self, hard_timeout: float, crawler: Crawler):
        self.hard_timeout = hard_timeout
        self.crawler = crawler
        self._timed_out_urls: set[str] = set()

    @classmethod
    def from_crawler(
        cls, crawler: Crawler
    ) -> "HardTimeoutMiddleware":
        timeout = crawler.settings.getfloat("HARD_TIMEOUT", 30.0)
        return cls(hard_timeout=timeout, crawler=crawler)

    def process_request(self, request: Any) -> None:
        request.meta["_hard_timeout_start"] = time.monotonic()
        delayed_call = reactor.callLater(  # type: ignore[attr-defined]
            self.hard_timeout,
            self._mark_timed_out,
            request,
        )
        request.meta["_hard_timeout_call"] = delayed_call

    def process_response(
        self, request: Any, response: Any
    ) -> Any:
        self._cancel_timer(request)
        if request.url in self._timed_out_urls:
            self._timed_out_urls.discard(request.url)
            raise IgnoreRequest(
                f"Hard timeout: response arrived too late for {request.url}"
            )
        return response

    def process_exception(
        self, request: Any, exception: Any
    ) -> None:
        self._cancel_timer(request)

    def _cancel_timer(self, request: Any) -> None:
        delayed_call = request.meta.pop("_hard_timeout_call", None)
        if delayed_call and delayed_call.active():
            delayed_call.cancel()

    def _mark_timed_out(self, request: Any) -> None:
        elapsed = time.monotonic() - request.meta.get(
            "_hard_timeout_start", 0
        )
        logger.warning(
            "Hard timeout (%.0fs) for %s — will be retried",
            elapsed,
            request.url,
        )
        self._timed_out_urls.add(request.url)
        # Force-close the slot's active transfer
        try:
            engine: Any = self.crawler.engine
            slot_key = engine.downloader._get_slot_key(request, None)
            if slot_key in engine.downloader.slots:
                s = engine.downloader.slots[slot_key]
                for req, deferred in list(s.transferring.items()):
                    if req is request:
                        deferred.cancel()
                        break
        except Exception:
            pass
