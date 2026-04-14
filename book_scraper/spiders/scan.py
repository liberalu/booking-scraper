import asyncio
import resource
import time
from collections.abc import AsyncGenerator, Generator
from typing import Any

import scrapy
from sqlalchemy.orm import Session

from book_scraper.config import load_shop_config
from book_scraper.db.repo import increment_scrape_run_stats
from book_scraper.db.session import get_session_factory
from book_scraper.items import ListingItem
from book_scraper.services.scan import ScanService
from book_scraper.spiders.registry import load_parsers


class ScanSpider(scrapy.Spider):
    name = "scan"

    def __init__(
        self,
        shop: str | None = None,
        rescrape: str = "false",
        urls: str = "",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        if not shop:
            raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
        self.shop_name = shop
        self._rescrape = rescrape.lower() in ("true", "1", "yes")
        self._single_urls = [u.strip() for u in urls.split(",") if u.strip()]
        self.conf = load_shop_config(shop)
        self.parsers = load_parsers(shop)
        self.allowed_domains = [
            self.conf.shop.base_url.replace("https://", "").replace("http://", "")
        ]

        scraping = self.conf.scraping
        self._batch_size: int = scraping.batch_size
        self._batch_pause: float = scraping.batch_pause

        self._run_id: int | None = None
        self._urls_processed: int = 0
        self._urls_responded: int = 0
        self._url_status_updates: list[dict[str, Any]] = []
        self._progress_session: Session | None = None
        self._progress_service: ScanService | None = None

        self._flush_every: int = 50
        self._errors_4xx: int = 0
        self._errors_5xx: int = 0
        self._error_count: int = 0

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        # Single-URL mode: create a run but skip full scan plan
        if self._single_urls:
            database_url = self.settings.get("DATABASE_URL")
            session_factory = get_session_factory(database_url)
            session = session_factory()
            try:
                from book_scraper.db.repo import create_scrape_run, upsert_shop

                shop = upsert_shop(
                    session, self.shop_name, self.conf.shop.base_url
                )
                run = create_scrape_run(
                    session, shop.id, "scan",
                    urls_total=len(self._single_urls),
                )
                session.commit()
                self._run_id = run.id
            finally:
                session.close()

            self.logger.info(
                "Single-URL mode: scraping %d URLs (run #%d)",
                len(self._single_urls), self._run_id,
            )
            for url in self._single_urls:
                yield scrapy.Request(
                    url,
                    callback=self.parse_product,
                    errback=self.handle_error,
                    meta={"discovered_url_id": None},
                )
            return

        database_url = self.settings.get("DATABASE_URL")
        session_factory = get_session_factory(database_url)
        session: Session = session_factory()

        try:
            service = ScanService(session)
            plan = service.prepare_scan(
                self.shop_name,
                self.conf.shop.base_url,
                self.conf,
                rescrape=self._rescrape,
            )
            self._run_id = plan.run_id

            for warning in plan.freshness_warnings:
                self.logger.warning(warning)

            total = len(plan.urls_to_scrape)
            num_batches = (total + self._batch_size - 1) // self._batch_size

            self.logger.info(
                "Scan starting: %d URLs in %d batches of %d "
                "(%.0fs pause between batches, %d skipped)",
                total,
                num_batches,
                self._batch_size,
                self._batch_pause,
                plan.urls_skipped,
            )

            prev_batch_start = time.monotonic()

            for batch_num in range(num_batches):
                start_idx = batch_num * self._batch_size
                end_idx = min(start_idx + self._batch_size, total)
                batch = plan.urls_to_scrape[start_idx:end_idx]

                if batch_num > 0:
                    # Wait for previous batch to finish processing
                    while self._urls_responded < start_idx:
                        await asyncio.sleep(1)

                    # Log previous batch timing and memory
                    batch_elapsed = time.monotonic() - prev_batch_start
                    mem_mb = resource.getrusage(
                        resource.RUSAGE_SELF
                    ).ru_maxrss / (1024 * 1024)
                    self.logger.info(
                        "Batch %d/%d completed in %.1fs "
                        "(memory: %.0fMB)",
                        batch_num,
                        num_batches,
                        batch_elapsed,
                        mem_mb,
                    )

                    self.logger.info(
                        "Batch %d/%d: pausing %.0fs",
                        batch_num + 1,
                        num_batches,
                        self._batch_pause,
                    )
                    await asyncio.sleep(self._batch_pause)

                prev_batch_start = time.monotonic()

                self.logger.info(
                    "Batch %d/%d: yielding %d URLs",
                    batch_num + 1,
                    num_batches,
                    len(batch),
                )

                for url_record in batch:
                    yield scrapy.Request(
                        url_record.url,
                        callback=self.parse_product,
                        errback=self.handle_error,
                        meta={"discovered_url_id": url_record.id},
                    )
        finally:
            session.close()

    def parse_product(
        self, response: scrapy.http.Response
    ) -> Generator[ListingItem, None, None]:
        discovered_url_id = response.meta.get("discovered_url_id")

        url = response.url.split("?")[0]
        if 400 <= response.status < 500:
            self._errors_4xx += 1
            self._error_count += 1
            self._report_validation(
                "http_4xx", "response", url, str(response.status),
            )
            self._queue_url_status_update(
                discovered_url_id,
                http_status=response.status,
                increment_fail=True,
            )
            return
        if 500 <= response.status < 600:
            self._errors_5xx += 1
            self._error_count += 1
            self._report_validation(
                "http_5xx", "response", url, str(response.status),
            )
            self._queue_url_status_update(
                discovered_url_id,
                http_status=response.status,
                increment_fail=True,
            )
            return

        # HTTP-level checks
        url = response.url.split("?")[0]
        if len(response.text) < 1024:
            self._report_validation(
                "empty_response", "response", url,
                f"len={len(response.text)}",
            )
        request_url = response.request.url.split("?")[0] if response.request else url
        final_url = url
        if final_url != request_url:
            # Check if redirected to homepage or category
            base = self.conf.shop.base_url.rstrip("/")
            path = final_url.replace(base, "")
            if path in ("", "/") or path.count("/") == 1:
                self._report_validation(
                    "redirect_to_homepage", "url", request_url,
                    f"redirected to {final_url}",
                )

        data = self.parsers.parse_product_page(response.text)

        if not data.get("title"):
            self._queue_url_status_update(
                discovered_url_id, http_status=200, url_type="non_product"
            )
            return

        # Build properties dict from format-specific fields
        props: dict[str, object] = {}
        for key in ("pages", "cover_type", "duration", "narrator", "translator"):
            if data.get(key) is not None:
                props[key] = data[key]

        item = ListingItem(
            url=response.url.split("?")[0],
            shop_name=self.shop_name,
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
        )

        # Mark URL as successfully scraped
        self._queue_url_status_update(
            discovered_url_id, http_status=200, url_type="product"
        )

        self._urls_processed += 1
        yield item

    def handle_error(self, failure: Any) -> None:
        """Handle request failures (timeouts, connection errors)."""
        request = failure.request
        discovered_url_id = request.meta.get("discovered_url_id")
        url = str(request.url).split("?")[0]

        status = getattr(failure.value, "response", None)
        http_status = status.status if status else None

        if http_status and 400 <= http_status < 500:
            self._errors_4xx += 1
            self._report_validation(
                "http_4xx", "response", url, str(http_status),
            )
        elif http_status and 500 <= http_status < 600:
            self._errors_5xx += 1
            self._report_validation(
                "http_5xx", "response", url, str(http_status),
            )
        else:
            error_type = type(failure.value).__name__
            self._report_validation(
                "request_error", "response", url, error_type,
            )
        self._error_count += 1

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
                issue, field, url, raw_value,
            )

    def _queue_url_status_update(
        self,
        url_id: int | None,
        http_status: int | None = None,
        url_type: str | None = None,
        increment_fail: bool = False,
    ) -> None:
        """Queue a URL status update and flush periodically."""
        if url_id is None:
            return
        self._url_status_updates.append(
            {
                "url_id": url_id,
                "http_status": http_status,
                "url_type": url_type,
                "increment_fail": increment_fail,
            }
        )
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
        """Update scrape_run and process URL status updates on close."""
        if self._run_id is None:
            return

        if self._progress_session is None:
            database_url = self.settings.get("DATABASE_URL")
            session_factory = get_session_factory(database_url)
            self._progress_session = session_factory()
            self._progress_service = ScanService(self._progress_session)

        try:
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
        finally:
            self._progress_session.close()
            self._progress_session = None
