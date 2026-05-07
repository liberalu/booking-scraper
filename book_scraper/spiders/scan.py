import contextlib
import time
from collections.abc import AsyncGenerator, Generator
from typing import Any

import scrapy
from scrapy import signals
from sqlalchemy.orm import Session

from book_scraper.config import load_shop_config
from book_scraper.db.repo import (
    get_pending_scrape_url_items,
    increment_scrape_run_stats,
    mark_scrape_url_item_response,
    reset_processing_scrape_url_items,
    update_scrape_run_progress,
)
from book_scraper.db.session import get_session_factory
from book_scraper.event_log import log_response_event
from book_scraper.items import ShopBookItem
from book_scraper.services.scan import ScanService
from book_scraper.spiders.registry import load_parsers

# Anti-bot challenge / wall fingerprints. A 200 OK response whose body
# matches one of these is treated as a failed fetch (`error_reason =
# 'anti_bot_detected'`, severity=critical) instead of a "successful"
# scrape that produces garbage data downstream. Matching is a cheap
# case-insensitive substring scan on the body — patterns are short,
# distinctive, and chosen to avoid collisions with legitimate prose.
ANTI_BOT_MARKERS: tuple[str, ...] = (
    # Cloudflare challenge / Bot Fight Mode
    "just a moment...",
    "luktelėkite",  # Lithuanian "Just a moment…" used by humanitas.lt
    "checking your browser before accessing",
    "cf-browser-verification",
    # Tighter than just "challenge-platform": that substring also
    # appears in the legitimate post-clearance beacon CF injects
    # (`cdn-cgi/challenge-platform/scripts/jsd/main.js`) on every
    # protected page once the visitor has cleared. The orchestrator
    # path below only renders on the interstitial itself.
    "challenge-platform/h/g/orchestrate/chl_page",
    # Akamai
    "pardon our interruption",
    # Datadome
    "datadome",
    "captcha-delivery",
    # Generic CAPTCHA / verification walls
    "are you a human",
    "verify you are not a robot",
)


def _is_anti_bot_response(text: str) -> bool:
    """True if the response body matches a known anti-bot wall."""
    if not text:
        return False
    lower = text.lower()
    return any(m in lower for m in ANTI_BOT_MARKERS)


