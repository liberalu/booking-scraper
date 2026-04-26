"""Downloader middleware that uses httpx instead of Twisted.

Twisted's HTTP client hangs on some servers (e.g. vaga.lt) after ~120
requests. This middleware intercepts all requests and uses httpx async
client, which handles the same requests without issues.

Throttling
----------
Returning a Response from `process_request` short-circuits Scrapy's
downloader path entirely — including its slot machinery, which is what
normally enforces ``CONCURRENT_REQUESTS_PER_DOMAIN``, ``DOWNLOAD_DELAY``,
and ``AUTOTHROTTLE``. Stage 0 Gate A confirmed this: ``slot=None`` on
every dispatch, requests fired in 3-50 ms bursts despite the configured
2-second delay.

This middleware therefore enforces pacing itself, per-host:

- A serialised lock per host (one in-flight request per host at a time,
  matching ``CONCURRENT_REQUESTS_PER_DOMAIN = 1``).
- An adaptive delay that starts at ``DOWNLOAD_DELAY`` / ``AUTOTHROTTLE_START_DELAY``
  and drifts toward ``response_latency / AUTOTHROTTLE_TARGET_CONCURRENCY``,
  bounded by ``DOWNLOAD_DELAY`` (floor) and ``AUTOTHROTTLE_MAX_DELAY``
  (ceiling). 5xx responses ratchet the delay up (never down).
- ``request_delay_s`` records the actual sleep we imposed before
  dispatch; ``delay_source`` is ``'autothrottle'`` (when AUTOTHROTTLE is
  on) or ``'configured_delay'`` (when only DOWNLOAD_DELAY is enforced).
"""

