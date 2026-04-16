"""Downloader middleware that uses httpx instead of Twisted.

Twisted's HTTP client hangs on some servers (e.g. vaga.lt) after ~120
requests. This middleware intercepts all requests and uses httpx async
client, which handles the same requests without issues.
"""

import logging  # pragma: no cover

import httpx  # pragma: no cover
from scrapy import Request, signals  # pragma: no cover
from scrapy.crawler import Crawler  # pragma: no cover
from scrapy.http import HtmlResponse  # pragma: no cover

logger = logging.getLogger(__name__)  # pragma: no cover


class HttpxMiddleware:  # pragma: no cover
    """Replace Scrapy's Twisted downloader with async httpx."""

    def __init__(self, timeout: float, user_agent: str):
        # max_keepalive_connections=0 matches the `Connection: close`
        # header — vaga.lt silently blocks reused sockets after ~150
        # requests. Without this the default pool (keepalive=20,
        # max=100) wedges around request ~100: httpx still holds the
        # sockets that the server marked stale, and process_request
        # awaits a pool slot that never frees.
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=200,
                max_keepalive_connections=0,
            ),
            headers={
                "User-Agent": user_agent,
                "Connection": "close",
            },
        )

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "HttpxMiddleware":
        timeout = crawler.settings.getfloat("DOWNLOAD_TIMEOUT", 15)
        ua = crawler.settings.get("USER_AGENT", "Scrapy")
        mw = cls(timeout=timeout, user_agent=ua)
        crawler.signals.connect(mw._close, signal=signals.spider_closed)
        return mw

    async def process_request(self, request: Request) -> HtmlResponse:
        """Intercept request and handle with httpx.

        Returning a Response skips Twisted's downloader entirely.
        """
        try:
            response = await self.client.get(str(request.url))
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
        except httpx.TimeoutException:
            logger.warning("httpx timeout for %s", request.url)
            raise

    async def _close(self) -> None:
        await self.client.aclose()
