"""Downloader middleware that routes requests through a FlareSolverr sidecar.

For shops gated by Cloudflare's Managed Challenge / Turnstile that
actively rejects automated browsers (verified on humanitas.lt with
patchright + real Brave: empty cookie jar, error variant of the
challenge page), neither httpx + TLS impersonation nor stealth-patched
Playwright will mint a `cf_clearance`. FlareSolverr runs a patched
Chromium in Docker that solves the challenge and returns the rendered
HTML + clearance cookie via a JSON RPC endpoint.

When a shop's TOML has a `[flaresolverr]` block, this middleware short-
circuits the downloader and POSTs to the configured endpoint. When the
block is absent it returns ``None``, falling through to whatever lower-
priority middleware handles the request (in this project,
``HttpxMiddleware``).

Layering note: this middleware is registered at priority 0 (one below
``HttpxMiddleware`` at priority 1) so its ``process_request`` runs
first and can short-circuit before httpx is consulted.
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


class FlaresolverrMiddleware:  # pragma: no cover
    """Route requests through a FlareSolverr sidecar when the shop opts in."""

    def __init__(self, crawler: Crawler):
        self._crawler = crawler
        # Per-spider FS state, populated in spider_opened only when the
        # shop's TOML has a `[flaresolverr]` block. None ⇒ middleware is
        # a no-op for the active spider.
        self._fs_endpoint: str | None = None
        self._fs_session_id: str | None = None
        self._fs_session_started: float = 0.0
        self._fs_session_ttl_s: float = 25 * 60.0
        self._fs_max_timeout_ms: int = 120_000
        # Reused HTTP client for all FS RPC calls. Long timeout because
        # the FS POST waits for the browser to finish rendering.
        self._client: httpx.AsyncClient | None = None
        # Per-host pacing — FS itself is the bottleneck (1–3 s per
        # request) but we still cap concurrency / impose a delay to
        # mirror HttpxMiddleware's behaviour for the rest of the
        # pipeline (status flip, hard timeout, etc.).
        self._max_concurrency: int = 1
        self._download_delay: float = 0.5
        self._host_slots: dict[str, asyncio.Semaphore] = {}
        self._host_dispatch_locks: dict[str, asyncio.Lock] = {}
        self._host_last_dispatch: dict[str, float] = {}
        self._session_lock = asyncio.Lock()

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "FlaresolverrMiddleware":
        mw = cls(crawler)
        crawler.signals.connect(mw.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(mw.spider_closed, signal=signals.spider_closed)
        return mw

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def spider_opened(self, spider: Any) -> None:
        fs_conf = self._fs_conf_from_spider(spider)
        if fs_conf is None:
            return
        self._fs_endpoint = fs_conf.endpoint
        self._fs_max_timeout_ms = int(fs_conf.max_timeout_ms)
        self._fs_session_ttl_s = max(60.0, float(fs_conf.session_ttl_minutes) * 60.0)
        # Pacing inputs: prefer the shop's [scraping] block — same
        # precedence chain HttpxMiddleware uses but without the DB
        # override (FS pacing is mostly a politeness floor; ops can
        # still tweak via direct shop_settings rows if needed later).
        scraping = getattr(getattr(spider, "conf", None), "scraping", None)
        if scraping is not None:
            self._download_delay = max(0.0, float(scraping.download_delay))
            self._max_concurrency = max(
                1, int(scraping.concurrent_requests_per_domain)
            )
        # Long client timeout — FS's POST blocks until the browser
        # finishes the navigation; CF challenge solves are routinely
        # 5–10 s and ramp to 30+ s under load.
        self._client = httpx.AsyncClient(timeout=self._fs_max_timeout_ms / 1000.0 + 30)
        logger.info(
            "FlaresolverrMiddleware: enabled for %s endpoint=%s "
            "max_timeout_ms=%d ttl=%.0fs",
            getattr(spider, "shop_name", "?"),
            self._fs_endpoint,
            self._fs_max_timeout_ms,
            self._fs_session_ttl_s,
        )

    async def spider_closed(self, spider: Any) -> None:
        if self._fs_endpoint is None:
            return
        # Best-effort: destroy the FS browser session so the sidecar
        # doesn't leak a Chromium tab if the spider is rerun rapidly.
        if self._fs_session_id and self._client is not None:
            try:
                await self._client.post(
                    self._fs_endpoint,
                    json={
                        "cmd": "sessions.destroy",
                        "session": self._fs_session_id,
                    },
                )
            except Exception:
                logger.exception("FS session destroy failed")
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._fs_endpoint = None
        self._fs_session_id = None

    # ------------------------------------------------------------------
    # Per-request entry point
    # ------------------------------------------------------------------
    async def process_request(
        self, request: Request, spider: Any = None
    ) -> HtmlResponse | None:
        if self._fs_endpoint is None or self._client is None:
            # Shop didn't opt in — let lower-priority middlewares handle it.
            return None

        host = self._host_key(str(request.url))
        slot, dispatch_lock = self._get_slot(host)
        async with slot:
            async with dispatch_lock:
                last = self._host_last_dispatch.get(host, 0.0)
                now_mono = time.monotonic()
                sleep_for = max(0.0, last + self._download_delay - now_mono)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                dispatched_at = time.time()
                dispatched_mono = time.monotonic()
                self._host_last_dispatch[host] = dispatched_mono

                request.meta["dispatched_at"] = dispatched_at
                request.meta["request_delay_s"] = sleep_for
                request.meta["delay_source"] = "flaresolverr"

                item_id = request.meta.get("scrape_url_item_id")
                if item_id is not None:
                    self._mark_processing(item_id, dispatched_at, sleep_for)

            return await self._fetch_via_flaresolverr(request)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _fs_conf_from_spider(spider: Any) -> Any:
        conf = getattr(spider, "conf", None)
        if conf is None:
            return None
        return getattr(conf, "flaresolverr", None)

    def _host_key(self, url: str) -> str:
        host = urlparse(url).hostname
        return host or "default"

    def _get_slot(self, host: str) -> tuple[asyncio.Semaphore, asyncio.Lock]:
        slot = self._host_slots.get(host)
        if slot is None:
            slot = asyncio.Semaphore(self._max_concurrency)
            self._host_slots[host] = slot
            self._host_dispatch_locks[host] = asyncio.Lock()
        return slot, self._host_dispatch_locks[host]

    def _mark_processing(
        self, item_id: int, dispatched_at: float, request_delay_s: float
    ) -> None:
        """Best-effort flip scrape_url_items.status to 'processing'.

        Mirrors HttpxMiddleware. Failure here must not stop the request.
        """
        s = self._crawler.settings if self._crawler else None
        database_url = s.get("DATABASE_URL") if s else None
        if not database_url:
            return
        try:
            from book_scraper.db.repo import mark_scrape_url_item_processing
            from book_scraper.db.session import get_session_factory

            session = get_session_factory(database_url)()
            try:
                mark_scrape_url_item_processing(
                    session,
                    item_id,
                    dispatched_at,
                    request_delay_s=request_delay_s,
                    delay_source="flaresolverr",
                )
                session.commit()
            finally:
                session.close()
        except Exception:
            logger.exception("FS mark_processing failed for item %d", item_id)

    # Pre-rotation buffer: kick off a fresh sessions.create this many
    # seconds *before* the existing session would actually expire. The
    # new session creation costs a CF challenge solve (~10–15 s), so
    # we want it ready by the time the old one is no longer trusted.
    # If multiple coroutines hit `_ensure_session` while a rotation is
    # already mid-flight, they reuse the still-valid old session ID
    # and don't pile up on the lock.
    _PRE_ROTATION_BUFFER_S: float = 90.0

    async def _ensure_session(self) -> str:
        """Return a usable FS session ID, rotating ahead of TTL when due.

        Sessions are reused across requests so the persistent CF
        clearance cookie sticks (FlareSolverr keeps the cookie jar
        attached to the session). The cookie wall is ~30 min on
        Cloudflare's side, so we destroy + recreate before that — see
        ``session_ttl_minutes`` in the shop TOML.

        Pre-rotation: when a request lands in the last
        ``_PRE_ROTATION_BUFFER_S`` of the TTL window, it triggers a
        background ``sessions.create`` (under the lock) but keeps
        using the old session ID until the new one is actually ready.
        That means the only request that pays the ~12 s rotation cost
        is the one that triggered it; in-flight peers continue on the
        old session.
        """
        async with self._session_lock:
            now = time.monotonic()
            age = now - self._fs_session_started if self._fs_session_id else None

            # Healthy path: session exists and is well within TTL.
            if (
                self._fs_session_id
                and age is not None
                and age < self._fs_session_ttl_s - self._PRE_ROTATION_BUFFER_S
            ):
                return self._fs_session_id

            client = self._client
            assert client is not None
            assert self._fs_endpoint is not None

            # Cold start path: no session yet → blocking create.
            if self._fs_session_id is None:
                return await self._create_session_locked(now)

            # Pre-rotation path: session still usable (within TTL), but
            # we're inside the buffer window. Mint a replacement and
            # only swap once it's ready, so concurrent peers keep
            # using the old ID. The old session is destroyed AFTER
            # the swap, fire-and-forget, so a request mid-flight on
            # the old session can finish.
            if age is not None and age < self._fs_session_ttl_s:
                old_id = self._fs_session_id
                try:
                    new_id = await self._create_session_locked(now)
                except Exception:
                    logger.exception(
                        "FS pre-rotation create failed; staying on old session"
                    )
                    return old_id
                # Best-effort old-session teardown (don't block the
                # caller on the destroy round trip).
                try:
                    await client.post(
                        self._fs_endpoint,
                        json={"cmd": "sessions.destroy", "session": old_id},
                    )
                except Exception:
                    logger.exception(
                        "FS pre-rotation: destroy of old session failed"
                    )
                return new_id

            # Hard expiry path: old session is past TTL, can't trust
            # it — destroy first, then create.
            try:
                await client.post(
                    self._fs_endpoint,
                    json={
                        "cmd": "sessions.destroy",
                        "session": self._fs_session_id,
                    },
                )
            except Exception:
                logger.exception(
                    "FS post-expiry: destroy of stale session failed (continuing)"
                )
            return await self._create_session_locked(now)

    async def _create_session_locked(self, now: float) -> str:
        """Mint a new FS session and store it. Caller must hold the lock."""
        client = self._client
        assert client is not None
        assert self._fs_endpoint is not None
        resp = await client.post(
            self._fs_endpoint, json={"cmd": "sessions.create"}
        )
        resp.raise_for_status()
        data = resp.json()
        session_id_raw = data.get("session")
        if not session_id_raw or not isinstance(session_id_raw, str):
            raise RuntimeError(f"FS sessions.create returned: {data}")
        session_id_str: str = session_id_raw
        self._fs_session_id = session_id_str
        self._fs_session_started = now
        logger.info("FlaresolverrMiddleware: session=%s", session_id_str)
        return session_id_str

    async def _fetch_via_flaresolverr(self, request: Request) -> HtmlResponse:
        client = self._client
        assert client is not None
        assert self._fs_endpoint is not None
        session_id = await self._ensure_session()

        method = (request.method or "GET").upper()
        body: dict[str, Any] = {
            "cmd": "request.get" if method == "GET" else "request.post",
            "url": str(request.url),
            "session": session_id,
            "maxTimeout": self._fs_max_timeout_ms,
        }
        if method == "POST":
            body["postData"] = (
                request.body.decode("utf-8") if isinstance(request.body, bytes)
                else (request.body or "")
            )

        try:
            r = await client.post(self._fs_endpoint, json=body)
        except httpx.TimeoutException:
            logger.warning("FlareSolverr timeout for %s", request.url)
            raise
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "ok":
            # FS itself failed (challenge unsolvable, browser crashed, …).
            # Surface as a 502 so RetryMiddleware picks it up.
            msg = data.get("message", "FlareSolverr error")
            logger.warning("FlareSolverr error for %s: %s", request.url, msg)
            return HtmlResponse(
                url=str(request.url),
                status=502,
                headers={"X-FlareSolverr-Error": msg},
                body=msg.encode("utf-8"),
                request=request,
                encoding="utf-8",
            )

        sol = data.get("solution") or {}
        body_str: str = sol.get("response") or ""
        status = int(sol.get("status") or 200)
        # Headers come back as a list of {name,value}. Normalise to a
        # dict the way HttpxMiddleware does. Strip Content-Encoding —
        # FlareSolverr already returns decoded HTML, and Scrapy's
        # decompression middleware would otherwise try to decode it
        # again.
        headers: dict[str, str] = {}
        raw_headers = sol.get("headers")
        if isinstance(raw_headers, list):
            for h in raw_headers:
                name = (h.get("name") or "").strip()
                if not name:
                    continue
                if name.lower() == "content-encoding":
                    continue
                headers[name] = h.get("value", "")
        return HtmlResponse(
            url=sol.get("url") or str(request.url),
            status=status,
            headers=headers,
            body=body_str.encode("utf-8"),
            request=request,
            encoding="utf-8",
        )
