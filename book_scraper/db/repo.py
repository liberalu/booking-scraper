import os
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from book_scraper.db.models import (
    Category,
    CronJob,
    DiscoveredUrl,
    Price,
    ScrapeRun,
    ScrapeUrlItem,
    Shop,
    ShopAuthor,
    ShopBook,
    ShopBookAttribute,
    ShopBookAuthor,
    ShopBookFieldUpdate,
    ValidationIssue,
)
from book_scraper.spiders.vaga.parsers import infer_shop_book_type
from book_scraper.url_utils import normalize_url

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
        row = existing.get(aid)
        if row is None:
            session.add(
                ShopBookAuthor(shop_book_id=shop_book_id, author_id=aid, position=pos)
            )
        elif row.position != pos:
            row.position = pos


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
    run_id: int | None = None,
) -> tuple[ShopBook, bool, Decimal | None, list[dict[str, Any]]]:
    """Upsert a shop_book. Returns (shop_book, created, old_price, changes)."""
    stmt = select(ShopBook).where(ShopBook.shop_id == shop_id, ShopBook.url == url)
    shop_book = session.execute(stmt).scalar_one_or_none()
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
            last_run_id=run_id,
            last_run_action="created",
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
        tracked_fields = {
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
            "image_url": image_url,
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
    """
    normalized = normalize_url(url)
    now = datetime.now(UTC)
    stmt = select(DiscoveredUrl).where(
        DiscoveredUrl.shop_id == shop_id,
        DiscoveredUrl.normalized_url == normalized,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is not None:
        existing.last_seen_at = now
        if run_id is not None:
            existing.last_seen_run_id = run_id
        if shop_book_id is not None and existing.shop_book_id != shop_book_id:
            existing.shop_book_id = shop_book_id
        session.flush()
        return existing
    record = DiscoveredUrl(
        shop_id=shop_id,
        url=url,
        normalized_url=normalized,
        source=source,
        first_seen_at=now,
        last_seen_at=now,
        last_seen_run_id=run_id,
        shop_book_id=shop_book_id,
    )
    session.add(record)
    session.flush()
    return record


def link_discovered_url_to_shop_book(
    session: Session,
    shop_id: int,
    url: str,
    shop_book_id: int,
    run_id: int | None = None,
) -> DiscoveredUrl | None:
    """Idempotently attach a shop_book to its discovered URL row.

    Returns the row (creating one if missing — useful when a shop_book
    is upserted via a path that didn't go through discovery yet).
    """
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
        first_seen_at=now,
        last_seen_at=now,
        last_seen_run_id=run_id,
        shop_book_id=shop_book_id,
    )
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
        last_heartbeat=datetime.now(UTC),
        pid=os.getpid(),
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


def find_resumable_run(
    session: Session,
    shop_id: int,
    phase: str,
) -> "ScrapeRun | None":
    """Find a 'running' scrape run with pending scrape_url_items.

    Such a run was crash-interrupted and can be resumed: the queue still
    holds unprocessed URLs. Returns None if no resumable run exists.
    """
    from sqlalchemy import exists

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
            ScrapeRun.status == "running",
            has_pending,
        )
        .order_by(ScrapeRun.started_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def mark_orphan_runs_failed(session: Session) -> int:
    """Fail every run still flagged 'running'. Call on scraper boot —
    any row still 'running' belongs to a process the restart killed."""
    now = datetime.now(UTC)
    stmt = select(ScrapeRun).where(ScrapeRun.status == "running")
    orphans = list(session.execute(stmt).scalars().all())
    for run in orphans:
        run.status = "failed"
        run.finished_at = now
    session.flush()
    return len(orphans)


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


def bulk_insert_validation_issues(
    session: Session,
    issues: list[dict[str, str | int | None]],
    shop_id: int | None = None,
) -> None:
    """Insert a batch of validation issues, resolving shop_book/discovered_url FKs.

    When `shop_id` is provided, each issue's `url` is resolved to a
    `shop_book_id` first; failing that, to a `discovered_url_id`. If the
    caller already populated either FK on the dict it is left alone.
    """
    if not issues:
        return

    if shop_id is not None:
        urls = {issue["url"] for issue in issues if issue.get("url")}
        shop_book_by_url: dict[str, int] = {}
        du_by_url: dict[str, int] = {}
        if urls:
            rows = session.execute(
                select(ShopBook.url, ShopBook.id).where(
                    ShopBook.shop_id == shop_id,
                    ShopBook.url.in_(urls),
                )
            ).all()
            for url, shop_book_id in rows:
                shop_book_by_url[url] = shop_book_id
            # Only look up discovered_urls for the leftover set.
            leftover = urls - shop_book_by_url.keys()
            if leftover:
                normalized_map = {url: normalize_url(str(url)) for url in leftover}
                rev = {v: k for k, v in normalized_map.items()}
                du_rows = session.execute(
                    select(DiscoveredUrl.normalized_url, DiscoveredUrl.id).where(
                        DiscoveredUrl.shop_id == shop_id,
                        DiscoveredUrl.normalized_url.in_(normalized_map.values()),
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
                issue["shop_book_id"] = shop_book_by_url[url]
            elif url and url in du_by_url:
                issue["discovered_url_id"] = du_by_url[url]

    _assign_lifecycle_states(session, issues)
    session.add_all([ValidationIssue(**issue) for issue in issues])


def _assign_lifecycle_states(
    session: Session,
    issues: list[dict[str, str | int | None]],
) -> None:
    """Stamp each issue with `new` or `recurring` based on prior history.

    Lifecycle rule: an issue is `recurring` if the SAME (entity, field,
    issue) triple has been seen in a previous scrape run — including
    when the previous occurrence was acknowledged (i.e. acknowledged
    issues that re-appear surface as `new` instead of `recurring` so
    they get triage attention; this matches the spec's
    "previously-acknowledged issue that reappears surfaces as new".
    """
    if not issues:
        return

    shop_book_keys: set[tuple[int, str, str]] = set()
    du_keys: set[tuple[int, str, str]] = set()
    url_keys: set[tuple[str, str, str]] = set()
    for issue in issues:
        field = str(issue.get("field") or "")
        issue_type = str(issue.get("issue") or "")
        if issue.get("shop_book_id"):
            shop_book_keys.add((int(issue["shop_book_id"]), field, issue_type))  # type: ignore[arg-type]
        elif issue.get("discovered_url_id"):
            du_keys.add((int(issue["discovered_url_id"]), field, issue_type))  # type: ignore[arg-type]
        else:
            url_keys.add((str(issue.get("url") or ""), field, issue_type))

    seen_shop_book: set[tuple[int, str, str]] = set()
    seen_du: set[tuple[int, str, str]] = set()
    seen_url: set[tuple[str, str, str]] = set()

    # Look up prior occurrences. We filter on unacknowledged rows only
    # so an acknowledged-then-reappearing issue comes back as `new`.
    if shop_book_keys:
        rows = session.execute(
            select(
                ValidationIssue.shop_book_id,
                ValidationIssue.field,
                ValidationIssue.issue,
            )
            .where(
                ValidationIssue.shop_book_id.in_({k[0] for k in shop_book_keys}),
                ValidationIssue.acknowledged_at.is_(None),
            )
            .distinct()
        ).all()
        seen_shop_book = {(r.shop_book_id, r.field, r.issue) for r in rows}
    if du_keys:
        rows = session.execute(
            select(
                ValidationIssue.discovered_url_id,
                ValidationIssue.field,
                ValidationIssue.issue,
            )
            .where(
                ValidationIssue.discovered_url_id.in_({k[0] for k in du_keys}),
                ValidationIssue.acknowledged_at.is_(None),
            )
            .distinct()
        ).all()
        seen_du = {(r.discovered_url_id, r.field, r.issue) for r in rows}
    if url_keys:
        rows = session.execute(
            select(
                ValidationIssue.url,
                ValidationIssue.field,
                ValidationIssue.issue,
            )
            .where(
                ValidationIssue.shop_book_id.is_(None),
                ValidationIssue.discovered_url_id.is_(None),
                ValidationIssue.url.in_({k[0] for k in url_keys}),
                ValidationIssue.acknowledged_at.is_(None),
            )
            .distinct()
        ).all()
        seen_url = {(r.url, r.field, r.issue) for r in rows}

    for issue in issues:
        field = str(issue.get("field") or "")
        issue_type = str(issue.get("issue") or "")
        state = "new"
        if issue.get("shop_book_id"):
            if (int(issue["shop_book_id"]), field, issue_type) in seen_shop_book:  # type: ignore[arg-type]
                state = "recurring"
        elif issue.get("discovered_url_id"):
            if (int(issue["discovered_url_id"]), field, issue_type) in seen_du:  # type: ignore[arg-type]
                state = "recurring"
        else:
            if (str(issue.get("url") or ""), field, issue_type) in seen_url:
                state = "recurring"
        issue.setdefault("lifecycle_state", state)


def acknowledge_validation_issue(session: Session, issue_id: int) -> bool:
    """Mark an issue as already_seen. Returns True if updated."""
    issue = session.get(ValidationIssue, issue_id)
    if issue is None:
        return False
    issue.lifecycle_state = "already_seen"
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
    """
    for rec in url_records:
        session.add(
            ScrapeUrlItem(
                run_id=run_id,
                shop_id=shop_id,
                discovered_url_id=rec.id,
                url=rec.url,
                url_type=rec.url_type or "product",
                status="pending",
            )
        )
    session.flush()


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
            "discovered_url_id": r.discovered_url_id,
        }
        for r in rows
    ]


def mark_scrape_url_item_done(session: Session, item_id: int) -> None:
    """Mark a scrape_url_item as done."""
    item = session.get(ScrapeUrlItem, item_id)
    if item:
        item.status = "done"
        item.done_at = datetime.now(UTC)
        session.flush()


def mark_scrape_url_item_failed(session: Session, item_id: int) -> None:
    """Mark a scrape_url_item as failed."""
    item = session.get(ScrapeUrlItem, item_id)
    if item:
        item.status = "failed"
        item.done_at = datetime.now(UTC)
        session.flush()


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
) -> CronJob:
    job = CronJob(
        shop_id=shop_id,
        phase=phase,
        strategy=strategy,
        args=args,
        cron_expression=cron_expression,
        enabled=enabled,
    )
    session.add(job)
    session.flush()
    return job