class ScanSpider(scrapy.Spider):
    name = "scan"

    def __init__(
        self,
        shop: str | None = None,
        rescrape: str = "false",
        urls: str = "",
        max_urls: str | int = "",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        if not shop:
            raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
        self.shop_name = shop
        self._rescrape = rescrape.lower() in ("true", "1", "yes")
        self._single_urls = [u.strip() for u in urls.split(",") if u.strip()]
        # Hard cap for dev / sanity runs. 0 or empty means "no cap".
        self._max_urls: int = int(max_urls) if str(max_urls).strip() else 0
        self.conf = load_shop_config(shop)
        self.parsers = load_parsers(shop)
        self.allowed_domains = [
            self.conf.shop.base_url.replace("https://", "").replace("http://", "")
        ]

        self._run_id: int | None = None
        self._urls_processed: int = 0
        self._urls_responded: int = 0
        self._url_status_updates: list[dict[str, Any]] = []
        self._progress_session: Session | None = None
        self._progress_service: ScanService | None = None

        # Defence-in-depth heartbeat: `update_scrape_run_progress` (called
        # from `_flush_progress` every `_flush_every` responses) also stamps
        # `last_heartbeat`. Kept low enough that even a slow crawl (~5
        # responses/min) flushes within the dashboard reaper threshold
        # (`DEAD_RUN_SECONDS = 60`). HeartbeatExtension is the primary
        # source of liveness signals; this is just a backup.
        self._flush_every: int = 10
        self._errors_4xx: int = 0
        self._errors_5xx: int = 0
        self._error_count: int = 0

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):  # type: ignore[no-untyped-def]
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_idle, signal=signals.spider_idle)
        return spider

    def spider_idle(self, spider) -> None:  # type: ignore[no-untyped-def]
        """When the main queue drains, check for new items queued mid-run
        and schedule them. Called by Scrapy when no requests are in flight.

        Hooks into Scrapy's ``spider_idle`` signal to pick up items enqueued
        mid-run via ``ScanService.enqueue_new_url``. Currently no code path
        emits such enqueues during a scan run; this handler remains inert
        until Phase 2 wires the scan spider to yield ``DiscoveredUrlItem``
        for newly-discovered product URLs.
        """
        if self._run_id is None:
            return
        database_url = self.settings.get("DATABASE_URL")
        session_factory = get_session_factory(database_url)
        session = session_factory()
        try:
            reset_processing_scrape_url_items(session, self._run_id)
            new_items = get_pending_scrape_url_items(session, self._run_id)
            session.commit()
        finally:
            session.close()

        if not new_items:
            return

        from scrapy.exceptions import DontCloseSpider

        engine = self.crawler.engine
        assert engine is not None
        for item in new_items:
            req = self._build_scan_request(
                item["url"],
                meta={
                    "discovered_url_id": item["discovered_url_id"],
                    "scrape_url_item_id": item["id"],
                    "scheduled_at": time.monotonic(),
                },
            )
            engine.crawl(req)
        raise DontCloseSpider

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        # Apply max_urls cap to single-URL mode too — keeps the flag
        # consistent regardless of how URLs are supplied.
        if self._max_urls and self._single_urls:
            self._single_urls = self._single_urls[: self._max_urls]
        # Single-URL mode: create a run but skip full scan plan
        if self._single_urls:
            database_url = self.settings.get("DATABASE_URL")
            session_factory = get_session_factory(database_url)
            session = session_factory()
            url_id_map: dict[str, int | None] = {}
            url_item_id_map: dict[str, int] = {}
            try:
                from book_scraper.db.models import DiscoveredUrl
                from book_scraper.db.repo import (
                    create_scrape_run,
                    insert_scrape_url_item,
                    upsert_shop,
                )

                shop = upsert_shop(session, self.shop_name, self.conf.shop.base_url)
                run = create_scrape_run(
                    session,
                    shop.id,
                    "scan",
                    urls_total=len(self._single_urls),
                    extra_payload={
                        "mode": "single_urls",
                        "urls": list(self._single_urls),
                    },
                )
                session.commit()
                self._run_id = run.id

                for url in self._single_urls:
                    du = (
                        session.query(DiscoveredUrl)
                        .filter_by(url=url, shop_id=shop.id)
                        .one_or_none()
                    )
                    url_id_map[url] = du.id if du else None
                    # Upsert a scrape_url_items row so the live view
                    # has something to render for these runs (the
                    # dashboard's "rescrape this URL" buttons land here).
                    item = insert_scrape_url_item(
                        session,
                        run_id=run.id,
                        shop_id=shop.id,
                        discovered_url_id=du.id if du else None,
                        url=url,
                    )
                    url_item_id_map[url] = item.id
                session.commit()
            finally:
                session.close()

            # HeartbeatExtension picks up `_run_id` lazily on its next
            # spider_opened-driven tick — no explicit handshake needed.

            self.logger.info(
                "Single-URL mode: scraping %d URLs (run #%d)",
                len(self._single_urls),
                self._run_id,
            )
            for url in self._single_urls:
                yield self._build_scan_request(
                    url,
                    meta={
                        "discovered_url_id": url_id_map.get(url),
                        "scrape_url_item_id": url_item_id_map.get(url),
                        "scheduled_at": time.monotonic(),
                    },
                )
            return

        database_url = self.settings.get("DATABASE_URL")
        session_factory = get_session_factory(database_url)
        session = session_factory()

        try:
            service = ScanService(session)
            # Phase 1: lock + create run row. Fast: a few SELECTs and a
            # single INSERT. Returns either a fresh plan (queue not yet
            # populated) or a resumable plan (queue already there).
            plan = service.prepare_scan_create_run(
                self.shop_name,
                self.conf.shop.base_url,
                self.conf,
                rescrape=self._rescrape,
            )
            if plan.lock_not_acquired:
                self.logger.warning(
                    "Another scan run is already active for shop=%s; exiting "
                    "cleanly. Use the dashboard to inspect the running run.",
                    self.shop_name,
                )
                return
            self._run_id = plan.run_id

            for warning in plan.freshness_warnings:
                self.logger.warning(warning)

            # HeartbeatExtension's tick loop (started at spider_opened)
            # reads `self._run_id` lazily on each fire, so a slow
            # `populate_scan_queue` does not leave `last_heartbeat`
            # frozen at row-creation time while the reaper threshold
            # ticks past — the next tick after the row is created
            # picks it up.

            # Phase 2: populate (or inherit) the queue.
            service.populate_scan_queue(plan)

            # Load work queue from DB (supports crash-resume)
            reset_processing_scrape_url_items(session, plan.run_id)
            url_items = get_pending_scrape_url_items(session, plan.run_id)
            session.commit()

            if self._max_urls and len(url_items) > self._max_urls:
                self.logger.info(
                    "max_urls cap: scraping %d of %d planned URLs",
                    self._max_urls,
                    len(url_items),
                )
                url_items = url_items[: self._max_urls]

            total = len(url_items)
            self.logger.info(
                "Scan starting: %d URLs (%d skipped). Pacing via Scrapy "
                "CONCURRENT_REQUESTS_PER_DOMAIN + DOWNLOAD_DELAY + AUTOTHROTTLE.",
                total,
                plan.urls_skipped,
            )

            for url_item in url_items:
                # Pause/resume: poll status before each dispatch.
                # If 'paused', sleep in 5s increments until resumed or
                # stopped. 'stopping' exits the loop immediately.
                if self._run_id is not None:
                    import asyncio

                    while True:
                        run_status = self._poll_run_status()
                        if run_status == "paused":
                            self.logger.debug(
                                "Run %d paused — waiting 5s", self._run_id
                            )
                            self._touch_heartbeat()
                            await asyncio.sleep(5)
                            continue
                        if run_status == "stopping":
                            self.logger.info(
                                "Run %d stopping — exiting queue loop",
                                self._run_id,
                            )
                            return
                        break
                yield self._build_scan_request(
                    url_item["url"],
                    meta={
                        "discovered_url_id": url_item["discovered_url_id"],
                        "scrape_url_item_id": url_item["id"],
                        "scheduled_at": time.monotonic(),
                    },
                )
        finally:
            session.close()

    def _build_scan_request(self, url: str, meta: dict[str, Any]) -> scrapy.Request:
        """Build a scan request, honouring the parser's `rewrite_scan_url` hook.

        Pegasas's PWA serves React shells with no parseable data, so its
        parser swaps the product URL for a single-SKU GraphQL request.
        For shops without the hook (vaga), the URL passes through.
        Stashes the original URL in ``meta["original_url"]`` so
        downstream tracking (scrape_url_items, ShopBookItem.url, redirect
        detection) can still reference the canonical product page.
        """
        rewrite = getattr(self.parsers, "rewrite_scan_url", None)
        request_url = url
        request_headers: dict[str, str] | None = None
        meta = dict(meta)
        meta["original_url"] = url
        if rewrite is not None:
            rewritten = rewrite(url)
            if rewritten:
                request_url = rewritten["url"]
                request_headers = rewritten.get("headers") or None
        return scrapy.Request(
            request_url,
            callback=self.parse_product,
            errback=self.handle_error,
            meta=meta,
            headers=request_headers,
        )

    def parse_product(
        self, response: scrapy.http.Response
    ) -> Generator[ShopBookItem, None, None]:
        discovered_url_id = response.meta.get("discovered_url_id")
        scrape_url_item_id = response.meta.get("scrape_url_item_id")
        dispatched_at = response.meta.get("dispatched_at")
        request_delay_s = response.meta.get("request_delay_s")
        delay_source = response.meta.get("delay_source")
        received_at = time.time()
        response_bytes = len(response.body) if response.body is not None else 0

        # When `rewrite_scan_url` swapped the URL (e.g. pegasas → /graphql),
        # the response.url is the GraphQL endpoint. Use the stashed original
        # URL so tracking columns + items reflect the canonical product page.
        original_url = response.meta.get("original_url")
        url = original_url or response.url.split("?")[0]
        # RetryMiddleware bumps `retry_times` on each retry; surface it
        # in the queue row so postmortem queries can see how often
        # transient backend pressure was papered over by retries.
        retry_count = int(response.meta.get("retry_times", 0))
        if 400 <= response.status < 600:
            if response.status < 500:
                self._errors_4xx += 1
            else:
                self._errors_5xx += 1
            self._error_count += 1
            # Transport errors are recorded only in scrape_failures (PR 1
            # of the migration; PR 3 stops the validation_issues
            # double-write — single source of truth for failure events).
            self._mark_response(
                scrape_url_item_id,
                response_url=url,
                success=False,
                http_status=response.status,
                received_at=received_at,
                response_bytes=response_bytes,
                error_reason=f"http_{response.status}",
                dispatched_at=dispatched_at,
                request_delay_s=request_delay_s,
                delay_source=delay_source,
                retry_count=retry_count,
            )
            self._queue_url_status_update(
                discovered_url_id,
                http_status=response.status,
                increment_fail=True,
            )
            return

        # HTTP-level checks
        # (url already resolved above to original_url when rewrite was applied)
        # Anti-bot wall check fires before any content-quality signal:
        # a 200 OK challenge page would otherwise trip empty_response /
        # redirect_to_homepage as warnings while still being parsed for
        # garbage data. Treat as a real failure with critical severity.
        if _is_anti_bot_response(response.text):
            self._error_count += 1
            self._mark_response(
                scrape_url_item_id,
                response_url=url,
                success=False,
                http_status=response.status,
                received_at=received_at,
                response_bytes=response_bytes,
                error_reason="anti_bot_detected",
                dispatched_at=dispatched_at,
                request_delay_s=request_delay_s,
                delay_source=delay_source,
                retry_count=retry_count,
            )
            self._queue_url_status_update(
                discovered_url_id,
                http_status=response.status,
                increment_fail=True,
            )
            return
        if len(response.text) < 1024:
            self._report_validation(
                "empty_response",
                "response",
                url,
                f"len={len(response.text)}",
            )
        # Skip redirect-to-homepage detection when rewrite_scan_url was
        # applied: the response.url is the GraphQL endpoint by design,
        # not a redirected product page, so the check would fire
        # spuriously on every pegasas request.
        if original_url is None:
            request_url = (
                response.request.url.split("?")[0] if response.request else url
            )
            final_url = url
            if final_url != request_url:
                # Check if redirected to homepage or category
                base = self.conf.shop.base_url.rstrip("/")
                path = final_url.replace(base, "")
                if path in ("", "/") or path.count("/") == 1:
                    self._report_validation(
                        "redirect_to_homepage",
                        "url",
                        request_url,
                        f"redirected to {final_url}",
                    )

        data = self.parsers.parse_product_page(response.text)

        if not data.get("is_book_product"):
            # Page fetched + parsed successfully; the parser just classified
            # it as not a book (category page, author listing, etc.). That's
            # a successful scrape outcome, not a failure — record as `done`
            # with url_type=non_product and no error_reason.
            self._mark_response(
                scrape_url_item_id,
                response_url=url,
                success=True,
                http_status=200,
                received_at=received_at,
                response_bytes=response_bytes,
                error_reason=None,
                dispatched_at=dispatched_at,
                url_type="non_product",
                request_delay_s=request_delay_s,
                delay_source=delay_source,
                retry_count=retry_count,
            )
            self._queue_url_status_update(
                discovered_url_id,
                http_status=200,
                url_type="non_product",
                book_score=data.get("book_score", 0),
                is_book_product=False,
                book_score_reasons=data.get("book_score_reasons", []),
            )
            return

        # Build properties dict from format-specific fields. Merge in
        # the parser-supplied `properties` dict first so shop-specific
        # extras (e.g. humanitas's `language` from `Leidinio kalba`,
        # pegasas's `dimensions`/`ean`/`is_new`/`discount_rate`) survive
        # into shop_book_attributes — without this, anything outside
        # the five hardcoded top-level keys was silently dropped during
        # scan-side ingestion. Discover already had the correct merge;
        # this brings scan to parity.
        props: dict[str, object] = {}
        parser_props = data.get("properties")
        if isinstance(parser_props, dict):
            props.update(parser_props)
        for key in ("pages", "cover_type", "duration", "narrator", "translator"):
            if data.get(key) is not None and key not in props:
                props[key] = data[key]

        item = ShopBookItem(
            url=url,
            shop_name=self.shop_name,
            type=data.get("type"),
            title=data["title"],
            author=data.get("author"),
            sku=data.get("sku"),
            isbn=data.get("isbn"),
            publisher=data.get("publisher"),
            year=data.get("year"),
            format=data.get("format"),
            description=data.get("description"),
            image_url=data.get("image_url"),
            categories=data.get("categories", []),
            properties=props or None,
            price=data.get("price"),
            price_original=data.get("price_original"),
            in_stock=data.get("in_stock"),
            planned_availability_date=data.get("planned_availability_date"),
            rating=data.get("rating"),
            review_count=data.get("review_count"),
        )

        # Mark URL as successfully scraped
        self._mark_response(
            scrape_url_item_id,
            response_url=url,
            success=True,
            http_status=200,
            received_at=received_at,
            response_bytes=response_bytes,
            error_reason=None,
            dispatched_at=dispatched_at,
            url_type="product",
            request_delay_s=request_delay_s,
            delay_source=delay_source,
            retry_count=retry_count,
        )
        self._queue_url_status_update(
            discovered_url_id,
            http_status=200,
            url_type="product",
            book_score=data.get("book_score", 0),
            is_book_product=True,
            book_score_reasons=data.get("book_score_reasons", []),
        )

        self._urls_processed += 1
        yield item

    def handle_error(self, failure: Any) -> None:
        """Handle request failures (timeouts, connection errors)."""
        request = failure.request
        discovered_url_id = request.meta.get("discovered_url_id")
        scrape_url_item_id = request.meta.get("scrape_url_item_id")
        dispatched_at = request.meta.get("dispatched_at")
        request_delay_s = request.meta.get("request_delay_s")
        delay_source = request.meta.get("delay_source")
        received_at = time.time()
        # Use original URL when rewrite_scan_url was applied so tracking
        # columns reference the product page, not the GraphQL endpoint.
        original_url = request.meta.get("original_url")
        url = original_url or str(request.url).split("?")[0]
        retry_count = int(request.meta.get("retry_times", 0))

        status = getattr(failure.value, "response", None)
        http_status = status.status if status else None

        # Transport errors land only in scrape_failures (PR 3 of the
        # migration). The validation_issues counterparts were duplicates.
        if http_status and 400 <= http_status < 500:
            self._errors_4xx += 1
            error_reason = f"http_{http_status}"
        elif http_status and 500 <= http_status < 600:
            self._errors_5xx += 1
            error_reason = f"http_{http_status}"
        else:
            error_type = type(failure.value).__name__
            error_reason = f"request_error:{error_type}"
        self._error_count += 1

        self._mark_response(
            scrape_url_item_id,
            response_url=url,
            success=False,
            http_status=http_status,
            received_at=received_at,
            response_bytes=None,
            error_reason=error_reason,
            dispatched_at=dispatched_at,
            request_delay_s=request_delay_s,
            delay_source=delay_source,
            retry_count=retry_count,
        )
        self._queue_url_status_update(
            discovered_url_id,
            http_status=http_status,
            increment_fail=True,
        )

    def _report_validation(
        self,
        issue: str,
        field: str,
        url: str,
        raw_value: str = "",
    ) -> None:
        """Report a validation issue to the ValidationPipeline."""
        crawler = getattr(self, "crawler", None)
        vp = getattr(crawler, "validation_pipeline", None) if crawler else None
        if vp is not None:
            vp._warn(issue, field, url, raw_value)
        else:
            self.logger.warning(
                "Validation [%s] field=%s url=%s %s",
                issue,
                field,
                url,
                raw_value,
            )

    def _mark_response(
        self,
        scrape_url_item_id: int | None,
        *,
        response_url: str,
        success: bool,
        http_status: int | None,
        received_at: float,
        response_bytes: int | None,
        error_reason: str | None,
        dispatched_at: float | None,
        url_type: str | None = None,
        request_delay_s: float | None = None,
        delay_source: str | None = None,
        retry_count: int = 0,
    ) -> None:
        """Immediate per-response write to scrape_url_items + JSONL event.

        Owns terminal state for the row (status, done_at, http_status,
        error_reason, response_bytes) per the live observability spec.
        The batched flush no longer touches these columns.

        Fresh DB session per call: short-lived, sub-10ms, mirrors the
        pattern in HttpxMiddleware._mark_processing.
        """
        duration_ms: int | None = None
        if dispatched_at is not None:
            duration_ms = max(0, int((received_at - dispatched_at) * 1000))
        if scrape_url_item_id is not None:
            database_url = self.settings.get("DATABASE_URL")
            session_factory = get_session_factory(database_url)
            session = session_factory()
            try:
                mark_scrape_url_item_response(
                    session,
                    scrape_url_item_id,
                    success=success,
                    http_status=http_status,
                    received_at=received_at,
                    response_bytes=response_bytes,
                    error_reason=error_reason,
                    url_type=url_type,
                    retry_count=retry_count,
                )
                session.commit()
            except Exception:
                self.logger.exception(
                    "mark_response failed for item %d", scrape_url_item_id
                )
            finally:
                session.close()
        # JSONL event log (best-effort, never raises).
        in_flight = self._current_in_flight()
        log_response_event(
            run_id=self._run_id,
            url=response_url,
            status=http_status,
            duration_ms=duration_ms,
            request_delay_s=request_delay_s,
            delay_source=delay_source,
            retry_count=retry_count,
            in_flight=in_flight,
            bytes_=response_bytes,
            error_reason=error_reason,
        )

    def _touch_heartbeat(self) -> None:
        """Stamp last_heartbeat while paused so the reaper won't kill the run."""
        if self._run_id is None:
            return
        database_url = self.settings.get("DATABASE_URL")
        session_factory = get_session_factory(database_url)
        session = session_factory()
        try:
            update_scrape_run_progress(session, self._run_id, self._urls_processed)
            session.commit()
        except Exception:
            self.logger.exception("Heartbeat touch failed for run %d", self._run_id)
        finally:
            session.close()

    def _poll_run_status(self) -> str | None:
        """Read `scrape_runs.status` for the current run.

        Called before each request dispatch to detect pause/stop
        transitions. Returns the current status string or None if the
        run row vanished or the query fails.
        """
        if self._run_id is None:
            return None
        from sqlalchemy import text as sa_text

        database_url = self.settings.get("DATABASE_URL")
        session_factory = get_session_factory(database_url)
        session = session_factory()
        try:
            result = session.execute(
                sa_text("SELECT status FROM scrape_runs WHERE id = :run_id"),
                {"run_id": self._run_id},
            ).scalar()
            return str(result) if result is not None else None
        except Exception:
            self.logger.exception("Status poll failed for run %d", self._run_id)
            return None
        finally:
            session.close()

    def _current_in_flight(self) -> int | None:
        """Count of in-flight requests via Scrapy's engine slots.

        Reads the `active` set on each Slot — populated by the engine
        as requests are dispatched. Best-effort: returns None if the
        engine is missing or the API shifts in a future Scrapy version.
        """
        try:
            engine = self.crawler.engine
            if engine is None:
                return None
            total = 0
            for slot in engine.downloader.slots.values():
                total += len(getattr(slot, "active", ()))
            return total
        except Exception:
            return None

    def _queue_url_status_update(
        self,
        url_id: int | None,
        http_status: int | None = None,
        url_type: str | None = None,
        increment_fail: bool = False,
        book_score: int | None = None,
        is_book_product: bool | None = None,
        book_score_reasons: list[str] | None = None,
    ) -> None:
        """Queue a discovered_urls + classification update for the batch.

        Per the live observability spec, scrape_url_items terminal state
        is no longer routed through here — the spider's `_mark_response`
        writes that immediately. This batch path now only touches
        `discovered_urls` and `url_classifications`.
        """
        if url_id is None:
            return
        update: dict[str, Any] = {
            "url_id": url_id,
            "http_status": http_status,
            "url_type": url_type,
            "increment_fail": increment_fail,
        }
        if book_score is not None and is_book_product is not None:
            update["book_score"] = book_score
            update["is_book_product"] = is_book_product
            update["book_score_reasons"] = book_score_reasons or []
        self._url_status_updates.append(update)
        self._urls_responded += 1
        if self._urls_responded % self._flush_every == 0:
            self._flush_progress()

    def _flush_progress(self) -> None:
        """Flush queued URL status updates and progress to DB."""
        if self._run_id is None or not self._url_status_updates:
            return

        if self._progress_session is None:
            database_url = self.settings.get("DATABASE_URL")
            session_factory = get_session_factory(database_url)
            self._progress_session = session_factory()
            self._progress_service = ScanService(self._progress_session)

        assert self._progress_service is not None
        self._progress_service.flush_progress(
            self._run_id,
            self._urls_processed,
            self._url_status_updates,
        )
        self._url_status_updates = []
        self.logger.info(
            "Flushed progress: %d URLs processed, %d total responded",
            self._urls_processed,
            self._urls_responded,
        )

    def closed(self, reason: str) -> None:
        """Finalize scrape_run on spider close.

        Tries the long-lived progress session first (carries pending URL
        status updates and stats). If it errors — typically a poisoned
        session after an earlier failed query — falls back to a fresh-
        session failsafe finalize so the run row is never left zombie.
        """
        if self._run_id is None:
            return

        database_url = self.settings.get("DATABASE_URL")
        finalized = False

        try:
            if self._progress_session is None:
                session_factory = get_session_factory(database_url)
                self._progress_session = session_factory()
                self._progress_service = ScanService(self._progress_session)

            assert self._progress_service is not None
            self._progress_service.finish_scan(
                self._run_id,
                self._urls_processed,
                self._url_status_updates,
                reason,
            )
            if self._errors_4xx or self._errors_5xx or self._error_count:
                increment_scrape_run_stats(
                    self._progress_session,
                    self._run_id,
                    errors_4xx=self._errors_4xx,
                    errors_5xx=self._errors_5xx,
                    error_count=self._error_count,
                )
                self._progress_session.commit()
            finalized = True
        except Exception:
            self.logger.exception(
                "Spider close: progress-session finalize failed; using failsafe"
            )
        finally:
            if self._progress_session is not None:
                with contextlib.suppress(Exception):
                    self._progress_session.close()
                self._progress_session = None

        # Failsafe: if the progress-session path didn't finalize the run
        # row (poisoned session, DB blip), do it via a fresh session so
        # the row is never left as 'running'. Stats / URL status updates
        # are best-effort and may be lost in this branch.
        if not finalized:
            from book_scraper.db.repo import finalize_run_failsafe

            status = "completed" if reason == "finished" else "failed"
            finalize_run_failsafe(database_url, self._run_id, status, reason)
