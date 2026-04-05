from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from book_scraper.db.models import Category, Listing, Price, Shop


def upsert_shop(session: Session, name: str, base_url: str) -> Shop:
    stmt = select(Shop).where(Shop.name == name)
    shop = session.execute(stmt).scalar_one_or_none()
    if shop is None:
        shop = Shop(name=name, base_url=base_url)
        session.add(shop)
        session.flush()
    return shop


def upsert_listing(
    session: Session,
    shop_id: int,
    url: str,
    title: str,
    author: str | None = None,
    sku: str | None = None,
    isbn: str | None = None,
    publisher: str | None = None,
    year: int | None = None,
    format: str | None = None,
    description: str | None = None,
    image_url: str | None = None,
    categories: list[str] | None = None,
    properties: dict[str, Any] | None = None,
    price: Decimal | None = None,
    price_original: Decimal | None = None,
    in_stock: bool = True,
) -> Listing:
    stmt = select(Listing).where(Listing.shop_id == shop_id, Listing.url == url)
    listing = session.execute(stmt).scalar_one_or_none()
    now = datetime.now(UTC)
    if listing is None:
        listing = Listing(
            shop_id=shop_id,
            url=url,
            title=title,
            author=author,
            sku=sku,
            isbn=isbn,
            publisher=publisher,
            year=year,
            format=format,
            description=description,
            image_url=image_url,
            categories=categories,
            properties=properties,
            price=price,
            price_original=price_original,
            in_stock=in_stock,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(listing)
        session.flush()
    else:
        listing.title = title
        listing.author = author
        # Only update fields if provided (don't overwrite with None from price spider)
        if sku is not None:
            listing.sku = sku
        if isbn is not None:
            listing.isbn = isbn
        if publisher is not None:
            listing.publisher = publisher
        if year is not None:
            listing.year = year
        if format is not None:
            listing.format = format
        if description is not None:
            listing.description = description
        if image_url is not None:
            listing.image_url = image_url
        if categories is not None:
            listing.categories = categories
        if properties is not None:
            # Merge with existing properties
            existing = listing.properties or {}
            existing.update(properties)
            listing.properties = existing
        if price is not None:
            listing.price = price
        if price_original is not None:
            listing.price_original = price_original
        listing.in_stock = in_stock
        listing.last_seen_at = now
        listing.is_active = True
        session.flush()
    return listing


def insert_price(
    session: Session,
    listing_id: int,
    price: Decimal,
    price_original: Decimal | None,
    in_stock: bool,
) -> Price:
    record = Price(
        listing_id=listing_id,
        price=price,
        price_original=price_original,
        in_stock=in_stock,
        scraped_at=datetime.now(UTC),
    )
    session.add(record)
    session.flush()
    return record


def upsert_category(
    session: Session, name: str, slug: str, parent_id: int | None = None
) -> Category:
    stmt = select(Category).where(Category.slug == slug)
    cat = session.execute(stmt).scalar_one_or_none()
    if cat is None:
        cat = Category(name=name, slug=slug, parent_id=parent_id)
        session.add(cat)
        session.flush()
    return cat


def mark_listings_inactive(
    session: Session, shop_id: int, active_urls: set[str]
) -> int:
    """Mark listings not in active_urls as inactive. Returns count of deactivated."""
    stmt = select(Listing).where(
        Listing.shop_id == shop_id, Listing.is_active.is_(True)
    )
    listings = session.execute(stmt).scalars().all()
    count = 0
    for listing in listings:
        if listing.url not in active_urls:
            listing.is_active = False
            count += 1
    session.flush()
    return count
