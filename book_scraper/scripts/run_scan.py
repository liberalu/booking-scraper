"""Standalone scan script using httpx instead of Scrapy.

Usage: PYTHONPATH=. uv run python book_scraper/scripts/run_scan.py [shop]
"""

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.orm import Session

from book_scraper.config import load_shop_config
from book_scraper.db.models import DiscoveredUrl
from book_scraper.db.repo import (
    create_scrape_run,
    finish_scrape_run,
    get_pending_scan_urls,
    get_urls_already_scraped,
    insert_price,
    mark_stale_runs_failed,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_listing,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory
from book_scraper.spiders.registry import load_parsers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("scan")

file_handler = logging.FileHandler("scan_errors.log")
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
)
logging.getLogger().addHandler(file_handler)

# Suppress noisy httpx request logging
logging.getLogger("httpx").setLevel(logging.WARNING)


@dataclass
class Stats:
    processed: int = 0
    failed: int = 0
    non_product: int = 0
    retried: int = 0
    http_errors: int = 0
    start_time: float = field(default_factory=time.monotonic)

    @property
    def total_handled(self) -> int:
        return self.processed + self.failed + self.non_product

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def rate(self) -> float:
        elapsed = self.elapsed
        return (self.total_handled / elapsed * 60) if elapsed > 0 else 0

    def summary(self) -> str:
        mins = self.elapsed / 60
        return (
            f"{self.processed} products, {self.non_product} non-product, "
            f"{self.failed} failed, {self.retried} retries | "
            f"{self.rate:.0f} pages/min | {mins:.1f} min elapsed"
        )


async def fetch_url(
    client: httpx.AsyncClient,
    url: str,
    max_retries: int = 2,
    retry_delay: float = 3.0,
) -> httpx.Response | None:
    """Fetch URL with retries and exponential backoff."""
    for attempt in range(max_retries + 1):
        try:
            return await client.get(url)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt < max_retries:
                wait = retry_delay * (2**attempt)
                logger.debug(
                    "Retry %d/%d for %s (%.0fs): %s",
                    attempt + 1,
                    max_retries,
                    url,
                    wait,
                    e,
                )
                await asyncio.sleep(wait)
            else:
                logger.warning(
                    "Failed after %d retries: %s: %s",
                    max_retries,
                    url,
                    e,
                )
                return None
    return None


def process_response(
    resp: httpx.Response | None,
    url_record: DiscoveredUrl,
    shop_id: int,
    session: Session,
    parsers: Any,
    stats: Stats,
) -> None:
    """Process a single response and save to DB."""
    if resp is None:
        update_discovered_url_status(
            session,
            url_id=url_record.id,
            http_status=None,
            increment_fail=True,
        )
        stats.failed += 1
        return

    if resp.status_code in (404, 410):
        update_discovered_url_status(
            session,
            url_id=url_record.id,
            http_status=resp.status_code,
            increment_fail=True,
        )
        stats.http_errors += 1
        stats.failed += 1
        return

    if resp.status_code != 200:
        update_discovered_url_status(
            session,
            url_id=url_record.id,
            http_status=resp.status_code,
            increment_fail=True,
        )
        stats.http_errors += 1
        stats.failed += 1
        return

    data = parsers.parse_product_page(resp.text)

    if not data.get("title"):
        update_discovered_url_status(
            session,
            url_id=url_record.id,
            http_status=200,
            url_type="non_product",
        )
        stats.non_product += 1
        return

    props: dict[str, Any] = {}
    for key in ("pages", "cover_type", "duration", "narrator", "translator"):
        if data.get(key) is not None:
            props[key] = data[key]

    price = Decimal(str(data["price"])) if data.get("price") else None
    price_original = (
        Decimal(str(data["price_original"]))
        if data.get("price_original")
        else None
    )

    year = data.get("year")
    if year is not None:
        try:
            year = int(year)
        except (ValueError, TypeError):
            year = None

    listing = upsert_listing(
        session,
        shop_id=shop_id,
        url=url_record.url.split("?")[0],
        title=data["title"],
        author=data.get("author"),
        sku=data.get("sku"),
        isbn=data.get("isbn"),
        publisher=data.get("publisher"),
        year=year,
        format=data.get("format"),
        description=data.get("description"),
        image_url=data.get("image_url"),
        categories=data.get("categories", []),
        properties=props or None,
        price=price,
        price_original=price_original,
        in_stock=data.get("in_stock", True),
    )

    if price is not None:
        insert_price(
            session,
            listing_id=listing.id,
            price=price,
            price_original=price_original,
            in_stock=data.get("in_stock", True),
        )

    update_discovered_url_status(
        session,
        url_id=url_record.id,
        http_status=200,
        url_type="product",
    )
    stats.processed += 1