import asyncio  # pragma: no cover
import logging  # pragma: no cover
import time  # pragma: no cover
from typing import Any  # pragma: no cover
from urllib.parse import urlparse  # pragma: no cover

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
    """Replace Scrapy's Twisted downloader with async httpx + per-host pacing."""

    def __init__(
        self,
        timeout: float,
        user_agent: str,
        database_url: str | None,
        download_delay: float,
        autothrottle_enabled: bool,
        autothrottle_start_delay: float,
        autothrottle_max_delay: float,
        autothrottle_target_concurrency: float,
    ):
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
        # Throttling configuration
        self._download_delay = download_delay
        self._autothrottle_enabled = autothrottle_enabled
        self._autothrottle_start = max(autothrottle_start_delay, download_delay)
        self._autothrottle_max = max(autothrottle_max_delay, self._autothrottle_start)
        self._autothrottle_target_concurrency = max(
            0.1, autothrottle_target_concurrency
        )
        # Per-host throttling state. Lock serialises per-host dispatch
        # (1 request in flight per host); state dicts track timing.
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_last_dispatch: dict[str, float] = {}
        self._host_current_delay: dict[str, float] = {}

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "HttpxMiddleware":
        s = crawler.settings
        mw = cls(
            timeout=s.getfloat("DOWNLOAD_TIMEOUT", 15),
            user_agent=s.get("USER_AGENT", "Scrapy"),
            database_url=s.get("DATABASE_URL"),
            download_delay=s.getfloat("DOWNLOAD_DELAY", 2.0),
            autothrottle_enabled=s.getbool("AUTOTHROTTLE_ENABLED", True),
            autothrottle_start_delay=s.getfloat("AUTOTHROTTLE_START_DELAY", 2.0),
            autothrottle_max_delay=s.getfloat("AUTOTHROTTLE_MAX_DELAY", 30.0),
            autothrottle_target_concurrency=s.getfloat(
                "AUTOTHROTTLE_TARGET_CONCURRENCY", 1.0
            ),
        )
        crawler.signals.connect(mw._close, signal=signals.spider_closed)
        return mw

    def _host_key(self, url: str) -> str:
        host = urlparse(url).hostname
        return host or "default"

    def _get_lock(self, host: str) -> asyncio.Lock:
        lock = self._host_locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._host_locks[host] = lock
            self._host_current_delay[host] = self._autothrottle_start
        return lock

    def _adjust_delay(
        self,
        host: str,
        latency_s: float,
        status_code: int | None,
    ) -> None:
        """Adapt per-host delay based on observed latency.

        Mirrors Scrapy's AutoThrottle algorithm:

          target_delay = latency / TARGET_CONCURRENCY
          new_delay    = (current + target) / 2
          clamp to [DOWNLOAD_DELAY, AUTOTHROTTLE_MAX_DELAY]

        Plus: 5xx responses ratchet up (never down) so we back off when
        the server is unhappy.
        """
        if not self._autothrottle_enabled:
            return
        current = self._host_current_delay.get(host, self._autothrottle_start)
        target = latency_s / self._autothrottle_target_concurrency
        target = max(self._download_delay, min(self._autothrottle_max, target))
        if status_code is not None and 500 <= status_code < 600:
            new_delay = max(current, target)
        else:
            new_delay = (current + target) / 2.0
        new_delay = max(self._download_delay, min(self._autothrottle_max, new_delay))
        self._host_current_delay[host] = new_delay

    def _mark_processing(
        self,
        item_id: int,
        dispatched_at: float,
        request_delay_s: float | None,
        delay_source: str | None,
    ) -> None:
        """Best-effort: flip scrape_url_items.status to 'processing'.

        Sync SQLAlchemy in an async context — briefly blocks the event
        loop, but with the per-host lock there's only one in flight per
        host and the write is sub-10ms. Failure here must NOT stop the
        request, so we swallow exceptions.
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
                mark_scrape_url_item_processing(
                    session,
                    item_id,
                    dispatched_at,
                    request_delay_s=request_delay_s,
                    delay_source=delay_source,
                )
                session.commit()
            finally:
                session.close()
        except Exception:
            logger.exception("mark_processing failed for item %d", item_id)

    async def process_request(self, request: Request) -> HtmlResponse:
        """Intercept request, pace per-host, then handle with httpx.

        The per-host lock is held for the entire HTTP roundtrip so we
        get true `CONCURRENT_REQUESTS_PER_DOMAIN = 1` semantics. The
        sleep before dispatch is the adaptive delay computed by the
        previous response.

        We stamp `dispatched_at` (post-sleep, immediately before the
        HTTP call) and `request_delay_s` (the actual sleep duration)
        on `request.meta` so the spider can include them in the JSONL
        event log.
        """
        host = self._host_key(str(request.url))
        lock = self._get_lock(host)
        async with lock:
            # Compute and apply the throttle delay BEFORE dispatch.
            current_delay = self._host_current_delay.get(
                host, self._autothrottle_start
            )
            last_dispatch = self._host_last_dispatch.get(host, 0.0)
            now_mono = time.monotonic()
            sleep_for = max(0.0, last_dispatch + current_delay - now_mono)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

            # Now actually dispatch.
            dispatched_at = time.time()
            dispatched_mono = time.monotonic()
            self._host_last_dispatch[host] = dispatched_mono

            request.meta["dispatched_at"] = dispatched_at
            request.meta["request_delay_s"] = sleep_for
            delay_source = (
                "autothrottle" if self._autothrottle_enabled else "configured_delay"
            )
            request.meta["delay_source"] = delay_source

            item_id = request.meta.get("scrape_url_item_id")
            if item_id is not None:
                self._mark_processing(
                    item_id,
                    dispatched_at,
                    sleep_for,
                    delay_source,
                )

            status_code: int | None = None
            try:
                response = await asyncio.wait_for(
                    self.client.get(str(request.url)),
                    timeout=HARD_REQUEST_TIMEOUT_S,
                )
                status_code = response.status_code
                # httpx auto-decompresses gzip, so remove Content-Encoding
                # to prevent Scrapy's HttpCompressionMiddleware from
                # trying to decompress again.
                headers = dict(response.headers)
                headers.pop("content-encoding", None)
                latency = time.monotonic() - dispatched_mono
                self._adjust_delay(host, latency, status_code)
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
                # Treat timeout as a strong "back off" signal — same as
                # 5xx, ratchet delay up to the max.
                self._adjust_delay(host, self._autothrottle_max, 503)
                raise

    async def _close(self) -> None:
        await self.client.aclose()
