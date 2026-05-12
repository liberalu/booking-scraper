import logging
import os
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, or_, select, update
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from book_scraper.db import scrape_run_events as run_event_types
from book_scraper.db.models import (
    Category,
    CronJob,
    DiscoveredUrl,
    Price,
    ScrapeFailure,
    ScrapeRun,
    ScrapeRunEvent,
    ScrapeUrlItem,
    Shop,
    ShopAuthor,
    ShopBook,
    ShopBookAttribute,
    ShopBookAuthor,
    ShopBookFieldUpdate,
    UrlClassification,
    ValidationIssue,
)
from book_scraper.spiders.vaga.parsers import infer_shop_book_type
from book_scraper.url_utils import normalize_url

logger = logging.getLogger(__name__)

_MULTI_AUTHOR_RE = re.compile(
    r"(?:,\s|;|\s&\s|\s/\s|\s+and\s+|\s+ir\s+)", re.IGNORECASE
)


def _split_author_string(raw: str | None) -> list[str]:
    """Split a raw author string on known separators and trim each part.

    Returns a list preserving order. Empty/None yields []. Single-author
    strings become a 1-item list so the caller can always iterate.
    """
    if not raw:
        return []
    parts = [p.strip() for p in _MULTI_AUTHOR_RE.split(raw) if p and p.strip()]
    return parts or [raw.strip()]