async def scrape_batch(
    client: httpx.AsyncClient,
    batch: list[DiscoveredUrl],
    shop_id: int,
    session: Session,
    parsers: Any,
    stats: Stats,
    concurrency: int = 4,
    max_retries: int = 2,
) -> None:
    """Scrape a batch with bounded concurrency."""
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(
        url_record: DiscoveredUrl,
    ) -> tuple[DiscoveredUrl, httpx.Response | None]:
        async with semaphore:
            resp = await fetch_url(client, url_record.url, max_retries)
            if resp is None:
                stats.retried += 1
            return url_record, resp

    tasks = [fetch_one(rec) for rec in batch]
    results = await asyncio.gather(*tasks)

    for url_record, resp in results:
        process_response(resp, url_record, shop_id, session, parsers, stats)


async def run_scan(shop_name: str = "vaga") -> None:
    conf = load_shop_config(shop_name)
    parsers = load_parsers(shop_name)
    base_url = conf["shop"]["base_url"]
    scraping = conf.get("scraping", {})

    batch_size: int = scraping.get("batch_size", 100)
    batch_pause: float = scraping.get("batch_pause", 15.0)
    timeout: float = scraping.get("download_timeout", 15)
    concurrency: int = scraping.get("concurrent_requests_per_domain", 4)
    max_retries: int = scraping.get("max_retries", 2)
    db_url = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper"
    )

    session_factory = get_session_factory(db_url)
    session: Session = session_factory()

    shop = upsert_shop(session, shop_name, base_url)
    mark_stale_runs_failed(session, shop.id, "scan")

    pending = get_pending_scan_urls(session, shop.id)
    already_done = get_urls_already_scraped(session, shop.id)
    urls = [u for u in pending if u.url not in already_done]
    total = len(urls)
    num_batches = (total + batch_size - 1) // batch_size

    if total == 0:
        logger.info("Nothing to scan — all URLs already done")
        session.close()
        return

    run = create_scrape_run(session, shop.id, "scan", urls_total=total)
    session.commit()
    run_id = run.id

    logger.info(
        "Scan run #%d: %d URLs in %d batches of %d "
        "(concurrency=%d, pause=%ds, %d skipped)",
        run_id,
        total,
        num_batches,
        batch_size,
        concurrency,
        batch_pause,
        len(pending) - total,
    )

    stats = Stats()
    status = "failed"

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=concurrency + 2,
                max_keepalive_connections=0,
            ),
        ) as client:
            for batch_idx in range(num_batches):
                start_idx = batch_idx * batch_size
                batch = urls[start_idx : start_idx + batch_size]

                if batch_idx > 0:
                    logger.info(
                        "Pausing %ds before batch %d/%d",
                        batch_pause,
                        batch_idx + 1,
                        num_batches,
                    )
                    await asyncio.sleep(batch_pause)

                logger.info(
                    "Batch %d/%d: %d URLs | %s",
                    batch_idx + 1,
                    num_batches,
                    len(batch),
                    stats.summary(),
                )

                await scrape_batch(
                    client,
                    batch,
                    shop.id,
                    session,
                    parsers,
                    stats,
                    concurrency=concurrency,
                    max_retries=max_retries,
                )

                update_scrape_run_progress(
                    session, run_id, stats.processed
                )
                session.commit()

        status = "completed"
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        status = "failed"
    except Exception:
        logger.exception("Scan failed with error")
        status = "failed"
    finally:
        update_scrape_run_progress(session, run_id, stats.processed)
        finish_scrape_run(session, run_id, status)
        session.commit()
        session.close()

    logger.info(
        "Scan run #%d %s | %s", run_id, status, stats.summary()
    )


if __name__ == "__main__":
    shop = sys.argv[1] if len(sys.argv) > 1 else "vaga"
    asyncio.run(run_scan(shop))
