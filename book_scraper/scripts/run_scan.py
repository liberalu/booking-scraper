"""Standalone scan script using httpx instead of Scrapy.

Usage: PYTHONPATH=. uv run python book_scraper/scripts/run_scan.py
"""

import logging
import time
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.orm import Session

from book_scraper.config import load_shop_config
from book_scraper.db.repo import (
    get_pending_scan_urls,
    get_urls_already_scraped,
    insert_price,
    update_discovered_url_status,
    upsert_listing,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory
from book_scraper.spiders.registry import load_parsers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("scan_script")

# Also log warnings to file
file_handler = logging.FileHandler("scrapy_errors.log")
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
)
logging.getLogger().addHandler(file_handler)


def run_scan(shop_name: str = "vaga") -> None:
    conf = load_shop_config(shop_name)
    parsers = load_parsers(shop_name)
    base_url = conf["shop"]["base_url"]
    scraping = conf.get("scraping", {})

    batch_size: int = scraping.get("batch_size", 100)
    batch_pause: float = scraping.get("batch_pause", 15.0)
    delay: float = scraping.get("download_delay", 0.5)
    timeout: float = scraping.get("download_timeout", 15)
    db_url = "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper"

    session_factory = get_session_factory(db_url)
    session: Session = session_factory()

    shop = upsert_shop(session, shop_name, base_url)

    pending = get_pending_scan_urls(session, shop.id)
    already_done = get_urls_already_scraped(session, shop.id)
    urls = [u for u in pending if u.url not in already_done]

    logger.info(
        "Scan: %d URLs to scrape (%d skipped), batch_size=%d, pause=%ds",
        len(urls),
        len(pending) - len(urls),
        batch_size,
        batch_pause,
    )

    client = httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"Connection": "close"},
    )

    processed = 0
    failed = 0
    non_product = 0
    total = len(urls)

    for batch_num in range(0, total, batch_size):
        batch = urls[batch_num : batch_num + batch_size]
        batch_idx = batch_num // batch_size + 1
        num_batches = (total + batch_size - 1) // batch_size

        if batch_num > 0:
            logger.info(
                "Batch %d/%d: pausing %ds",
                batch_idx,
                num_batches,
                batch_pause,
            )
            time.sleep(batch_pause)

        logger.info(
            "Batch %d/%d: scraping %d URLs "
            "(%d processed, %d failed, %d non-product)",
            batch_idx,
            num_batches,
            len(batch),
            processed,
            failed,
            non_product,
        )

        for url_record in batch:
            try:
                resp = client.get(url_record.url)
            except Exception as e:
                logger.warning("Failed %s: %s", url_record.url, e)
                update_discovered_url_status(
                    session,
                    url_id=url_record.id,
                    http_status=None,
                    increment_fail=True,
                )
                failed += 1
                time.sleep(delay)
                continue

            if resp.status_code in (404, 410):
                update_discovered_url_status(
                    session,
                    url_id=url_record.id,
                    http_status=resp.status_code,
                    increment_fail=True,
                )
                failed += 1
                time.sleep(delay)
                continue

            data = parsers.parse_product_page(resp.text)

            if not data.get("title"):
                update_discovered_url_status(
                    session,
                    url_id=url_record.id,
                    http_status=200,
                    url_type="non_product",
                )
                non_product += 1
                time.sleep(delay)
                continue

            # Build properties
            props: dict[str, Any] = {}
            for key in (
                "pages",
                "cover_type",
                "duration",
                "narrator",
                "translator",
            ):
                if data.get(key) is not None:
                    props[key] = data[key]

            price = (
                Decimal(str(data["price"]))
                if data.get("price")
                else None
            )
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
                shop_id=shop.id,
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

            processed += 1
            time.sleep(delay)

        # Commit after each batch
        session.commit()
        logger.info(
            "Batch %d/%d done. Total: %d processed, %d failed, "
            "%d non-product",
            batch_idx,
            num_batches,
            processed,
            failed,
            non_product,
        )

    session.commit()
    client.close()
    session.close()
    logger.info(
        "Scan complete: %d processed, %d failed, %d non-product",
        processed,
        failed,
        non_product,
    )


if __name__ == "__main__":
    run_scan()
