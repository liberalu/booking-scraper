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
        client_reset_after_requests: int,
    ):
        self._timeout = timeout
        self._user_agent = user_agent
        self.client = self._make_client()
        self.database_url = database_url
        self._session_factory: Any = None
        # Throttling configuration
        self._download_delay = download_delay
        self._autothrottle_enabled = autothrottle_enabled
        self._autothrottle_start = max(autothrottle_start_delay, download_delay)
        self._autothrottle_max = max(autothrottle_max_delay, self._autothrottle_start)
        # `_autothrottle_target_concurrency` is no longer a constructor
        # input — it's always derived from the per-shop concurrency in
        # `spider_opened` (see commit 62f2df8). The 1.0 placeholder here
        # is harmless: it's only consulted if `_adjust_delay` runs before
        # `spider_opened`, which can't happen on a real run (the signal
        # always fires first). Tests that call `_adjust_delay` directly
        # set this attribute themselves.
        self._autothrottle_target_concurrency: float = 1.0
        # Per-host throttling state.
        # _host_slots: Semaphore caps in-flight requests to _max_concurrency.
        # _host_dispatch_locks: Lock serialises timing/sleep so concurrent
        #   coroutines don't all read last_dispatch=0 and race to fire.
        self._max_concurrency: int = 1
        self._host_slots: dict[str, asyncio.Semaphore] = {}
        self._host_dispatch_locks: dict[str, asyncio.Lock] = {}
        self._host_last_dispatch: dict[str, float] = {}
        self._host_current_delay: dict[str, float] = {}
        # Client-rotation: vaga.lt (and likely others) silently stop
        # responding after ~100 requests on the same httpx.AsyncClient
        # instance. Cause is connection-level — TIME_WAIT pile-up on
        # the client side from `Connection: close`, server-side
        # cumulative tracking, or both. Tear the client down and
        # recreate it before we hit either wall. See follow-up #10
        # in docs/superpowers/follow-ups/2026-04-26-live-observability-follow-ups.md.
        self._client_reset_after = max(1, client_reset_after_requests)
        self._requests_since_reset = 0
        self._client_lock = asyncio.Lock()  # serialises client swap
        # Old clients are retired here rather than immediately closed so
        # in-flight requests (concurrent > 1) can finish normally.
        # The list is drained at spider_closed.
        self._retired_clients: list[httpx.AsyncClient] = []
        self._crawler: Crawler | None = None

    def _make_client(self) -> "httpx.AsyncClient":
        return httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={
                "User-Agent": self._user_agent,
                "Connection": "close",
                **_BROWSER_HEADERS,
            },
        )

    async def _maybe_reset_client(self, reset_after: int | None = None) -> None:
        """Rotate the httpx.AsyncClient every N requests.

        Bounded TIME_WAIT pile-up + bounded server-side state. Holds
        a tiny critical section to swap-and-close so concurrent
        callers don't see a half-closed client. (With CONCURRENT_
        REQUESTS_PER_DOMAIN = 1 we don't really get concurrent
        callers, but be defensive in case future shops bump it.)

        ``reset_after`` may be supplied per-call (e.g. read from the
        active spider's shop config) to override the global default.
        """
        threshold = reset_after if reset_after is not None else self._client_reset_after
        threshold = max(1, threshold)
        # Read+increment under the same lock to avoid two requests
        # both deciding "I will reset".
        async with self._client_lock:
            self._requests_since_reset += 1
            if self._requests_since_reset < threshold:
                return
            old = self.client
            self.client = self._make_client()
            self._requests_since_reset = 0
        # Retire instead of closing immediately: in-flight requests on `old`
        # can finish normally. The list is drained at spider_closed.
        self._retired_clients.append(old)

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
            client_reset_after_requests=s.getint(
                "HTTPX_CLIENT_RESET_AFTER_REQUESTS", 80
            ),
        )
        # Scrapy 2.14+ only passes `spider` to process_request if the argument
        # is required (no default). Save the crawler to access spider via
        # crawler.spider instead.
        mw._crawler = crawler
        crawler.signals.connect(mw._close, signal=signals.spider_closed)
        crawler.signals.connect(mw.spider_opened, signal=signals.spider_opened)
        return mw

    def spider_opened(self, spider: Any) -> None:
        """Apply per-shop rate settings before any requests dispatch.

        Precedence (highest first): ``shop_settings`` DB row → TOML
        ``[scraping]`` block in ``config/shops/<shop>.toml`` → Scrapy
        globals from ``settings.py`` (already baked into ``self``).
        TOML defaults to its model values (1.0s delay, concurrency=1)
        when the section is omitted, so the chain is always
        well-defined.
        """
        shop_name = getattr(spider, "shop_name", None)
        if not shop_name:
            return

        # Step 1: TOML defaults (per-shop config). Loaded fresh here so a
        # `config/shops/<shop>.toml` edit takes effect on the next run
        # without requiring spider code to pre-populate it.
        toml_download_delay: float = self._download_delay
        toml_concurrency: int = self._max_concurrency
        try:
            from book_scraper.config import load_shop_config

            shop_conf = load_shop_config(shop_name)
            toml_download_delay = float(shop_conf.scraping.download_delay)
            toml_concurrency = int(shop_conf.scraping.concurrent_requests_per_domain)
        except Exception:
            logger.exception(
                "spider_opened: failed to read TOML config for %s; "
                "falling back to Scrapy globals",
                shop_name,
            )

        # Step 2: shop_settings DB rows (highest precedence). Operator
        # overrides applied without redeploying.
        raw: dict[str, tuple[str, str]] = {}
        if self.database_url:
            try:
                if self._session_factory is None:
                    from book_scraper.db.session import get_session_factory

                    self._session_factory = get_session_factory(self.database_url)
                from book_scraper.db.models import Shop, ShopSettings

                session = self._session_factory()
                try:
                    rows = (
                        session.query(ShopSettings)
                        .join(Shop, Shop.id == ShopSettings.shop_id)
                        .filter(Shop.name == shop_name)
                        .all()
                    )
                    raw = {r.key: (r.value, r.type) for r in rows}
                finally:
                    session.close()
            except Exception:
                logger.exception(
                    "spider_opened: failed to read shop_settings for %s; "
                    "using TOML/global defaults",
                    shop_name,
                )

        def _cast(key: str, default: float | int) -> float | int:
            entry = raw.get(key)
            if entry is None:
                return default
            val, type_hint = entry
            try:
                return float(val) if type_hint == "float" else int(val)
            except (ValueError, TypeError):
                return default

        download_delay = max(
            0.1, min(60.0, float(_cast("download_delay", toml_download_delay)))
        )
        concurrency = max(
            1,
            min(16, int(_cast("concurrent_requests_per_domain", toml_concurrency))),
        )
        self._download_delay = download_delay
        self._autothrottle_start = download_delay
        self._autothrottle_max = max(self._autothrottle_max, download_delay)
        self._max_concurrency = concurrency
        # Bridge per-shop concurrency to AutoThrottle's target. The
        # algorithm picks `target_delay = latency / target_concurrency`,
        # so leaving target=1.0 (Scrapy's global default) makes
        # `current_delay` drift toward `latency` regardless of how many
        # slots the semaphore exposes — dispatches stay serial and
        # `_max_concurrency` never engages. Verified on patogupirkti
        # run 367 (2026-05-08): concurrency=4 in TOML, avg dispatch
        # gap ≈ avg latency ≈ 1.2 s, in-flight ≈ 1.17. With target tied
        # to concurrency, target_delay = latency / 4 ≈ 0.35 s and the
        # semaphore actually saturates.
        self._autothrottle_target_concurrency = float(concurrency)
        self._host_slots.clear()
        self._host_dispatch_locks.clear()
        self._host_last_dispatch.clear()
        self._host_current_delay.clear()
        logger.info(
            "HttpxMiddleware: rate for %s — "
            "download_delay=%.2fs concurrent=%d target_concurrency=%.1f",
            shop_name,
            self._download_delay,
            self._max_concurrency,
            self._autothrottle_target_concurrency,
        )

    def _host_key(self, url: str) -> str:
        host = urlparse(url).hostname
        return host or "default"

    def _get_slot(self, host: str) -> tuple[asyncio.Semaphore, asyncio.Lock]:
        slot = self._host_slots.get(host)
        if slot is None:
            slot = asyncio.Semaphore(self._max_concurrency)
            self._host_slots[host] = slot
            self._host_dispatch_locks[host] = asyncio.Lock()
            self._host_current_delay[host] = self._autothrottle_start
        return slot, self._host_dispatch_locks[host]

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

        Plus: failure responses ratchet up (never down) so we back off
        when the server is unhappy. "Failure" includes both 5xx and
        ``status_code is None`` (timeout / connection drop / DNS
        failure / TLS error). The latter is the more important case:
        a flood of timeouts usually means the server is dying or
        Cloudflare is blocking us, and treating it as "things are fine,
        decay the delay" via the averaging branch was the inverse of
        what we want. Treating it as a back-off signal protects the
        server while it's struggling and avoids escalating Cloudflare's
        challenge tier.
        """
        if not self._autothrottle_enabled:
            return
        current = self._host_current_delay.get(host, self._autothrottle_start)
        target = latency_s / self._autothrottle_target_concurrency
        target = max(self._download_delay, min(self._autothrottle_max, target))
        is_failure = status_code is None or 500 <= status_code < 600
        new_delay = max(current, target) if is_failure else (current + target) / 2.0
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

    async def process_request(
        self, request: Request, spider: Any = None
    ) -> HtmlResponse:
        """Intercept request, pace per-host, then handle with httpx.

        The Semaphore limits concurrent in-flight requests per host to
        _max_concurrency. The inner dispatch_lock serialises timing/sleep so
        concurrent coroutines don't race on last_dispatch. The dispatch_lock
        is released before the HTTP call so in-flight requests can overlap.
        """
        host = self._host_key(str(request.url))
        slot, dispatch_lock = self._get_slot(host)
        async with slot:
            async with dispatch_lock:
                # Compute and apply the throttle delay BEFORE dispatch.
                current_delay = self._host_current_delay.get(
                    host, self._autothrottle_start
                )
                last_dispatch = self._host_last_dispatch.get(host, 0.0)
                now_mono = time.monotonic()
                sleep_for = max(0.0, last_dispatch + current_delay - now_mono)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)

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

            # dispatch_lock released — timing serialised, HTTP call can overlap.

            # Rotate the httpx client periodically and read per-shop timeouts.
            # shop config read_timeout overrides the httpx client-level default
            # (set from DOWNLOAD_TIMEOUT at startup); hard_timeout overrides the
            # asyncio.wait_for ceiling. Without this, cold Magento FPC misses
            # (~50-90s) are killed at the httpx client's 15s default.
            #
            # Scrapy 2.14+ only passes `spider` to process_request when the
            # argument is required (no default). Use self._crawler.spider instead.
            reset_after: int | None = None
            req_timeout: float | None = None
            hard_timeout: float = HARD_REQUEST_TIMEOUT_S
            active_spider = getattr(self, "_crawler", None)
            active_spider = active_spider.spider if active_spider is not None else None
            shop_conf = getattr(active_spider, "conf", None)
            if shop_conf is not None:
                scraping = getattr(shop_conf, "scraping", None)
                if scraping is not None:
                    reset_after = getattr(
                        scraping, "httpx_client_reset_after_requests", None
                    )
                    rt = getattr(scraping, "read_timeout", None)
                    if rt is not None:
                        req_timeout = float(rt)
                    ht = getattr(scraping, "hard_timeout", None)
                    if ht is not None:
                        hard_timeout = float(ht)
            await self._maybe_reset_client(reset_after)

            req_kwargs: dict[str, Any] = {}
            if req_timeout is not None:
                req_kwargs["timeout"] = req_timeout
            # Forward per-request headers (Accept for GraphQL JSON endpoints,
            # Content-Type + Origin/Referer for LupaSearch POSTs that reject
            # naked text/html browser headers).
            forwarded_headers: dict[str, str] = {}
            for header_name in ("Accept", "Content-Type", "Origin", "Referer"):
                raw = request.headers.get(header_name)
                if raw is None:
                    continue
                forwarded_headers[header_name] = (
                    raw.decode() if isinstance(raw, bytes) else raw
                )
            if forwarded_headers:
                req_kwargs["headers"] = forwarded_headers

            method = (request.method or "GET").upper()
            status_code: int | None = None
            try:
                if method == "POST":
                    # POST endpoints (e.g. LupaSearch) carry their filter
                    # payload in the body — sending GET silently strips it
                    # and the endpoint returns the unfiltered catalog.
                    response = await asyncio.wait_for(
                        self.client.post(
                            str(request.url),
                            content=request.body or b"",
                            **req_kwargs,
                        ),
                        timeout=hard_timeout,
                    )
                else:
                    response = await asyncio.wait_for(
                        self.client.get(str(request.url), **req_kwargs),
                        timeout=hard_timeout,
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
        for old in self._retired_clients:
            try:
                await old.aclose()
            except Exception:
                logger.exception("httpx retired client aclose failed")
        self._retired_clients.clear()