def _normalize_author(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _sync_attribute_rows(
    session: Session,
    shop_book: "ShopBook",
    properties: dict[str, Any],
) -> None:
    """Upsert (shop_book_id, key) rows in shop_book_attributes to match the
    provided dict.

    Missing keys leave existing rows alone so a partial scrape doesn't
    clobber previously-captured attributes. Only the keys present in
    `properties` are inserted/updated.
    """
    if not properties:
        return
    existing_rows = {
        row.key: row
        for row in session.query(ShopBookAttribute).filter_by(shop_book_id=shop_book.id)
    }
    for key, value in properties.items():
        str_value = None if value is None else str(value)
        row = existing_rows.get(key)
        if row is None:
            session.add(
                ShopBookAttribute(shop_book_id=shop_book.id, key=key, value=str_value)
            )
        elif row.value != str_value:
            row.value = str_value
    session.flush()


def _sync_shop_book_authors(
    session: Session,
    shop_book_id: int,
    author_raw: str | None,
) -> None:
    """Split `author_raw` on multi-author separators and reconcile
    rows in `shop_authors` + `shop_book_authors` so the shop_book points at
    the right set of authors in the right order.

    Called only when the scrape actually supplies an author string
    (conditional field in `upsert_shop_book`), so category scrapes that
    don't parse an author don't blow away an established list.
    """
    parts = _split_author_string(author_raw)
    # Resolve/create author rows; keep only the first occurrence of any
    # repeated name so (shop_book_id, author_id) stays unique.
    desired: list[tuple[int, int]] = []
    seen_ids: set[int] = set()
    position = 0
    for name in parts:
        norm = _normalize_author(name)
        if not norm:
            continue
        author = (
            session.query(ShopAuthor)
            .filter(ShopAuthor.normalized_name == norm)
            .one_or_none()
        )
        if author is None:
            author = ShopAuthor(name=name, normalized_name=norm)
            session.add(author)
            session.flush()
        if author.id in seen_ids:
            continue
        seen_ids.add(author.id)
        desired.append((author.id, position))
        position += 1

    existing = {
        row.author_id: row
        for row in session.query(ShopBookAuthor).filter(
            ShopBookAuthor.shop_book_id == shop_book_id
        )
    }
    desired_ids = {aid for aid, _ in desired}
    for aid, row in existing.items():
        if aid not in desired_ids:
            session.delete(row)
    for aid, pos in desired:
        match = existing.get(aid)
        if match is None:
            session.add(
                ShopBookAuthor(shop_book_id=shop_book_id, author_id=aid, position=pos)
            )
        elif match.position != pos:
            match.position = pos


def touch_shop_book_field_updates(
    session: Session,
    shop_book_id: int,
    fields: list[str],
    when: datetime | None = None,
) -> None:
    """Set updated_at=now for each (shop_book_id, field), inserting new
    rows when needed.

    `fields` should only contain fields that actually changed; callers
    are expected to filter no-ops out (see PostgresPipeline).
    """
    if not fields:
        return
    stamp = when or datetime.now(UTC)
    existing = {
        row.field: row
        for row in session.query(ShopBookFieldUpdate)
        .filter(ShopBookFieldUpdate.shop_book_id == shop_book_id)
        .filter(ShopBookFieldUpdate.field.in_(fields))
    }
    for field in fields:
        row = existing.get(field)
        if row is None:
            session.add(
                ShopBookFieldUpdate(
                    shop_book_id=shop_book_id, field=field, updated_at=stamp
                )
            )
        else:
            row.updated_at = stamp


def upsert_shop(session: Session, name: str, base_url: str) -> Shop:
    stmt = select(Shop).where(Shop.name == name)
    shop = session.execute(stmt).scalar_one_or_none()
    if shop is None:
        shop = Shop(name=name, base_url=base_url)
        session.add(shop)
        session.flush()
    return shop


def _infer_shop_book_type(
    *,
    title: str,
    author: str | None = None,
    isbn: str | None = None,
    year: int | None = None,
    format: str | None = None,
    categories: list[str] | None = None,
    properties: dict[str, Any] | None = None,
) -> str:
    """Infer the final shop_book type for the current single-shop setup.

    Current values are: book, non_book, ebook, audio.
    Price-only updates should pass no new type and leave an existing row
    unchanged; callers use this helper when they have classification data.
    """
    properties = properties or {}
    return infer_shop_book_type(
        {
            "title": title,
            "author": author,
            "isbn": isbn,
            "year": year,
            "format": format,
            "categories": categories or [],
            "pages": properties.get("pages"),
            "cover_type": properties.get("cover_type"),
            "translator": properties.get("translator"),
            "narrator": properties.get("narrator"),
            "duration": properties.get("duration"),
            "schema_types": [],
        }
    )


def upsert_shop_book(
    session: Session,
    shop_id: int,
    url: str,
    title: str,
    type: str | None = None,
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
    planned_availability_date: Any | None = None,
    rating: Decimal | None = None,
    review_count: int | None = None,
    run_id: int | None = None,
) -> tuple[ShopBook, bool, Decimal | None, list[dict[str, Any]]]:
    """Upsert a shop_book. Returns (shop_book, created, old_price, changes).

    Lookup precedence:

    1. ``(shop_id, sku)`` when ``sku`` is provided. SKUs are durable
       identifiers on shops that expose them (e.g. pegasas's Magento
       SKU stays stable across slug changes), so a URL change shouldn't
       create a new row — we update the existing row's ``url`` instead.
    2. ``(shop_id, url)`` fallback for shops/items without a SKU
       (vaga's HTML scrape sometimes lacks one).

    URLs are normalised (trailing-slash stripped, scheme/host lowercased,
    tracking params removed) before lookup + persistence so the same
    product never gets two rows because two parsers produced two
    cosmetic variants of the same URL — e.g. LupaSearch returns
    ``…/title-12345/`` while the GraphQL parser builds ``…/title-12345``
    from ``f"{base}/{url_key}"``.
    """
    url = normalize_url(url)
    shop_book: ShopBook | None = None
    if sku:
        shop_book = session.execute(
            select(ShopBook).where(ShopBook.shop_id == shop_id, ShopBook.sku == sku)
        ).scalar_one_or_none()

    # Stale-SKU guard: SKU matched a row at a *different* URL — this can
    # happen when a shop assigns a product the wrong URL slug, then later
    # fixes it (moving the product to a corrected slug and recycling the
    # old slug for a different product). If the incoming URL is already
    # owned by another row, updating the SKU-matched row's URL would hit
    # `uq_shop_book_shop_url` and cause an IntegrityError. Detect this
    # split-identity case early: detach the SKU from the stale row and
    # fall through to the URL-matched row so the correct row is updated.
    if shop_book is not None and shop_book.url != url:
        url_owner = session.execute(
            select(ShopBook).where(ShopBook.shop_id == shop_id, ShopBook.url == url)
        ).scalar_one_or_none()
        if url_owner is not None and url_owner.id != shop_book.id:
            logger.warning(
                "upsert_shop_book: stale SKU %s detached from shop_book %s "
                "(url=%s) — URL %s already owned by shop_book %s. "
                "Likely cause: shop reassigned slug after wrong slug was "
                "scraped.",
                sku,
                shop_book.id,
                shop_book.url,
                url,
                url_owner.id,
            )
            shop_book.sku = None
            session.flush()
            shop_book = url_owner

    if shop_book is None:
        shop_book = session.execute(
            select(ShopBook).where(ShopBook.shop_id == shop_id, ShopBook.url == url)
        ).scalar_one_or_none()
    now = datetime.now(UTC)
    if shop_book is None:
        shop_book = ShopBook(
            shop_id=shop_id,
            url=url,
            title=title,
            type=type
            or _infer_shop_book_type(
                title=title,
                author=author,
                isbn=isbn,
                year=year,
                format=format,
                categories=categories,
                properties=properties,
            ),
            author=author,
            sku=sku,
            isbn=isbn,
            publisher=publisher,
            year=year,
            format=format,
            description=description,
            image_url=image_url,
            categories=categories,
            price=price,
            price_original=price_original,
            in_stock=in_stock,
            planned_availability_date=planned_availability_date,
            rating=rating,
            review_count=review_count,
            last_run_id=run_id,
            last_run_action="created",
            created_run_id=run_id,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(shop_book)
        session.flush()
        if properties:
            _sync_attribute_rows(session, shop_book, properties)
        if author is not None:
            _sync_shop_book_authors(session, shop_book.id, author)
        return shop_book, True, None, []
    else:
        old_price = shop_book.price
        shop_book.last_run_id = run_id
        shop_book.last_run_action = "updated"

        # Track field changes
        changes: list[dict[str, Any]] = []
        # When a SKU match found the row but the URL has shifted (slug
        # rename, category-path swap), update the stored URL too so it
        # reflects the latest seen path. Logged as a change so postmortems
        # can see it happened.
        tracked_fields = {
            "url": url,
            "title": title,
        }
        # Fields that only update when provided (not None). Author is
        # conditional so a lightweight PriceItem (category scrape) that
        # didn't parse an author can't clobber one captured from the full
        # product page.
        conditional_fields: dict[str, str | int | None] = {
            "author": author,
            "sku": sku,
            "isbn": isbn,
            "publisher": publisher,
            "year": year,
            "format": format,
            "description": description,
        }

        for field_name, new_val in tracked_fields.items():
            old_val = getattr(shop_book, field_name)
            if old_val != new_val:
                changes.append(
                    {
                        "field": field_name,
                        "old": str(old_val) if old_val is not None else None,
                        "new": str(new_val) if new_val is not None else None,
                    }
                )
            setattr(shop_book, field_name, new_val)

        for cond_field, cond_val in conditional_fields.items():
            if cond_val is not None:
                old_val = getattr(shop_book, cond_field)
                if old_val != cond_val:
                    changes.append(
                        {
                            "field": cond_field,
                            "old": str(old_val) if old_val is not None else None,
                            "new": str(cond_val) if cond_val is not None else None,
                        }
                    )
                setattr(shop_book, cond_field, cond_val)

        if image_url is not None:
            shop_book.image_url = image_url

        if type is not None:
            shop_book.type = type
        elif format is not None:
            current_categories = (
                categories if categories is not None else shop_book.categories
            )
            shop_book.type = _infer_shop_book_type(
                title=shop_book.title,
                author=shop_book.author,
                isbn=shop_book.isbn,
                year=shop_book.year,
                format=shop_book.format,
                categories=current_categories,
                properties=properties,
            )

        if categories is not None:
            shop_book.categories = categories
        if properties is not None:
            _sync_attribute_rows(session, shop_book, properties)
        if author is not None:
            _sync_shop_book_authors(session, shop_book.id, author)
        if price is not None:
            shop_book.price = price
        if price_original is not None:
            shop_book.price_original = price_original
        shop_book.in_stock = in_stock
        if planned_availability_date is not None:
            shop_book.planned_availability_date = planned_availability_date
        if rating is not None:
            shop_book.rating = rating
        if review_count is not None:
            shop_book.review_count = review_count
        shop_book.last_seen_at = now
        shop_book.is_active = True
        # Clear the transition stamp when a previously-vanished shop_book
        # comes back; keeps the "inactive_since" semantics meaningful.
        shop_book.inactive_since = None
        session.flush()
        return shop_book, False, old_price, changes


def insert_price(
    session: Session,
    shop_book_id: int,
    price: Decimal,
    price_original: Decimal | None,
    in_stock: bool,
    run_id: int | None = None,
) -> Price:
    record = Price(
        shop_book_id=shop_book_id,
        price=price,
        price_original=price_original,
        in_stock=in_stock,
        scraped_at=datetime.now(UTC),
        scrape_run_id=run_id,
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


def mark_shop_books_inactive(
    session: Session, shop_id: int, active_urls: set[str]
) -> int:
    """Mark shop_books not in active_urls as inactive. Returns count of deactivated.

    Stamps `inactive_since` with the transition time so the dashboard
    can show "inactive since <date>" and so downstream jobs can prune
    long-vanished shop_books.
    """
    stmt = select(ShopBook).where(
        ShopBook.shop_id == shop_id, ShopBook.is_active.is_(True)
    )
    shop_books = session.execute(stmt).scalars().all()
    now = datetime.now(UTC)
    count = 0
    for shop_book in shop_books:
        if shop_book.url not in active_urls:
            shop_book.is_active = False
            shop_book.inactive_since = now
            count += 1
    session.flush()
    return count


# --- Discovered URLs ---


def upsert_discovered_url(
    session: Session,
    shop_id: int,
    url: str,
    source: str,
    run_id: int | None = None,
    shop_book_id: int | None = None,
) -> DiscoveredUrl:
    """Upsert (shop_id, normalized_url).

    New rows record `first_seen_at = last_seen_at = now`. Repeat hits
    refresh `last_seen_at`, update `last_seen_run_id` when `run_id` is
    provided, and adopt a resolved `shop_book_id` when one is supplied.
    The raw `url` on an existing row is left alone — the normalized
    URL is the canonical identifier.

    Implemented as an atomic ``INSERT … ON CONFLICT DO UPDATE`` so two
    items in the same pipeline batch (e.g. a book that appears under
    multiple categories in one GraphQL page response) don't race on
    the SELECT-then-INSERT path. The previous version triggered an
    ``IntegrityError`` whenever a duplicate snuck in, which then
    poisoned the SQLAlchemy session with ``PendingRollbackError`` for
    every subsequent item — the spider would go silent, stall, and
    die without finishing.
    """
    normalized = normalize_url(url)
    now = datetime.now(UTC)
    initial_url_type = "product" if shop_book_id is not None else "unknown"

    insert_stmt = pg_insert(DiscoveredUrl).values(
        shop_id=shop_id,
        url=url,
        normalized_url=normalized,
        source=source,
        url_type=initial_url_type,
        first_seen_at=now,
        last_seen_at=now,
        last_seen_run_id=run_id,
        shop_book_id=shop_book_id,
    )
    # On conflict, refresh last_seen_at + last_seen_run_id, adopt a
    # resolved shop_book_id if one came in, and promote url_type from
    # 'unknown' → 'product' once we know it's a real product page.
    update_set: dict[str, Any] = {"last_seen_at": now}
    if run_id is not None:
        update_set["last_seen_run_id"] = run_id
    if shop_book_id is not None:
        update_set["shop_book_id"] = shop_book_id
        # Promote url_type from 'unknown' to 'product' but never demote
        # 'non_product' / 'unreachable' — those are operator decisions.
        update_set["url_type"] = func.coalesce(
            case(
                (DiscoveredUrl.url_type == "unknown", "product"),
                else_=DiscoveredUrl.url_type,
            ),
            "product",
        )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["shop_id", "normalized_url"],
        set_=update_set,
    ).returning(DiscoveredUrl.id)
    new_id = session.execute(upsert_stmt).scalar_one()
    session.flush()
    record = session.get(DiscoveredUrl, new_id)
    assert record is not None
    # The ORM may have a stale cached row from before the upsert (when
    # the same URL was upserted earlier in the session). Refresh so
    # callers see last_seen_at / last_seen_run_id / shop_book_id values
    # that reflect the just-applied UPDATE.
    session.refresh(record)
    return record


def link_discovered_url_to_shop_book(
    session: Session,
    shop_id: int,
    url: str,
    shop_book_id: int,
    run_id: int | None = None,
    is_partial: bool = False,
) -> DiscoveredUrl | None:
    """Idempotently attach a shop_book to its discovered URL row.

    Returns the row (creating one if missing — useful when a shop_book
    is upserted via a path that didn't go through discovery yet).

    ``is_partial=True`` signals the caller knows the persisted shop_book
    is missing key metadata (e.g. ISBN from lupasearch). The url_type is
    set/promoted to ``product_partial`` instead of ``product`` so the
    delta scan picks it up. Calling again with ``is_partial=False`` (or
    a successful scan-spider URL update) promotes it the rest of the way
    to ``product``. Once a row is ``product``, a later partial call does
    NOT demote it — full data is sticky.
    """
    target_type = "product_partial" if is_partial else "product"
    normalized = normalize_url(url)
    stmt = select(DiscoveredUrl).where(
        DiscoveredUrl.shop_id == shop_id,
        DiscoveredUrl.normalized_url == normalized,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    now = datetime.now(UTC)
    if existing is not None:
        if existing.shop_book_id != shop_book_id:
            existing.shop_book_id = shop_book_id
        # Promotion ladder: unknown -> product_partial -> product. A
        # non-partial call can advance product_partial to product, but a
        # partial call must not demote an already-complete product row.
        if existing.url_type == "unknown":
            existing.url_type = target_type
        elif existing.url_type == "product_partial" and not is_partial:
            existing.url_type = "product"
        existing.last_seen_at = now
        if run_id is not None:
            existing.last_seen_run_id = run_id
        session.flush()
        return existing
    record = DiscoveredUrl(
        shop_id=shop_id,
        url=url,
        normalized_url=normalized,
        source="category",
        url_type=target_type,
        first_seen_at=now,
        last_seen_at=now,
        last_seen_run_id=run_id,
        shop_book_id=shop_book_id,
    )
    session.add(record)
    session.flush()
    return record


# Failures before a URL is considered unreachable
# (mirrors get_pending_scan_urls default).
_UNREACHABLE_THRESHOLD = 3


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
    now = datetime.now(UTC)
    record.last_checked_at = now
    if http_status is not None:
        record.last_http_status = http_status

    if increment_fail:
        record.fail_count += 1
        # Promote to "unreachable" when fail threshold is first reached.
        # Skip if already unreachable or classified as non_product (those
        # pages return 404/non-2xx by design from the scraper's perspective
        # but aren't "unreachable" in the user-facing sense).
        if record.fail_count >= _UNREACHABLE_THRESHOLD and record.url_type not in (
            "non_product",
            "unreachable",
        ):
            record.url_type = "unreachable"
            # Inactivate the linked shop_book — it was scraped from this URL
            # and the URL is now dead, so the listing is gone.
            if record.shop_book_id is not None:
                sb = session.get(ShopBook, record.shop_book_id)
                if sb is not None and sb.is_active:
                    sb.is_active = False
                    sb.inactive_since = now
    else:
        # Successful fetch — reset failure state.
        if record.url_type == "unreachable":
            # Put back to "unknown" so the next parse re-classifies it.
            # The shop_book will be re-activated by upsert_shop_book if the
            # page is still a valid product.
            record.url_type = url_type if url_type is not None else "unknown"
        elif url_type is not None:
            record.url_type = url_type
        record.fail_count = 0

    session.flush()


def upsert_url_classification(
    session: Session,
    discovered_url_id: int,
    book_score: int,
    is_book_product: bool,
    reasons: list[dict[str, object]],
) -> None:
    """Upsert the book classification for a discovered URL.

    Called unconditionally after parse_product_page() — covers both book
    and non-book results so every scanned URL has a classification row.
    """
    stmt = select(UrlClassification).where(
        UrlClassification.discovered_url_id == discovered_url_id
    )
    existing = session.execute(stmt).scalar_one_or_none()
    now = datetime.now(UTC)
    if existing is not None:
        existing.book_score = book_score
        existing.is_book_product = is_book_product
        existing.reasons = reasons
        existing.classified_at = now
    else:
        record = UrlClassification(
            discovered_url_id=discovered_url_id,
            book_score=book_score,
            is_book_product=is_book_product,
            reasons=reasons,
            classified_at=now,
        )
        session.add(record)
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


def get_stable_discovered_urls(
    session: Session,
    shop_id: int,
    retry_after_days: int = 7,
) -> dict[str, str]:
    """Return URLs already classified and recently checked.

    Used by `discover_full_crawl` to skip enqueueing scan jobs for URLs
    whose `url_type` is already known (`product`, `non_product`,
    `unreachable`) and were checked within `retry_after_days`. The crawler
    still follows these URLs to find new outgoing links — only the
    `scrape_url_items` insert is skipped.

    Keys are `normalized_url`; values are `url_type`.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retry_after_days)
    stmt = select(DiscoveredUrl.normalized_url, DiscoveredUrl.url_type).where(
        DiscoveredUrl.shop_id == shop_id,
        DiscoveredUrl.url_type.in_(("product", "non_product", "unreachable")),
        DiscoveredUrl.last_checked_at.is_not(None),
        DiscoveredUrl.last_checked_at >= cutoff,
    )
    return {row.normalized_url: row.url_type for row in session.execute(stmt)}


# --- Scrape Runs ---


def try_acquire_scan_lock(session: Session, shop_id: int, phase: str) -> bool:
    """Acquire a transaction-scoped advisory lock keyed on (shop_id, phase).

    Returns True if the lock was acquired, False if another transaction
    already holds it. The lock releases automatically on commit or rollback;
    callers should hold it across the run-creation transaction so that two
    scrapy processes hitting `prepare_scan_create_run` concurrently do not
    both create runs for the same shop+phase.
    """
    key2 = abs(hash(phase)) & 0x7FFFFFFF  # 32-bit positive
    result = session.execute(
        sa_text("SELECT pg_try_advisory_xact_lock(:k1, :k2)"),
        {"k1": shop_id, "k2": key2},
    ).scalar()
    return bool(result)


_RETRYABLE_FAILURE_REASONS = frozenset(
    {"run_aborted", "stuck_in_processing", "subdivision_5xx"}
)


def count_consecutive_zero_progress_resumes(
    session: Session, run_id: int, max_lookback: int = 8
) -> int:
    """Count trailing zero-progress restart events on a run.

    Walks `restarted` events newest → oldest. Each event's payload
    carries `urls_processed_snapshot` — the value of `urls_processed`
    captured at the moment of the restart. A "zero-progress restart"
    is one whose snapshot equals the snapshot of the previous restart
    (i.e. nothing got done between the two attempts).

    Stops at the first event that DID make progress, or after
    `max_lookback` events. Returns the streak length.

    Used by the StallDetector to circuit-break: 2+ consecutive zero-
    progress restarts means the bug is structural, not transient.
    """
    events = (
        session.query(ScrapeRunEvent)
        .filter(
            ScrapeRunEvent.run_id == run_id,
            ScrapeRunEvent.event_type == run_event_types.RESTARTED,
        )
        .order_by(ScrapeRunEvent.id.desc())
        .limit(max_lookback)
        .all()
    )
    if not events:
        return 0

    # Compare each event's snapshot to the next-older one's snapshot.
    # If equal, the gap between them produced no progress.
    streak = 0
    for newer, older in zip(events, events[1:], strict=False):
        newer_snap = (newer.payload or {}).get("urls_processed_snapshot")
        older_snap = (older.payload or {}).get("urls_processed_snapshot")
        if newer_snap is None or older_snap is None:
            break
        if newer_snap == older_snap:
            streak += 1
        else:
            break
    # `streak` counts adjacent pairs that match — N matching pairs span
    # N+1 events. Return the event count, capped to total events seen.
    # If no pair matched, the streak is 0; return 0 (not 1) — a single
    # restart with no predecessor can't be "zero-progress" by definition.
    return min(streak + 1 if streak > 0 else 0, len(events))


def count_auto_resume_chain_depth(session: Session, run_id: int) -> int:
    """Count `restarted` events on this run.

    Returns 0 for a run that has never restarted. Used by the
    StallDetector + reconcile_runs to cap runaway auto-resume loops.
    """
    return (
        session.query(ScrapeRunEvent)
        .filter(
            ScrapeRunEvent.run_id == run_id,
            ScrapeRunEvent.event_type == run_event_types.RESTARTED,
        )
        .count()
    )


def reset_retryable_failures(session: Session, run_id: int) -> int:
    """Reset failed URL items with retryable error reasons back to pending.

    run_aborted: items that were in-flight when the run was killed.
    stuck_in_processing: items that timed out in the processing state.
    Both are transient failures that should be retried on the next run.
    """
    retryable_item_ids = (
        session.query(ScrapeUrlItem.id)
        .join(
            ScrapeFailure,
            ScrapeFailure.scrape_url_item_id == ScrapeUrlItem.id,
        )
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status == "failed",
            ScrapeFailure.run_id == run_id,
            ScrapeFailure.error_reason.in_(_RETRYABLE_FAILURE_REASONS),
        )
        .distinct()
    )
    stmt = (
        update(ScrapeUrlItem)
        .where(ScrapeUrlItem.id.in_(retryable_item_ids.subquery().select()))
        .values(status="pending", done_at=None)
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    session.flush()
    rowcount = getattr(result, "rowcount", 0)
    return int(rowcount) if rowcount is not None else 0


def restart_run_in_place(
    session: Session,
    run: ScrapeRun,
    *,
    payload: dict[str, Any],
    actor: str,
    event_type: str = "restarted",
) -> None:
    """Mutate a `failed`+`resumable_after_failure` run back to `running`
    on the same row, then emit the restart marker event.

    **Service-layer use only** — call from inside the spawned scrapy
    subprocess so `os.getpid()` is the spider's PID. The dashboard
    Continue endpoint already mutates the row in-place itself before
    spawning the subprocess; do not call this from the dashboard
    process — it would stamp the dashboard PID on the run.

    Atomic with the surrounding caller's transaction: the UPDATE and
    the event INSERT both go through `session.flush()` and rely on the
    caller to commit.

    Refuses to operate on a row that is not `failed`+`resumable_after_failure`
    — callers must filter on `find_resumable_run`'s output.
    """
    if run.status != "failed" or not run.resumable_after_failure:
        raise ValueError(
            f"restart_run_in_place expects status='failed' "
            f"AND resumable_after_failure=True; got status={run.status!r}, "
            f"resumable_after_failure={run.resumable_after_failure!r}"
        )

    run.status = "running"
    run.finished_at = None
    run.close_reason = None
    run.resumable_after_failure = False
    run.pid = os.getpid()
    run.last_heartbeat = datetime.now(UTC)
    session.flush()

    reset_retryable_failures(session, run.id)
    reset_processing_scrape_url_items(session, run.id)

    emit_scrape_run_event(
        session,
        run.id,
        event_type,
        payload=payload,
        actor=actor,
    )


def emit_scrape_run_event(
    session: Session,
    run_id: int,
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
    actor: str | None = None,
) -> ScrapeRunEvent:
    """Append a lifecycle event to scrape_run_events.

    Append-only: callers must not update or delete events. Flushed within
    the caller's transaction so the event is atomic with the surrounding
    state mutation (status flip, row insert, etc.).
    """
    if event_type not in run_event_types.EVENT_TYPES:
        raise ValueError(f"unknown scrape run event_type: {event_type!r}")
    event = ScrapeRunEvent(
        run_id=run_id,
        event_type=event_type,
        actor=actor,
        payload=payload,
    )
    session.add(event)
    session.flush()
    return event


def create_scrape_run(
    session: Session,
    shop_id: int,
    phase: str,
    urls_total: int | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> ScrapeRun:
    run = ScrapeRun(
        shop_id=shop_id,
        phase=phase,
        status="running",
        urls_total=urls_total,
        last_heartbeat=datetime.now(UTC),
        pid=os.getpid(),
    )
    session.add(run)
    session.flush()
    payload: dict[str, Any] = {"phase": phase}
    if urls_total is not None:
        payload["urls_total"] = urls_total
    if extra_payload:
        payload.update(extra_payload)
    emit_scrape_run_event(
        session,
        run.id,
        run_event_types.STARTED,
        payload=payload,
        actor=run_event_types.ACTOR_SYSTEM,
    )
    return run


def finish_scrape_run(
    session: Session,
    run_id: int,
    status: str,
    reason: str | None = None,
) -> None:
    run = session.get(ScrapeRun, run_id)
    if run is None:
        return
    was_running = run.status == "running"
    was_non_terminal = run.status not in ("completed", "failed")
    run.status = status
    run.finished_at = datetime.now(UTC)
    # Stamp close_reason on every transition (idempotent — first writer wins
    # via the `is None` guard in record_scrape_run_failed_issue, but the
    # explicit set here ensures the happy `completed`/`reason="finished"`
    # path also persists a value).
    if reason is not None and run.close_reason is None:
        run.close_reason = reason
    session.flush()
    if was_running:
        abort_processing_scrape_url_items(session, run_id)
    if was_running and status == "failed":
        record_scrape_run_failed_issue(session, run, reason or "finished_failed")
    if was_non_terminal and status in ("completed", "failed"):
        terminal_event = (
            run_event_types.COMPLETED
            if status == "completed"
            else run_event_types.FAILED
        )
        emit_scrape_run_event(
            session,
            run_id,
            terminal_event,
            payload={
                "close_reason": run.close_reason,
                "urls_processed": run.urls_processed,
                "error_count": run.error_count,
            },
            actor=run_event_types.ACTOR_SYSTEM,
        )
    logger.info("scrape_run %d -> %s (reason=%s)", run_id, status, reason or "<none>")


def finalize_run_failsafe(
    database_url: str,
    run_id: int,
    status: str,
    reason: str,
    resumable_after_failure: bool = False,
) -> None:
    """Finalize a scrape run via a fresh DB session.

    Bypasses any long-lived pipeline session that may be poisoned with a
    PendingRollbackError after an earlier failed query. The fresh session
    reconnects cleanly and applies a 5-second statement_timeout so a hung
    DB doesn't block spider shutdown.

    Used by spider close paths (scan, discover) and the StallDetector.
    Swallows-and-logs any exception so the spider always finishes its
    shutdown sequence — leaving the row zombie (later reaped) is strictly
    worse than a logged finalize failure.

    If ``resumable_after_failure`` is True, the run row is flagged so the
    next scheduled run inherits its pending scrape_url_items (used by the
    StallDetector — stalled runs still have valid pending work).
    """
    from book_scraper.db.session import get_session_factory

    try:
        session_factory = get_session_factory(database_url)
        session = session_factory()
        try:
            session.execute(sa_text("SET LOCAL statement_timeout = '5s'"))
            # Guard: only finalize if the run is still in a non-terminal state.
            # Without this, the closed() failsafe in spiders that call
            # finish_scrape_run() before returning would have their completed
            # status clobbered to failed here (closed() fires after start()
            # returns, so finish_scrape_run already ran successfully).
            _run = session.get(ScrapeRun, run_id)
            if _run is not None and _run.status in ("completed", "failed"):
                return
            finish_scrape_run(session, run_id, status, reason=reason)
            if resumable_after_failure:
                run = session.get(ScrapeRun, run_id)
                if run is not None:
                    run.resumable_after_failure = True
            session.commit()
        finally:
            session.close()
    except Exception:
        logger.exception(
            "Failsafe finalize for run %d failed (status=%s, reason=%s)",
            run_id,
            status,
            reason,
        )


def abort_processing_scrape_url_items(session: Session, run_id: int) -> int:
    """Flip any still-`processing` rows to `failed` with reason=run_aborted.

    Called when a run transitions to a terminal state (failed/completed)
    so in-flight rows don't sit at `processing` indefinitely after the
    process behind them is gone. The `done_at IS NULL` clause makes
    concurrent reaper passes safe no-ops.
    """
    now = datetime.now(UTC)
    items = (
        session.query(ScrapeUrlItem)
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status == "processing",
            ScrapeUrlItem.done_at.is_(None),
        )
        .all()
    )
    for item in items:
        item.status = "failed"
        item.done_at = now
    session.flush()
    # PR 3 of the migration: failure detail (reason / http) lives only
    # in scrape_failures now. The queue row carries `status` only.
    for item in items:
        record_scrape_failure(
            session,
            scrape_url_item=item,
            error_reason="run_aborted",
            http_status=None,
            error_detail="run_aborted",
            occurred_at=now,
        )
    return len(items)


# Per-row staleness threshold for `processing` items on still-active runs.
# DOWNLOAD_TIMEOUT is 15s (settings.py); the dashboard already labels rows
# "stuck" at 30s (DOWNLOAD_TIMEOUT × 2). The reaper threshold is set higher
# so we never reap a row the dashboard hasn't even labeled stuck yet.
STUCK_ROW_THRESHOLD_S = 120


def sweep_orphaned_processing_items(session: Session) -> int:
    """Reap stale `processing` rows.

    Two cases in one pass:
    - Terminal runs (failed/completed/stopped): every `processing` row →
      `failed` with reason `run_aborted`. Reuses
      `abort_processing_scrape_url_items`.
    - Active runs (`running`/`paused`): only rows whose `claimed_at` is
      older than `STUCK_ROW_THRESHOLD_S` → `failed` with reason
      `stuck_in_processing`. Surfaces hung workers in the Failures card
      instead of letting them sit at `processing` forever.

    Rows with `claimed_at IS NULL` are never reaped — they were never
    legitimately claimed.

    Transaction ownership stays with the caller: this helper only
    `flush()`es. The caller commits (or rolls back) so we don't
    accidentally commit unrelated pending work on the same session.
    """
    from sqlalchemy import exists

    has_orphan = (
        exists()
        .where(ScrapeUrlItem.run_id == ScrapeRun.id)
        .where(ScrapeUrlItem.status == "processing")
        .where(ScrapeUrlItem.done_at.is_(None))
    )
    terminal_with_orphans = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.status.not_in(("running", "paused")),
            has_orphan,
        )
        .all()
    )

    cleaned = 0
    for run in terminal_with_orphans:
        cleaned += abort_processing_scrape_url_items(session, run.id)

    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=STUCK_ROW_THRESHOLD_S)
    stuck = (
        session.query(ScrapeUrlItem)
        .join(ScrapeRun, ScrapeRun.id == ScrapeUrlItem.run_id)
        .filter(
            ScrapeRun.status.in_(("running", "paused")),
            ScrapeUrlItem.status == "processing",
            ScrapeUrlItem.done_at.is_(None),
            ScrapeUrlItem.claimed_at.isnot(None),
            ScrapeUrlItem.claimed_at < cutoff,
        )
        .all()
    )
    for item in stuck:
        item.status = "failed"
        item.done_at = now
        cleaned += 1

    if cleaned:
        session.flush()
        for item in stuck:
            record_scrape_failure(
                session,
                scrape_url_item=item,
                error_reason="stuck_in_processing",
                http_status=None,
                error_detail="stuck_in_processing",
                occurred_at=now,
            )
    return cleaned


def record_scrape_run_failed_issue(
    session: Session,
    run: ScrapeRun,
    reason: str,
) -> None:
    """Insert a `scrape_run_failed` validation issue for a failed run.

    Surfaces failed runs on the validation/issues page so they don't go
    unnoticed. Idempotent — skips insert if the run already has one.

    Also stamps `close_reason` on the run if it is not already set, so
    out-of-band callers (mark_stale_runs_failed, mark_orphan_runs_failed,
    dashboard reaper, manual kill) record their reason on the run itself.
    First writer wins.
    """
    if run.close_reason is None:
        run.close_reason = reason
    existing = (
        session.query(ValidationIssue.id)
        .filter(
            ValidationIssue.scrape_run_id == run.id,
            ValidationIssue.issue == "scrape_run_failed",
        )
        .first()
    )
    if existing is not None:
        session.flush()
        return
    issue = ValidationIssue(
        scrape_run_id=run.id,
        url=f"run:{run.id}",
        field="run",
        issue="scrape_run_failed",
        raw_value=reason,
        lifecycle_state="new",
    )
    session.add(issue)
    session.flush()


def mark_stale_runs_failed(
    session: Session,
    shop_id: int,
    phase: str,
    reason: str = "stale_pre_scan",
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
        if run.close_reason is None:
            run.close_reason = reason
        record_scrape_run_failed_issue(session, run, reason)
        abort_processing_scrape_url_items(session, run.id)
        emit_scrape_run_event(
            session,
            run.id,
            run_event_types.FAILED,
            payload={
                "close_reason": reason,
                "urls_processed": run.urls_processed,
                "error_count": run.error_count,
            },
            actor=run_event_types.ACTOR_SYSTEM,
        )
        logger.info("scrape_run %d -> failed (reason=%s)", run.id, reason)
    session.flush()
    return len(stale)


def find_resumable_run(
    session: Session,
    shop_id: int,
    phase: str,
) -> "ScrapeRun | None":
    """Find a resumable scrape run with pending scrape_url_items.

    A run is resumable when it has pending items AND either:
      - status = 'running' (crash-interrupted, queue still owned by the row)
      - status = 'failed' AND resumable_after_failure = True
        (reaped for heartbeat_timeout / stall_timeout — the queue was
        good work that the next scheduled run should adopt)

    Returns None if no resumable run exists.
    """
    from sqlalchemy import and_, exists, or_

    has_pending = (
        exists()
        .where(ScrapeUrlItem.run_id == ScrapeRun.id)
        .where(ScrapeUrlItem.status == "pending")
    )
    stmt = (
        select(ScrapeRun)
        .where(
            ScrapeRun.shop_id == shop_id,
            ScrapeRun.phase == phase,
            or_(
                # Active runs (running or paused) own their queue.
                ScrapeRun.status.in_(("running", "paused")),
                and_(
                    ScrapeRun.status == "failed",
                    ScrapeRun.resumable_after_failure.is_(True),
                ),
            ),
            has_pending,
        )
        .order_by(ScrapeRun.started_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def mark_orphan_runs_failed(
    session: Session,
) -> list[tuple[int, str, str]]:
    """Fail every run still flagged 'running'. Call on scraper boot —
    any row still 'running' belongs to a process the restart killed.

    Orphans had a real spider doing real work; flag them
    ``resumable_after_failure`` so the next scheduled run inherits any
    pending items rather than dropping them on the floor.

    Returns a list of (run_id, shop_name, phase) tuples for the caller
    to optionally spawn automatic restarts.
    """
    now = datetime.now(UTC)
    stmt = (
        select(ScrapeRun)
        .where(ScrapeRun.status == "running")
        .options(joinedload(ScrapeRun.shop))
    )
    orphans = list(session.execute(stmt).scalars().all())
    orphan_info: list[tuple[int, str, str]] = []
    for run in orphans:
        run.status = "failed"
        run.finished_at = now
        run.resumable_after_failure = True
        if run.close_reason is None:
            run.close_reason = "orphan_on_boot"
        record_scrape_run_failed_issue(session, run, "orphan_on_boot")
        abort_processing_scrape_url_items(session, run.id)
        emit_scrape_run_event(
            session,
            run.id,
            run_event_types.FAILED,
            payload={
                "close_reason": "orphan_on_boot",
                "urls_processed": run.urls_processed,
                "error_count": run.error_count,
            },
            actor=run_event_types.ACTOR_SYSTEM,
        )
        orphan_info.append((run.id, run.shop.name, run.phase))
        logger.info("scrape_run %d -> failed (reason=orphan_on_boot)", run.id)
    session.flush()
    return orphan_info


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
        .limit(1)
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
    # Terminal-state guard: a reaped run is final. Late progress writes
    # from a spider that hadn't yet noticed the reap must not undo the
    # transition. Allow 'paused' so the heartbeat keeps ticking during
    # a pause and the reaper doesn't kill an idle-but-alive run.
    if run.status not in ("running", "paused"):
        return
    run.urls_processed = urls_processed
    run.last_heartbeat = datetime.now(UTC)
    session.flush()


def increment_scrape_run_stats(
    session: Session,
    run_id: int,
    items_added: int = 0,
    items_updated: int = 0,
    errors_4xx: int = 0,
    errors_5xx: int = 0,
    error_count: int = 0,
) -> None:
    run = session.get(ScrapeRun, run_id)
    if run is None:
        return
    run.items_added += items_added
    run.items_updated += items_updated
    run.errors_4xx += errors_4xx
    run.errors_5xx += errors_5xx
    run.error_count += error_count
    session.flush()


# --- Scan orchestration helpers ---


def check_discover_freshness(
    session: Session,
    shop_id: int,
    shop_name: str,
    discover_config: Any,
) -> list[str]:
    """Check if discovery is fresh enough. Raises RuntimeError if no URLs exist.
    Returns list of warning messages for stale discoveries."""
    # Normalize to dict for iteration
    if hasattr(discover_config, "model_dump"):
        config_dict = discover_config.model_dump(exclude_none=True)
    elif isinstance(discover_config, dict):
        config_dict = discover_config
    else:
        config_dict = {}

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
        strategy_conf = config_dict.get(strategy)
        if strategy_conf is None:
            continue
        max_age = (
            strategy_conf.get("max_age_hours")
            if isinstance(strategy_conf, dict)
            else getattr(strategy_conf, "max_age_hours", None)
        )
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


def _resolve_entity_fks(
    session: Session,
    issues: list[dict[str, str | int | None]],
    shop_id: int,
) -> None:
    """Resolve url strings to shop_book_id / discovered_url_id FKs in-place."""
    urls: set[str] = {
        str(i["url"])
        for i in issues
        if i.get("url") and not i.get("shop_book_id") and not i.get("discovered_url_id")
    }
    if not urls:
        return
    sb_rows = session.execute(
        select(ShopBook.url, ShopBook.id).where(
            ShopBook.shop_id == shop_id, ShopBook.url.in_(urls)
        )
    ).all()
    shop_book_by_url = {url: sid for url, sid in sb_rows}
    leftover = urls - shop_book_by_url.keys()
    du_by_url: dict[str, int] = {}
    if leftover:
        norm_map = {url: normalize_url(str(url)) for url in leftover}
        rev = {v: k for k, v in norm_map.items()}
        du_rows = session.execute(
            select(DiscoveredUrl.normalized_url, DiscoveredUrl.id).where(
                DiscoveredUrl.shop_id == shop_id,
                DiscoveredUrl.normalized_url.in_(norm_map.values()),
            )
        ).all()
        for normalized, du_id in du_rows:
            raw = rev.get(normalized)
            if raw is not None:
                du_by_url[raw] = du_id
    for issue in issues:
        if issue.get("shop_book_id") or issue.get("discovered_url_id"):
            continue
        url = issue.get("url")
        if url and url in shop_book_by_url:
            issue["shop_book_id"] = shop_book_by_url[str(url)]
        elif url and url in du_by_url:
            issue["discovered_url_id"] = du_by_url[str(url)]


def upsert_validation_issues(
    session: Session,
    issues: list[dict[str, str | int | None]],
    shop_id: int,
    run_id: int,
) -> None:
    """Upsert detected issues as canonical rows (one per entity×field×issue_type).

    On first detection: INSERT with lifecycle_state='new', run_count=1.
    On re-detection of open/ack/snoozed: UPDATE last_seen_run_id, run_count++.
    On re-detection of resolved: reset to 'new', clear resolved_at.
    Snoozed issues whose snoozed_until has passed are reset to 'new'.
    """
    if not issues:
        return
    _resolve_entity_fks(session, issues, shop_id)

    import sqlalchemy as sa

    sb_issues = [i for i in issues if i.get("shop_book_id")]
    du_issues = [
        i
        for i in issues
        if i.get("discovered_url_id") and not i.get("shop_book_id")
    ]
    url_issues = [
        i
        for i in issues
        if not i.get("shop_book_id") and not i.get("discovered_url_id")
    ]

    def _make_values(
        batch: list[dict[str, str | int | None]],
    ) -> list[dict[str, object]]:
        return [
            {
                "shop_id": shop_id,
                "last_seen_run_id": run_id,
                "first_seen_run_id": run_id,
                "url": str(i.get("url") or ""),
                "field": str(i.get("field") or ""),
                "issue": str(i.get("issue") or ""),
                "raw_value": i.get("raw_value"),
                "shop_book_id": i.get("shop_book_id"),
                "discovered_url_id": i.get("discovered_url_id"),
                "lifecycle_state": "new",
                "run_count": 1,
            }
            for i in batch
        ]

    excluded = pg_insert(ValidationIssue).excluded
    _on_conflict_set = {
        "last_seen_run_id": excluded.last_seen_run_id,
        "run_count": ValidationIssue.run_count + 1,
        "raw_value": excluded.raw_value,
        "lifecycle_state": sa.case(
            (ValidationIssue.lifecycle_state == "resolved", sa.literal("new")),
            (
                sa.and_(
                    ValidationIssue.lifecycle_state == "snoozed",
                    ValidationIssue.snoozed_until <= sa.func.now(),
                ),
                sa.literal("new"),
            ),
            else_=ValidationIssue.lifecycle_state,
        ),
        "resolved_at": sa.case(
            (ValidationIssue.lifecycle_state == "resolved", sa.null()),
            else_=ValidationIssue.resolved_at,
        ),
    }

    if sb_issues:
        stmt = pg_insert(ValidationIssue).values(_make_values(sb_issues))
        stmt = stmt.on_conflict_do_update(
            index_elements=["shop_book_id", "field", "issue"],
            index_where=ValidationIssue.shop_book_id.isnot(None),
            set_=_on_conflict_set,
        )
        session.execute(stmt)

    if du_issues:
        stmt = pg_insert(ValidationIssue).values(_make_values(du_issues))
        stmt = stmt.on_conflict_do_update(
            index_elements=["discovered_url_id", "field", "issue"],
            index_where=ValidationIssue.discovered_url_id.isnot(None),
            set_=_on_conflict_set,
        )
        session.execute(stmt)

    if url_issues:
        stmt = pg_insert(ValidationIssue).values(_make_values(url_issues))
        stmt = stmt.on_conflict_do_update(
            index_elements=["url", "field", "issue"],
            index_where=sa.and_(
                ValidationIssue.shop_book_id.is_(None),
                ValidationIssue.discovered_url_id.is_(None),
            ),
            set_=_on_conflict_set,
        )
        session.execute(stmt)


def resolve_gone_issues(session: Session, shop_id: int, run_id: int) -> int:
    """Mark open issues not detected in run_id as resolved.

    Returns the number of rows updated.
    """
    import sqlalchemy as sa

    now = datetime.now(UTC)
    result = session.execute(
        sa.update(ValidationIssue)
        .where(
            ValidationIssue.shop_id == shop_id,
            ValidationIssue.last_seen_run_id != run_id,
            ValidationIssue.lifecycle_state.in_(["new", "acknowledged", "snoozed"]),
        )
        .values(lifecycle_state="resolved", resolved_at=now)
    )
    return result.rowcount  # type: ignore[return-value]


def acknowledge_validation_issue(session: Session, issue_id: int) -> bool:
    """Mark an issue as acknowledged. Returns True if updated."""
    issue = session.get(ValidationIssue, issue_id)
    if issue is None:
        return False
    issue.lifecycle_state = "acknowledged"
    issue.acknowledged_at = datetime.now(UTC)
    session.flush()
    return True


def acknowledge_validation_issues_bulk(
    session: Session,
    issue_type: str | None = None,
    state: str | None = None,
    shop_id: int | None = None,
    run_id: int | None = None,
    q: str = "",
) -> int:
    """Bulk-acknowledge open issues matching the filter set. Returns count updated.

    Any combination of filters is allowed. Passing no filters at all
    acknowledges every open issue (callers wanting the global 'ack all
    open' behaviour rely on this).
    """
    from sqlalchemy import or_

    from book_scraper.db.models import ShopBook

    now = datetime.now(UTC)
    query = session.query(ValidationIssue).filter(
        ValidationIssue.lifecycle_state != "already_seen"
    )
    if issue_type is not None:
        query = query.filter(ValidationIssue.issue == issue_type)
    if state in {"new", "recurring"}:
        query = query.filter(ValidationIssue.lifecycle_state == state)
    if shop_id is not None or q:
        query = query.join(ScrapeRun, ValidationIssue.scrape_run_id == ScrapeRun.id)
    if shop_id is not None:
        query = query.filter(ScrapeRun.shop_id == shop_id)
    if run_id is not None:
        query = query.filter(ValidationIssue.scrape_run_id == run_id)
    if q:
        pattern = f"%{q}%"
        query = query.outerjoin(
            ShopBook, ValidationIssue.shop_book_id == ShopBook.id
        ).filter(or_(ValidationIssue.url.ilike(pattern), ShopBook.title.ilike(pattern)))
    issues = query.all()
    for issue in issues:
        issue.lifecycle_state = "already_seen"
        issue.acknowledged_at = now
    session.flush()
    return len(issues)


def delete_validation_issues_matching(
    session: Session,
    issue_type: str | None = None,
    state: str | None = None,
    shop_id: int | None = None,
    run_id: int | None = None,
    q: str = "",
) -> int:
    """Hard-delete validation issues matching the filter. Returns count deleted.

    At least one filter must be set — a guardrail to prevent the UI
    from wiping the whole table with an unintended empty request.
    """
    from sqlalchemy import or_

    from book_scraper.db.models import ShopBook

    if not (issue_type or state or shop_id or run_id or q):
        raise ValueError(
            "delete_validation_issues_matching requires at least one filter"
        )

    query = session.query(ValidationIssue)
    if issue_type is not None:
        query = query.filter(ValidationIssue.issue == issue_type)
    if state in {"new", "recurring", "already_seen"}:
        query = query.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        query = query.filter(ValidationIssue.lifecycle_state != "already_seen")
    if shop_id is not None or q:
        query = query.join(ScrapeRun, ValidationIssue.scrape_run_id == ScrapeRun.id)
    if shop_id is not None:
        query = query.filter(ScrapeRun.shop_id == shop_id)
    if run_id is not None:
        query = query.filter(ValidationIssue.scrape_run_id == run_id)
    if q:
        pattern = f"%{q}%"
        query = query.outerjoin(
            ShopBook, ValidationIssue.shop_book_id == ShopBook.id
        ).filter(or_(ValidationIssue.url.ilike(pattern), ShopBook.title.ilike(pattern)))
    ids = [i.id for i in query.all()]
    if not ids:
        return 0
    session.query(ValidationIssue).filter(ValidationIssue.id.in_(ids)).delete(
        synchronize_session=False
    )
    session.flush()
    return len(ids)


def get_urls_already_scraped(session: Session, shop_id: int) -> set[str]:
    """Return URLs already scraped (marked as 'product' in discovered_urls)."""
    return set(
        row[0]
        for row in session.query(DiscoveredUrl.url)
        .filter(
            DiscoveredUrl.shop_id == shop_id,
            DiscoveredUrl.url_type == "product",
        )
        .all()
    )


# --- Scrape URL Items ---


def prepare_scrape_url_items(
    session: Session,
    shop_id: int,
    run_id: int,
    url_records: "list[DiscoveredUrl]",
) -> None:
    """Batch-insert pending scrape_url_items for a new scan run.

    Persists the work queue to DB so the spider can resume after a crash.
    Uses each DiscoveredUrl.url_type as the item's url_type (defaults to 'product').
    ON CONFLICT DO NOTHING guards against duplicate inserts if two spiders
    race to populate the same run.
    """
    if not url_records:
        return
    rows = [
        {
            "run_id": run_id,
            "shop_id": shop_id,
            "discovered_url_id": rec.id,
            "url": rec.url,
            "url_type": rec.url_type or "product",
            "status": "pending",
        }
        for rec in url_records
    ]
    stmt = (
        pg_insert(ScrapeUrlItem)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["run_id", "url"])
    )
    session.execute(stmt)


def get_pending_scrape_url_items(session: Session, run_id: int) -> list[dict[str, Any]]:
    """Return all pending items for a run as dicts {id, url, discovered_url_id}."""
    rows = (
        session.query(ScrapeUrlItem)
        .filter(ScrapeUrlItem.run_id == run_id, ScrapeUrlItem.status == "pending")
        .all()
    )
    return [
        {
            "id": r.id,
            "url": r.url,
            "url_type": r.url_type,
            "discovered_url_id": r.discovered_url_id,
        }
        for r in rows
    ]


def mark_scrape_url_item_processing(
    session: Session,
    item_id: int,
    dispatched_at: float,
    request_delay_s: float | None = None,
    delay_source: str | None = None,
) -> None:
    """Mark a scrape_url_item in-flight: status=processing + claimed_at.

    Called from HttpxMiddleware.process_request the moment the request
    goes out, so the dashboard can surface "currently scraping" rows.

    `request_delay_s` and `delay_source` capture the per-request delay
    telemetry (live observability spec). `delay_source` records where
    the value came from so the dashboard can label it honestly.
    """
    item = session.get(ScrapeUrlItem, item_id)
    if item:
        run = session.get(ScrapeRun, item.run_id)
        if run is not None and run.status != "running":
            return
        item.status = "processing"
        item.claimed_at = datetime.fromtimestamp(dispatched_at, tz=UTC)
        # `attempts` ticks once per dispatch cycle. Scrapy's RetryMiddleware
        # re-issues without re-claiming, so internal retries don't bump
        # this — see scrape_url_items.retry_count for that count.
        item.attempts = (item.attempts or 0) + 1
        if request_delay_s is not None:
            item.request_delay_s = request_delay_s
        if delay_source is not None:
            item.delay_source = delay_source
        session.flush()


def record_scrape_failure(
    session: Session,
    *,
    scrape_url_item: ScrapeUrlItem,
    error_reason: str | None,
    http_status: int | None,
    response_bytes: int | None = None,
    error_detail: str | None = None,
    occurred_at: datetime | None = None,
) -> ScrapeFailure:
    """Append a `scrape_failures` row for a failure event.

    Append-only by design — every call inserts a new row, ordered by
    `occurred_at`. Retries get their own rows; lifecycle / acks live on
    each failure event rather than on the queue row. The single writer
    is the spider/repo pair, so accidental dupes are a real bug worth
    surfacing in the data, not papering over with idempotency tricks.
    """
    failure = ScrapeFailure(
        scrape_url_item_id=scrape_url_item.id,
        run_id=scrape_url_item.run_id,
        shop_id=scrape_url_item.shop_id,
        url=scrape_url_item.url,
        discovered_url_id=scrape_url_item.discovered_url_id,
        occurred_at=occurred_at or datetime.now(UTC),
        error_reason=error_reason,
        http_status=http_status,
        response_bytes=response_bytes,
        error_detail=error_detail,
    )
    session.add(failure)
    session.flush()
    return failure


def mark_scrape_url_item_response(
    session: Session,
    item_id: int,
    *,
    success: bool,
    http_status: int | None,
    received_at: float | None,
    response_bytes: int | None = None,
    error_reason: str | None = None,
    url_type: str | None = None,
    retry_count: int | None = None,
) -> None:
    """Immediate per-response write — owns terminal state for an item.

    Sets status to 'done' or 'failed' and stamps done_at, http_status, and
    response_bytes in a single UPDATE. PR 3 of the migration: failure
    detail (`error_reason`) is no longer written to the queue row; the
    `scrape_failures` event log carries it.

    `retry_count` (when provided) reflects the value of
    `request.meta["retry_times"]` after RetryMiddleware reissued the
    request. 0 means the response landed on the first attempt; values
    above 0 mean transient backend pressure was papered over by retries.
    """
    item = session.get(ScrapeUrlItem, item_id)
    if item is None:
        return
    # Terminal-state guard: if the run was reaped between dispatch and
    # response, skip the write. The reaper has already flipped any
    # `processing` row to `failed/run_aborted` via
    # `abort_processing_scrape_url_items`; overriding it here would
    # resurrect the row.
    run = session.get(ScrapeRun, item.run_id)
    if run is not None and run.status != "running":
        return
    item.status = "done" if success else "failed"
    item.done_at = (
        datetime.fromtimestamp(received_at, tz=UTC)
        if received_at is not None
        else datetime.now(UTC)
    )
    if http_status is not None:
        item.http_status = http_status
    if response_bytes is not None:
        item.response_bytes = response_bytes
    if url_type is not None:
        item.url_type = url_type
    if retry_count is not None:
        item.retry_count = retry_count
    session.flush()
    if not success:
        record_scrape_failure(
            session,
            scrape_url_item=item,
            error_reason=error_reason,
            http_status=http_status,
            response_bytes=response_bytes,
            occurred_at=item.done_at,
        )


def mark_scrape_url_item_done(
    session: Session,
    item_id: int,
    http_status: int | None = None,
    error_reason: str | None = None,
    dispatched_at: float | None = None,
    received_at: float | None = None,
    url_type: str | None = None,
) -> None:
    """Mark a scrape_url_item as done.

    `received_at` is the unix timestamp captured by the spider when the
    response actually arrived. We use it to stamp `done_at` rather than
    `datetime.now(UTC)`, because progress flushes happen in batches —
    using `now()` would lump every URL in a batch onto the same flush
    timestamp and inflate measured durations.
    """
    item = session.get(ScrapeUrlItem, item_id)
    if item:
        item.status = "done"
        item.done_at = (
            datetime.fromtimestamp(received_at, tz=UTC)
            if received_at is not None
            else datetime.now(UTC)
        )
        if dispatched_at is not None and item.claimed_at is None:
            item.claimed_at = datetime.fromtimestamp(dispatched_at, tz=UTC)
        if http_status is not None:
            item.http_status = http_status
        # PR 3: scrape_url_items.error_reason was dropped. Caller's
        # `error_reason` arg is ignored for done rows (success); on the
        # rare done-with-error path we'd record a scrape_failures event.
        if url_type is not None:
            item.url_type = url_type
        session.flush()


def mark_scrape_url_item_failed(
    session: Session,
    item_id: int,
    http_status: int | None = None,
    error_reason: str | None = None,
    dispatched_at: float | None = None,
    received_at: float | None = None,
    url_type: str | None = None,
) -> None:
    """Mark a scrape_url_item as failed. See `mark_scrape_url_item_done`
    for the rationale behind `received_at`."""
    item = session.get(ScrapeUrlItem, item_id)
    if item:
        item.status = "failed"
        item.done_at = (
            datetime.fromtimestamp(received_at, tz=UTC)
            if received_at is not None
            else datetime.now(UTC)
        )
        if dispatched_at is not None and item.claimed_at is None:
            item.claimed_at = datetime.fromtimestamp(dispatched_at, tz=UTC)
        if http_status is not None:
            item.http_status = http_status
        if url_type is not None:
            item.url_type = url_type
        session.flush()
        # PR 3: error_reason lives only in scrape_failures.
        record_scrape_failure(
            session,
            scrape_url_item=item,
            error_reason=error_reason,
            http_status=http_status,
            occurred_at=item.done_at,
        )


def fetch_retryable_failed_items(
    session: Session,
    run_id: int,
    cap: int,
) -> list[ScrapeUrlItem]:
    """Return failed items on this run with attempts < cap.

    Used by the end-of-run retry sweep. No filter on `error_reason` —
    every failed item under the cap gets one more dispatch chance.
    """
    return list(
        session.query(ScrapeUrlItem)
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status == "failed",
            ScrapeUrlItem.attempts < cap,
        )
        .all()
    )


def reset_failed_items_to_pending(
    session: Session,
    item_ids: list[int],
    *,
    reset_attempts: bool = False,
) -> int:
    """Flip given failed items back to `pending` and clear stale
    terminal metadata so the next claim starts fresh.

    Clears `claimed_at`, `done_at`, `http_status`, and `response_bytes`
    — these were stamped by the previous failed dispatch and would
    otherwise show up on the pending row in the History card. The
    underlying scrape_failures rows stay (they're an append-only
    event log).

    `reset_attempts=False` (default, end-of-run sweep): leaves the
    counter alone — the next claim ticks it.
    `reset_attempts=True` (operator manual retry): zeros the counter
    so capped items get a fresh window.

    Returns the number of items updated.
    """
    if not item_ids:
        return 0
    values: dict[str, Any] = {
        "status": "pending",
        "claimed_at": None,
        "done_at": None,
        "http_status": None,
        "response_bytes": None,
    }
    if reset_attempts:
        values["attempts"] = 0
    stmt = (
        update(ScrapeUrlItem)
        .where(ScrapeUrlItem.id.in_(item_ids))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    session.flush()
    rowcount = getattr(result, "rowcount", 0)
    return int(rowcount) if rowcount is not None else 0


def reset_processing_scrape_url_items(session: Session, run_id: int) -> int:
    """Reset 'processing' items back to 'pending' for crash recovery.

    Returns the number of items reset.
    """
    items = (
        session.query(ScrapeUrlItem)
        .filter(ScrapeUrlItem.run_id == run_id, ScrapeUrlItem.status == "processing")
        .all()
    )
    for item in items:
        item.status = "pending"
        item.claimed_at = None
    session.flush()
    return len(items)


def insert_scrape_url_item(
    session: Session,
    run_id: int,
    shop_id: int,
    discovered_url_id: int | None,
    url: str,
    url_type: str = "product",
) -> ScrapeUrlItem:
    """Insert a single pending scrape_url_item mid-run.

    Used to enqueue newly-discovered URLs so the same run processes them
    as a second pass. Idempotent: if an item for (run_id, url) already
    exists, returns it unchanged.
    """
    existing = (
        session.query(ScrapeUrlItem).filter_by(run_id=run_id, url=url).one_or_none()
    )
    if existing is not None:
        return existing
    item = ScrapeUrlItem(
        run_id=run_id,
        shop_id=shop_id,
        discovered_url_id=discovered_url_id,
        url=url,
        url_type=url_type,
        status="pending",
    )
    session.add(item)
    session.flush()
    return item


# --- CronJob CRUD ---


def list_cron_jobs(session: Session) -> list[CronJob]:
    """Return all cron jobs, ordered by id."""
    return list(session.execute(select(CronJob).order_by(CronJob.id)).scalars().all())


def get_cron_job(session: Session, job_id: int) -> CronJob | None:
    return session.get(CronJob, job_id)


def create_cron_job(
    session: Session,
    shop_id: int,
    phase: str,
    strategy: str | None,
    args: str,
    cron_expression: str,
    enabled: bool = True,
    chain_to_job_id: int | None = None,
) -> CronJob:
    job = CronJob(
        shop_id=shop_id,
        phase=phase,
        strategy=strategy,
        args=args,
        cron_expression=cron_expression,
        enabled=enabled,
        chain_to_job_id=chain_to_job_id,
    )
    session.add(job)
    session.flush()
    return job


def update_cron_job(
    session: Session,
    job_id: int,
    **fields: Any,
) -> None:
    """Update allowed fields: phase, strategy, args, cron_expression, enabled, chain_to_job_id."""  # noqa: E501
    allowed = {
        "phase",
        "strategy",
        "args",
        "cron_expression",
        "enabled",
        "chain_to_job_id",
    }
    job = session.get(CronJob, job_id)
    if job is None:
        return
    for k, v in fields.items():
        if k in allowed:
            setattr(job, k, v)
    session.flush()


def toggle_cron_job(session: Session, job_id: int) -> None:
    job = session.get(CronJob, job_id)
    if job is None:
        return
    job.enabled = not job.enabled
    session.flush()


def delete_cron_job(session: Session, job_id: int) -> None:
    job = session.get(CronJob, job_id)
    if job is not None:
        session.delete(job)
        session.flush()


def update_cron_job_last_run(
    session: Session,
    job_id: int,
    when: datetime,
) -> None:
    job = session.get(CronJob, job_id)
    if job is None:
        return
    job.last_run_at = when
    session.flush()


def mark_cron_job_ran_if_matches(
    session: Session,
    shop_id: int,
    phase: str,
    strategy: str | None = None,
) -> None:
    """Update last_run_at on every cron_job matching (shop_id, phase, strategy).

    No-op if no cron_job matches. Multiple matches are all updated — the
    schema permits duplicate (shop_id, phase, strategy) rows (e.g. a
    sitemap scan scheduled for morning + evening).
    """
    strategy_clause = (
        CronJob.strategy.is_(None) if strategy is None else CronJob.strategy == strategy
    )
    stmt = select(CronJob).where(
        CronJob.shop_id == shop_id,
        CronJob.phase == phase,
        strategy_clause,
    )
    jobs = list(session.execute(stmt).scalars().all())
    now = datetime.now(UTC)
    for job in jobs:
        job.last_run_at = now
    if jobs:
        session.flush()
