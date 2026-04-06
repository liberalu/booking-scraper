import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any

import scrapy
from sqlalchemy.orm import Session

from book_scraper.config import load_shop_config
from book_scraper.db.session import get_session_factory
from book_scraper.items import ListingItem
from book_scraper.services.scan import ScanService
from book_scraper.spiders.registry import load_parsers


class ScanSpider(scrapy.Spider):
    name = "scan"

    def __init__(self, shop: str | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        if not shop:
            raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
        self.shop_name = shop
        self.conf = load_shop_config(shop)
        self.parsers = load_parsers(shop)
        self.allowed_domains = [
            self.conf["shop"]["base_url"].replace("https://", "").replace("http://", "")
        ]

        scraping = self.conf.get("scraping", {})
        self._batch_size: int = scraping.get("batch_size", 100)
        self._batch_pause: float = scraping.get("batch_pause", 10.0)

        self._run_id: int | None = None
        self._urls_processed: int = 0
        self._urls_responded: int = 0
        self._url_status_updates: list[dict[str, Any]] = []
        self._progress_session: Session | None = None
        self._progress_service: ScanService | None = None

        self._flush_every: int = 50

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        database_url = self.settings.get("DATABASE_URL")
        session_factory = get_session_factory(database_url)
        session: Session = session_factory()

        try:
            service = ScanService(session)
            plan = service.prepare_scan(
                self.shop_name,
                self.conf["shop"]["base_url"],
                self.conf,
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

            for batch_num in range(num_batches):
                start_idx = batch_num * self._batch_size
                end_idx = min(start_idx + self._batch_size, total)
                batch = plan.urls_to_scrape[start_idx:end_idx]

                if batch_num > 0:
                    # Wait for previous batch to finish processing
                    while self._urls_responded < start_idx:
                        await asyncio.sleep(1)

                    self.logger.info(
                        "Batch %d/%d: pausing %.0fs",
                        batch_num + 1,
                        num_batches,
                        self._batch_pause,
                    )
                    await asyncio.sleep(self._batch_pause)

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

        if response.status in (404, 410):
            self._queue_url_status_update(
                discovered_url_id,
                http_status=response.status,
                increment_fail=True,
            )
            return

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

        status = getattr(failure.value, "response", None)
        http_status = status.status if status else None

        self._queue_url_status_update(
            discovered_url_id,
            http_status=http_status,
            increment_fail=True,
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
        finally:
            self._progress_session.close()
            self._progress_session = None
