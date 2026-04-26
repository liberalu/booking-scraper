"""Downloader middleware that uses httpx instead of Twisted.

Twisted's HTTP client hangs on some servers (e.g. vaga.lt) after ~120
requests. This middleware intercepts all requests and uses httpx async
client, which handles the same requests without issues.
"""

import asyncio  # pragma: no cover
import logging  # pragma: no cover
import time  # pragma: no cover
from typing import Any  # pragma: no cover

import httpx  # pragma: no cover
from scrapy import Request, signals  # pragma: no cover
from scrapy.crawler import Crawler  # pragma: no cover
from scrapy.http import HtmlResponse  # pragma: no cover

logger = logging.getLogger(__name__)  # pragma: no cover

# Browser-shaped headers. vaga.lt's TTFB is ~3× higher for non-browser
# UAs (verified empirically: 0.76s for Chrome UA, 2.02s for Scrapy UA on
# the same URL/connection). Sending plausible browser headers prevents
# the server from serving the degraded path.
_BROWSER_HEADERS = {  # pragma: no cover
    "Accept": (  # pragma: no cover
        "text/html,application/xhtml+xml,application/xml;q=0.9,"  # pragma: no cover
        "image/avif,image/webp,*/*;q=0.8"  # pragma: no cover
    ),  # pragma: no cover
    "Accept-Language": "lt,en;q=0.9",  # pragma: no cover
}  # pragma: no cover

# Hard ceiling on total per-request wall time. httpx's per-stage read
# timeout resets on every chunk, so a server that trickles bytes can
# stretch a single request indefinitely — we've observed 5-min outliers.
# This wraps the whole request in asyncio.wait_for so anything past
# this fails fast as a TimeoutError and the spider moves on.
HARD_REQUEST_TIMEOUT_S = 60.0  # pragma: no cover


class HttpxMiddleware:  # pragma: no cover
    """Replace Scrapy's Twisted downloader with async httpx."""

    def __init__(self, timeout: float, user_agent: str, database_url: str | None):
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Connection": "close",
                **_BROWSER_HEADERS,
            },
        )
        self.database_url = database_url
        self._session_factory: Any = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "HttpxMiddleware":
        timeout = crawler.settings.getfloat("DOWNLOAD_TIMEOUT", 15)
        ua = crawler.settings.get("USER_AGENT", "Scrapy")
        database_url = crawler.settings.get("DATABASE_URL")
        mw = cls(timeout=timeout, user_agent=ua, database_url=database_url)
        crawler.signals.connect(mw._close, signal=signals.spider_closed)
        return mw

    def _mark_processing(self, item_id: int, dispatched_at: float) -> None:
        """Best-effort: flip scrape_url_items.status to 'processing'.

        Sync SQLAlchemy in an async context — briefly blocks the event
        loop, but with CONCURRENT_REQUESTS_PER_DOMAIN=1 and ~2s between
        requests there's no contention and the write is sub-10ms. Failure
        here must NOT stop the request, so we swallow exceptions.
        """
        if not self.database_url:
            return
        if self._session_factory is None:
            from book_scraper.db.session import get_session_factory

            self._session_factory = get_session_factory(self.database_url)
        try:
            from book_scraper.db.repo import mark_scrape_url_item_processing

            session = self._session_factory()
            try:
                mark_scrape_url_item_processing(session, item_id, dispatched_at)
                session.commit()
            finally:
                session.close()
        except Exception:
            logger.exception("mark_processing failed for item %d", item_id)

    async def process_request(self, request: Request) -> HtmlResponse:
        """Intercept request and handle with httpx.

        Returning a Response skips Twisted's downloader entirely. Because
        of that, Scrapy's `request_reached_downloader` signal never fires,
        so we stamp the dispatch time directly on `request.meta` here —
        the spider reads it back as the per-URL "started_at".
        """
        dispatched_at = time.time()
        request.meta["dispatched_at"] = dispatched_at
        item_id = request.meta.get("scrape_url_item_id")
        if item_id is not None:
            self._mark_processing(item_id, dispatched_at)
        try:
            response = await asyncio.wait_for(
                self.client.get(str(request.url)),
                timeout=HARD_REQUEST_TIMEOUT_S,
            )
            # httpx auto-decompresses gzip, so remove Content-Encoding
            # to prevent Scrapy's HttpCompressionMiddleware from
            # trying to decompress again.
            headers = dict(response.headers)
            headers.pop("content-encoding", None)
            return HtmlResponse(
                url=str(response.url),
                status=response.status_code,
                headers=headers,
                body=response.content,
                request=request,
                encoding=response.encoding or "utf-8",
            )
        except (httpx.TimeoutException, TimeoutError):
            logger.warning("httpx timeout for %s", request.url)
            raise

    async def _close(self) -> None:
        await self.client.aclose()
