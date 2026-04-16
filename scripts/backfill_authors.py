"""Backfill: fill in `listings.author` for rows missing it by re-reading
the shop's category pages.

The normal category-discovery crawl already refreshes authors on every
run, but that's coupled to a full re-discovery. This script runs the
narrower pass: fetch category pages, parse out (url, author) pairs, and
update only the listings whose `author` is currently NULL.

Idempotent:
  - Running after every author is filled is a no-op (UPDATE matches
    zero rows because the WHERE clause requires `author IS NULL`).
  - It never overwrites an existing author.
  - Multiple category pages contributing the same URL will land on the
    same answer because each page is the single source of truth for
    that product.

Usage:
    PYTHONPATH=. uv run python scripts/backfill_authors.py vaga
    PYTHONPATH=. uv run python scripts/backfill_authors.py vaga --max-pages 20
    PYTHONPATH=. uv run python scripts/backfill_authors.py vaga --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import httpx

from book_scraper.config import load_shop_config
from book_scraper.db.models import Listing, Shop
from book_scraper.db.session import get_session_factory
from book_scraper.spiders.registry import load_parsers

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper",
)

log = logging.getLogger("backfill_authors")


def _iter_category_pages(
    client: httpx.Client,
    url_template: str,
    max_pages: int,
    request_delay: float,
) -> list[str]:
    """Walk the paginated category URLs until the shop stops returning
    products (or we hit max_pages). Returns the raw HTML of every page
    that had at least some content in its body.

    We can't inspect for "has products" here without a parser, so this
    just fetches until we get an empty body or an HTTP error.
    """
    pages: list[str] = []
    for page_num in range(1, max_pages + 1):
        url = url_template.format(page=page_num)
        try:
            resp = client.get(url, timeout=30.0)
        except httpx.RequestError as err:
            log.warning("page %d: request failed (%s) — stopping", page_num, err)
            break
        if resp.status_code != 200:
            log.info(
                "page %d: HTTP %d — stopping pagination",
                page_num,
                resp.status_code,
            )
            break
        body = resp.text
        if not body.strip():
            log.info("page %d: empty body — stopping", page_num)
            break
        pages.append(body)
        log.info("page %d: fetched (%d bytes)", page_num, len(body))
        time.sleep(request_delay)
    return pages


def backfill(
    shop_name: str,
    max_pages: int = 100,
    request_delay: float = 0.25,
    dry_run: bool = False,
) -> int:
    conf = load_shop_config(shop_name)
    try:
        category_conf = conf.discover.categories
    except AttributeError as err:
        raise SystemExit(f"Shop '{shop_name}' has no categories strategy") from err
    if category_conf is None:
        raise SystemExit(f"Shop '{shop_name}' has no categories strategy")

    parsers = load_parsers(shop_name)
    session = get_session_factory(DATABASE_URL)()
    try:
        shop = session.query(Shop).filter(Shop.name == shop_name).one_or_none()
        if shop is None:
            log.warning("Shop '%s' not in DB — nothing to update", shop_name)
            return 0

        missing_count = (
            session.query(Listing)
            .filter(Listing.shop_id == shop.id, Listing.author.is_(None))
            .count()
        )
        log.info(
            "%s: %d listing(s) currently have NULL author",
            shop_name,
            missing_count,
        )
        if missing_count == 0:
            return 0

        with httpx.Client(follow_redirects=True) as client:
            pages = _iter_category_pages(
                client,
                category_conf.url,
                max_pages=max_pages,
                request_delay=request_delay,
            )

        updated = 0
        for body in pages:
            products = parsers.parse_category_page(body)
            for product in products:
                url = product.get("url")
                author = product.get("author")
                if not url or not author:
                    continue
                if not url.startswith("http"):
                    url = conf.shop.base_url + url
                # WHERE author IS NULL makes this idempotent: once a
                # listing has an author we never clobber it.
                result = (
                    session.query(Listing)
                    .filter(
                        Listing.shop_id == shop.id,
                        Listing.url == url,
                        Listing.author.is_(None),
                    )
                    .update({"author": author}, synchronize_session=False)
                )
                updated += result
        if dry_run:
            log.info(
                "%s: DRY RUN — would update %d listing(s)",
                shop_name,
                updated,
            )
            session.rollback()
        else:
            session.commit()
            log.info("%s: updated author on %d listing(s)", shop_name, updated)
        return updated
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shop", help="Shop name, e.g. 'vaga'")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help="Stop after this many category pages (default: 100)",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.25,
        help="Seconds to sleep between page requests (default: 0.25)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the scrape but roll back DB changes at the end",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    backfill(
        args.shop,
        max_pages=args.max_pages,
        request_delay=args.request_delay,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
