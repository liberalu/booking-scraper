from decimal import Decimal, InvalidOperation
from typing import Any

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem
from sqlalchemy.orm import Session, sessionmaker

from book_scraper.db.repo import insert_price, upsert_listing, upsert_shop
from book_scraper.db.session import get_session_factory
from book_scraper.items import ListingItem, PriceItem


class ValidationPipeline:
    def process_item(self, item: Any, spider: Any) -> Any:
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

        if isinstance(item, ListingItem) and not adapter.get("shop_title"):
            raise DropItem("Missing shop_title")

        return item


class PostgresPipeline:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.session_factory: sessionmaker[Session] | None = None
        self.session: Session | None = None
        self.shop_cache: dict[str, int] = {}

    @classmethod
    def from_crawler(cls, crawler: Any) -> "PostgresPipeline":
        return cls(database_url=crawler.settings.get("DATABASE_URL"))

    def open_spider(self, spider: Any) -> None:
        self.session_factory = get_session_factory(self.database_url)
        self.session = self.session_factory()

    def close_spider(self, spider: Any) -> None:
        if self.session:
            self.session.commit()
            self.session.close()

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

    def process_item(self, item: Any, spider: Any) -> Any:
        if self.session is None:
            return item

        adapter = ItemAdapter(item)
        shop_name: str = adapter.get("shop_name") or ""

        if isinstance(item, ListingItem):
            shop_id = self._get_shop_id(shop_name)
            listing = upsert_listing(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                shop_title=adapter["shop_title"],
                shop_author=adapter.get("shop_author"),
                isbn_from_shop=adapter.get("isbn"),
                image_url=adapter.get("image_url"),
            )
            if adapter.get("price") is not None:
                insert_price(
                    self.session,
                    listing_id=listing.id,
                    price=Decimal(adapter["price"]),
                    price_original=(
                        Decimal(adapter["price_original"])
                        if adapter.get("price_original")
                        else None
                    ),
                    in_stock=adapter.get("in_stock", True),
                )

        elif isinstance(item, PriceItem):
            shop_id = self._get_shop_id(shop_name)
            listing = upsert_listing(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                shop_title=adapter.get("url", ""),
            )
            insert_price(
                self.session,
                listing_id=listing.id,
                price=Decimal(adapter["price"]),
                price_original=(
                    Decimal(adapter["price_original"])
                    if adapter.get("price_original")
                    else None
                ),
                in_stock=adapter.get("in_stock", True),
            )

        # Commit every 100 items
        if hasattr(spider, "_item_count"):
            spider._item_count += 1
        else:
            spider._item_count = 1
        if spider._item_count % 100 == 0:
            self.session.commit()

        return item
