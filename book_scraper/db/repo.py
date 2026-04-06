from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from book_scraper.db.models import (
    Category,
    DiscoveredUrl,
    Listing,
    Price,
    ScrapeRun,
    Shop,
)


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


# --- Discovered URLs ---


def upsert_discovered_url(
    session: Session,
    shop_id: int,
    url: str,
    source: str,
) -> DiscoveredUrl:
    stmt = select(DiscoveredUrl).where(
        DiscoveredUrl.shop_id == shop_id, DiscoveredUrl.url == url
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is not None:
        return existing
    record = DiscoveredUrl(shop_id=shop_id, url=url, source=source)
    session.add(record)
    session.flush()
    return record


def update_discovered_url_status(
    session: Session,
    url_id: int,
    http_status: int | None = None,
    url_type: str | None = None,
    increment_fail: bool = False,
) -> None:
    record = session.get(DiscoveredUrl, url_id)
    if record is None:
        return
    record.last_checked_at = datetime.now(UTC)
    if http_status is not None:
        record.last_http_status = http_status
    if url_type is not None:
        record.url_type = url_type
    if increment_fail:
        record.fail_count += 1
    else:
        record.fail_count = 0
    session.flush()


def get_pending_scan_urls(
    session: Session,
    shop_id: int,
    max_fail_count: int = 3,
    retry_after_days: int = 7,
) -> list[DiscoveredUrl]:
    cutoff = datetime.now(UTC) - timedelta(days=retry_after_days)
    stmt = select(DiscoveredUrl).where(
        DiscoveredUrl.shop_id == shop_id,
        DiscoveredUrl.url_type != "non_product",
        or_(
            DiscoveredUrl.fail_count < max_fail_count,
            DiscoveredUrl.last_checked_at < cutoff,
            DiscoveredUrl.last_checked_at.is_(None),
        ),
    )
    return list(session.execute(stmt).scalars().all())


# --- Scrape Runs ---


def create_scrape_run(
    session: Session,
    shop_id: int,
    phase: str,
    urls_total: int | None = None,
) -> ScrapeRun:
    run = ScrapeRun(
        shop_id=shop_id,
        phase=phase,
        status="running",
        urls_total=urls_total,
    )
    session.add(run)
    session.flush()
    return run


def finish_scrape_run(
    session: Session,
    run_id: int,
    status: str,
) -> None:
    run = session.get(ScrapeRun, run_id)
    if run is None:
        return
    run.status = status
    run.finished_at = datetime.now(UTC)
    session.flush()


def mark_stale_runs_failed(
    session: Session,
    shop_id: int,
    phase: str,
) -> int:
    now = datetime.now(UTC)
    stmt = select(ScrapeRun).where(
        ScrapeRun.shop_id == shop_id,
        ScrapeRun.phase == phase,
        ScrapeRun.status == "running",
    )
    stale = list(session.execute(stmt).scalars().all())
    for run in stale:
        run.status = "failed"
        run.finished_at = now
    session.flush()
    return len(stale)


def get_latest_completed_run(
    session: Session,
    shop_id: int,
    phase: str,
) -> ScrapeRun | None:
    stmt = (
        select(ScrapeRun)
        .where(
            ScrapeRun.shop_id == shop_id,
            ScrapeRun.phase == phase,
            ScrapeRun.status == "completed",
        )
        .order_by(ScrapeRun.finished_at.desc())
    )
    return session.execute(stmt).scalar_one_or_none()


def update_scrape_run_progress(
    session: Session,
    run_id: int,
    urls_processed: int,
) -> None:
    run = session.get(ScrapeRun, run_id)
    if run is None:
        return
    run.urls_processed = urls_processed
    session.flush()


# --- Scan orchestration helpers ---


def check_discover_freshness(
    session: Session,
    shop_id: int,
    shop_name: str,
    discover_config: dict[str, Any],
) -> list[str]:
    """Check if discovery is fresh enough. Raises RuntimeError if no URLs exist.
    Returns list of warning messages for stale discoveries."""
    has_any_urls = (
        session.query(DiscoveredUrl).filter(DiscoveredUrl.shop_id == shop_id).first()
        is not None
    )

    if not has_any_urls:
        raise RuntimeError(
            f"No discovered URLs for shop '{shop_name}'. "
            f"Run discover first: scrapy crawl discover "
            f"-a shop={shop_name} -a strategy=sitemap"
        )

    warnings: list[str] = []
    for strategy in ("sitemap", "categories"):
        strategy_conf = discover_config.get(strategy)
        if strategy_conf is None:
            continue
        max_age = strategy_conf.get("max_age_hours")
        if max_age is None:
            continue

        phase = f"discover_{strategy}"
        latest = get_latest_completed_run(session, shop_id, phase)

        if latest is None:
            warnings.append(
                f"No completed {phase} run found. "
                f"Run: scrapy crawl discover -a shop={shop_name} -a strategy={strategy}"
            )
            continue

        if latest.finished_at is None:
            continue

        age_hours = (datetime.now(UTC) - latest.finished_at).total_seconds() / 3600
        if age_hours > max_age:
            warnings.append(
                f"Last {phase} is {age_hours:.0f}h old (max: {max_age}h). "
                f"Run: scrapy crawl discover -a shop={shop_name} -a strategy={strategy}"
            )

    return warnings


def get_urls_already_scraped(session: Session, shop_id: int) -> set[str]:
    """Return URLs already scraped since the last completed/failed scan run."""
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
        return set()

    cutoff = recent_run.started_at
    return set(
        row[0]
        for row in session.query(Listing.url)
        .filter(
            Listing.shop_id == shop_id,
            Listing.last_seen_at >= cutoff,
        )
        .all()
    )
