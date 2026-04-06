from decimal import Decimal, InvalidOperation
from typing import Any

from itemadapter import ItemAdapter
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from sqlalchemy.orm import Session, sessionmaker

from book_scraper.db.repo import (
    increment_scrape_run_stats,
    insert_price,
    update_scrape_run_progress,
    upsert_discovered_url,
    upsert_listing,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory
from book_scraper.items import DiscoveredUrlItem, ListingItem, PriceItem


class ValidationPipeline:
    def process_item(self, item: Any) -> Any:
        adapter = ItemAdapter(item)

        if isinstance(item, (ListingItem, PriceItem)):
            price = adapter.get("price")
            if price is not None:
                try:
                    adapter["price"] = str(Decimal(str(price)))
                except (InvalidOperation, ValueError) as err:
                    raise DropItem(f"Invalid price: {price}") from err

            price_original = adapter.get("price_original")
            if price_original is not None:
                try:
                    adapter["price_original"] = str(Decimal(str(price_original)))
                except (InvalidOperation, ValueError):
                    adapter["price_original"] = None

        if isinstance(item, ListingItem) and not adapter.get("title"):
            raise DropItem("Missing title")

        return item


class PostgresPipeline:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.session_factory: sessionmaker[Session] | None = None
        self.session: Session | None = None
        self.shop_cache: dict[str, int] = {}
        self.crawler: Crawler | None = None
        self._item_count: int = 0
        self._stats_added: int = 0
        self._stats_updated: int = 0

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "PostgresPipeline":  # pragma: no cover
        pipeline = cls(database_url=crawler.settings.get("DATABASE_URL"))
        pipeline.crawler = crawler
        return pipeline

    def open_spider(self) -> None:  # pragma: no cover
        self.session_factory = get_session_factory(self.database_url)
        self.session = self.session_factory()

    def close_spider(self) -> None:  # pragma: no cover
        if self.session:
            spider = self.spider
            if spider and hasattr(spider, "_run_id") and spider._run_id:
                self._flush_stats(spider._run_id)
            self.session.commit()
            self.session.close()

    @property
    def spider(self) -> Any:
        return self.crawler.spider if self.crawler else None

    def _flush_stats(self, run_id: int) -> None:
        if self._stats_added or self._stats_updated:
            assert self.session is not None
            increment_scrape_run_stats(
                self.session,
                run_id,
                items_added=self._stats_added,
                items_updated=self._stats_updated,
            )
            self._stats_added = 0
            self._stats_updated = 0

    def _get_shop_id(self, shop_name: str) -> int:
        if shop_name not in self.shop_cache:
            assert self.session is not None
            shop = upsert_shop(
                self.session,
                name=shop_name,
                base_url=f"https://{shop_name}.lt",
            )
            self.shop_cache[shop_name] = shop.id
        return self.shop_cache[shop_name]

    def process_item(self, item: Any) -> Any:
        if self.session is None:  # pragma: no cover
            return item

        adapter = ItemAdapter(item)
        shop_name: str = adapter.get("shop_name") or ""

        if isinstance(item, ListingItem):
            shop_id = self._get_shop_id(shop_name)

            year = adapter.get("year")
            if year is not None:
                try:
                    year = int(year)
                except (ValueError, TypeError):
                    year = None

            price = (
                Decimal(adapter["price"]) if adapter.get("price") is not None else None
            )
            price_original = (
                Decimal(adapter["price_original"])
                if adapter.get("price_original")
                else None
            )

            listing, created = upsert_listing(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                title=adapter["title"],
                author=adapter.get("author"),
                sku=adapter.get("sku"),
                isbn=adapter.get("isbn"),
                publisher=adapter.get("publisher"),
                year=year,
                format=adapter.get("format"),
                description=adapter.get("description"),
                image_url=adapter.get("image_url"),
                categories=adapter.get("categories"),
                properties=adapter.get("properties"),
                price=price,
                price_original=price_original,
                in_stock=adapter.get("in_stock", True),
            )
            if created:
                self._stats_added += 1
            else:
                self._stats_updated += 1
            if price is not None:
                insert_price(
                    self.session,
                    listing_id=listing.id,
                    price=price,
                    price_original=price_original,
                    in_stock=adapter.get("in_stock", True),
                )

        elif isinstance(item, PriceItem):
            shop_id = self._get_shop_id(shop_name)
            price = Decimal(adapter["price"])
            price_original = (
                Decimal(adapter["price_original"])
                if adapter.get("price_original")
                else None
            )
            listing, created = upsert_listing(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                title=adapter.get("title") or adapter["url"],
                price=price,
                price_original=price_original,
                in_stock=adapter.get("in_stock", True),
            )
            if created:
                self._stats_added += 1
            else:
                self._stats_updated += 1
            insert_price(
                self.session,
                listing_id=listing.id,
                price=price,
                price_original=price_original,
                in_stock=adapter.get("in_stock", True),
            )

        elif isinstance(item, DiscoveredUrlItem):
            shop_id = self._get_shop_id(shop_name)
            upsert_discovered_url(
                self.session,
                shop_id=shop_id,
                url=item["url"],
                source=item["source"],
            )

        # Commit every 100 items
        self._item_count += 1
        if self._item_count % 100 == 0:
            self.session.commit()
            # Update scrape_run progress if spider tracks it
            spider = self.spider
            if spider and hasattr(spider, "_run_id") and spider._run_id:
                update_scrape_run_progress(
                    self.session,
                    spider._run_id,
                    spider._urls_processed,
                )
                self._flush_stats(spider._run_id)

        return item
