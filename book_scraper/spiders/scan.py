from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import scrapy
from sqlalchemy.orm import Session

from book_scraper.config import load_shop_config
from book_scraper.db.models import DiscoveredUrl, Listing, ScrapeRun
from book_scraper.db.repo import (
    create_scrape_run,
    finish_scrape_run,
    get_latest_completed_run,
    get_pending_scan_urls,
    mark_stale_runs_failed,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory
from book_scraper.items import ListingItem
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
        self.custom_settings = {
            "CONCURRENT_REQUESTS_PER_DOMAIN": scraping.get(
                "concurrent_requests_per_domain", 1
            ),
            "DOWNLOAD_DELAY": scraping.get("download_delay", 1.0),
        }

        self._run_id: int | None = None
        self._urls_processed: int = 0
        self._url_status_updates: list[dict[str, Any]] = []

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        database_url = self.settings.get("DATABASE_URL")
        session_factory = get_session_factory(database_url)
        session: Session = session_factory()

        try:
            shop = upsert_shop(session, self.shop_name, self.conf["shop"]["base_url"])

            # Mark stale/crashed runs as failed
            stale_count = mark_stale_runs_failed(session, shop.id, "scan")
            if stale_count:
                self.logger.info("Marked %d stale scan run(s) as failed", stale_count)

            # Auto-discover check
            self._check_discover_freshness(session, shop.id)

            # Load pending URLs
            pending_urls = get_pending_scan_urls(session, shop.id)

            # Filter out already-scraped URLs (resume logic)
            urls_to_scrape = self._filter_already_done(session, shop.id, pending_urls)

            # Create new run
            run = create_scrape_run(
                session, shop.id, "scan", urls_total=len(urls_to_scrape)
            )
            self._run_id = run.id
            session.commit()

            self.logger.info(
                "Scan starting: %d URLs to scrape (%d skipped as already done)",
                len(urls_to_scrape),
                len(pending_urls) - len(urls_to_scrape),
            )

            for url_record in urls_to_scrape:
                yield scrapy.Request(
                    url_record.url,
                    callback=self.parse_product,
                    errback=self.handle_error,
                    meta={"discovered_url_id": url_record.id},
                )
        finally:
            session.close()

    def _check_discover_freshness(self, session: Session, shop_id: int) -> None:
        """Check if discovery is fresh enough. Error if no URLs exist,
        warn if stale but proceed."""
        has_any_urls = (
            session.query(DiscoveredUrl)
            .filter(DiscoveredUrl.shop_id == shop_id)
            .first()
            is not None
        )

        if not has_any_urls:
            raise RuntimeError(
                f"No discovered URLs for shop '{self.shop_name}'. "
                f"Run discover first: scrapy crawl discover "
                f"-a shop={self.shop_name} -a strategy=sitemap"
            )

        # Check freshness - warn if stale but don't block
        discover_conf = self.conf.get("discover", {})
        for strategy in ("sitemap", "categories"):
            strategy_conf = discover_conf.get(strategy)
            if strategy_conf is None:
                continue
            max_age = strategy_conf.get("max_age_hours")
            if max_age is None:
                continue

            phase = f"discover_{strategy}"
            latest = get_latest_completed_run(session, shop_id, phase)

            if latest is None:
                self.logger.warning(
                    "No completed %s run found. "
                    "Run: scrapy crawl discover -a shop=%s -a strategy=%s",
                    phase,
                    self.shop_name,
                    strategy,
                )
                continue

            if latest.finished_at is None:
                continue

            age_hours = (datetime.now(UTC) - latest.finished_at).total_seconds() / 3600
            if age_hours > max_age:
                self.logger.warning(
                    "Last %s is %.0fh old (max: %sh). "
                    "Run: scrapy crawl discover -a shop=%s -a strategy=%s",
                    phase,
                    age_hours,
                    max_age,
                    self.shop_name,
                    strategy,
                )

    def _filter_already_done(
        self,
        session: Session,
        shop_id: int,
        pending_urls: list[DiscoveredUrl],
    ) -> list[DiscoveredUrl]:
        """Filter out URLs already scraped in a recent run (resume logic)."""
        recent_run = (
            session.query(ScrapeRun)
            .filter(
                ScrapeRun.shop_id == shop_id,
                ScrapeRun.phase == "scan",
                ScrapeRun.status.in_(["completed", "failed"]),
            )
            .order_by(ScrapeRun.started_at.desc())
            .first()
        )

        if recent_run is None:
            return pending_urls

        cutoff = recent_run.started_at
        scraped_urls = set(
            row[0]
            for row in session.query(Listing.url)
            .filter(
                Listing.shop_id == shop_id,
                Listing.last_seen_at >= cutoff,
            )
            .all()
        )

        return [u for u in pending_urls if u.url not in scraped_urls]

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
        """Queue a URL status update for batch processing at spider close."""
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

    def closed(self, reason: str) -> None:
        """Update scrape_run and process URL status updates on close."""
        if self._run_id is None:
            return

        database_url = self.settings.get("DATABASE_URL")
        session_factory = get_session_factory(database_url)
        session = session_factory()

        try:
            # Process URL status updates
            for update in self._url_status_updates:
                update_discovered_url_status(session, **update)

            status = "completed" if reason == "finished" else "failed"
            update_scrape_run_progress(session, self._run_id, self._urls_processed)
            finish_scrape_run(session, self._run_id, status)
            session.commit()
        finally:
            session.close()