def update_cron_job(
    session: Session,
    job_id: int,
    **fields: Any,
) -> None:
    """Update allowed fields: phase, strategy, args, cron_expression, enabled."""
    allowed = {"phase", "strategy", "args", "cron_expression", "enabled"}
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
    """Update last_run_at on the cron_job that matches (shop_id, phase, strategy).

    No-op if no cron_job matches. Used at end of scrape runs to keep the
    dashboard's 'last run' column current. Strategy matching is exact
    including NULL — a scan job has strategy=NULL; a discover_sitemap job
    has strategy='sitemap'.
    """
    strategy_clause = (
        CronJob.strategy.is_(None) if strategy is None else CronJob.strategy == strategy
    )
    stmt = select(CronJob).where(
        CronJob.shop_id == shop_id,
        CronJob.phase == phase,
        strategy_clause,
    )
    job = session.execute(stmt).scalar_one_or_none()
    if job is not None:
        job.last_run_at = datetime.now(UTC)
        session.flush()


def cleanup_scrape_url_items(session: Session, run_id: int) -> int:
    """Delete all scrape_url_items for a finished run.

    scrape_url_items is a staging table — rows are deleted when the run
    ends (completed or failed). Progress is already persisted to
    discovered_urls, shop_books, and prices via pipelines.

    Returns the number of rows deleted.
    """
    deleted = (
        session.query(ScrapeUrlItem)
        .filter(ScrapeUrlItem.run_id == run_id)
        .delete(synchronize_session=False)
    )
    session.flush()
    return deleted
