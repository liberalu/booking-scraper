import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from book_scraper.db.models import (
    Category,
    DiscoveredUrl,
    Listing,
    ListingAttribute,
    Price,
    ScrapeRun,
    Shop,
    ValidationIssue,
)
from book_scraper.url_utils import normalize_url


def _sync_attribute_rows(
    session: Session,
    listing: "Listing",
    properties: dict[str, Any],
) -> None:
    """Upsert (listing_id, key) rows in listing_attributes to match the
    provided dict.

    Missing keys leave existing rows alone so a partial scrape doesn't
    clobber previously-captured attributes. Only the keys present in
    `properties` are inserted/updated.
    """
    if not properties:
        return
    existing_rows = {
        row.key: row
        for row in session.query(ListingAttribute).filter_by(listing_id=listing.id)
    }
    for key, value in properties.items():
        str_value = None if value is None else str(value)
        row = existing_rows.get(key)
        if row is None:
            session.add(
                ListingAttribute(listing_id=listing.id, key=key, value=str_value)
            )
        elif row.value != str_value:
            row.value = str_value
    session.flush()


def upsert_shop(session: Session, name: str, base_url: str) -> Shop:
    stmt = select(Shop).where(Shop.name == name)
    shop = session.execute(stmt).scalar_one_or_none()
    if shop is None:
        shop = Shop(name=name, base_url=base_url)
        session.add(shop)
        session.flush()
    return shop


def _infer_listing_type(format: str | None) -> str:
    """Map a free-form `format` string to a listing_type enum value.

    Only audiobooks are currently marked as 'audio'. Ebook detection
    is deferred until the shops start emitting a recognisable ebook
    format string.
    """
    if format and format.lower() in {"audiobook", "audio", "audiobookas"}:
        return "audio"
    return "book"


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
    run_id: int | None = None,
) -> tuple[Listing, bool, Decimal | None, list[dict[str, Any]]]:
    """Upsert a listing. Returns (listing, created, old_price, changes)."""
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
            type=_infer_listing_type(format),
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
        session.add(listing)
        session.flush()
        if properties:
            _sync_attribute_rows(session, listing, properties)
        return listing, True, None, []
    else:
        old_price = listing.price
        listing.last_run_id = run_id
        listing.last_run_action = "updated"

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
            old_val = getattr(listing, field_name)
            if old_val != new_val:
                changes.append(
                    {
                        "field": field_name,
                        "old": str(old_val) if old_val is not None else None,
                        "new": str(new_val) if new_val is not None else None,
                    }
                )
            setattr(listing, field_name, new_val)

        for cond_field, cond_val in conditional_fields.items():
            if cond_val is not None:
                old_val = getattr(listing, cond_field)
                if old_val != cond_val:
                    changes.append(
                        {
                            "field": cond_field,
                            "old": str(old_val) if old_val is not None else None,
                            "new": str(cond_val) if cond_val is not None else None,
                        }
                    )
                setattr(listing, cond_field, cond_val)

        # Re-derive type from the authoritative `format` string (only
        # when a format was supplied — a PriceItem won't touch it).
        if format is not None:
            listing.type = _infer_listing_type(format)

        if categories is not None:
            listing.categories = categories
        if properties is not None:
            _sync_attribute_rows(session, listing, properties)
        if price is not None:
            listing.price = price
        if price_original is not None:
            listing.price_original = price_original
        listing.in_stock = in_stock
        listing.last_seen_at = now
        listing.is_active = True
        # Clear the transition stamp when a previously-vanished listing
        # comes back; keeps the "inactive_since" semantics meaningful.
        listing.inactive_since = None
        session.flush()
        return listing, False, old_price, changes


def insert_price(
    session: Session,
    listing_id: int,
    price: Decimal,
    price_original: Decimal | None,
    in_stock: bool,
    run_id: int | None = None,
) -> Price:
    record = Price(
        listing_id=listing_id,
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


def mark_listings_inactive(
    session: Session, shop_id: int, active_urls: set[str]
) -> int:
    """Mark listings not in active_urls as inactive. Returns count of deactivated.

    Stamps `inactive_since` with the transition time so the dashboard
    can show "inactive since <date>" and so downstream jobs can prune
    long-vanished listings.
    """
    stmt = select(Listing).where(
        Listing.shop_id == shop_id, Listing.is_active.is_(True)
    )
    listings = session.execute(stmt).scalars().all()
    now = datetime.now(UTC)
    count = 0
    for listing in listings:
        if listing.url not in active_urls:
            listing.is_active = False
            listing.inactive_since = now
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
    listing_id: int | None = None,
) -> DiscoveredUrl:
    """Upsert (shop_id, normalized_url).

    New rows record `first_seen_at = last_seen_at = now`. Repeat hits
    refresh `last_seen_at`, update `last_seen_run_id` when `run_id` is
    provided, and adopt a resolved `listing_id` when one is supplied.
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
        if listing_id is not None and existing.listing_id != listing_id:
            existing.listing_id = listing_id
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
        listing_id=listing_id,
    )
    session.add(record)
    session.flush()
    return record


def link_discovered_url_to_listing(
    session: Session,
    shop_id: int,
    url: str,
    listing_id: int,
    run_id: int | None = None,
) -> DiscoveredUrl | None:
    """Idempotently attach a listing to its discovered URL row.

    Returns the row (creating one if missing — useful when a listing
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
        if existing.listing_id != listing_id:
            existing.listing_id = listing_id
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
        listing_id=listing_id,
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
    """Insert a batch of validation issues, resolving listing/discovered_url FKs.

    When `shop_id` is provided, each issue's `url` is resolved to a
    `listing_id` first; failing that, to a `discovered_url_id`. If the
    caller already populated either FK on the dict it is left alone.
    """
    if not issues:
        return

    if shop_id is not None:
        urls = {issue["url"] for issue in issues if issue.get("url")}
        listing_by_url: dict[str, int] = {}
        du_by_url: dict[str, int] = {}
        if urls:
            rows = session.execute(
                select(Listing.url, Listing.id).where(
                    Listing.shop_id == shop_id,
                    Listing.url.in_(urls),
                )
            ).all()
            for url, listing_id in rows:
                listing_by_url[url] = listing_id
            # Only look up discovered_urls for the leftover set.
            leftover = urls - listing_by_url.keys()
            if leftover:
                normalized_map = {
                    url: normalize_url(str(url)) for url in leftover
                }
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
            if issue.get("listing_id") or issue.get("discovered_url_id"):
                continue
            url = issue.get("url")
            if url and url in listing_by_url:
                issue["listing_id"] = listing_by_url[url]
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

    listing_keys: set[tuple[int, str, str]] = set()
    du_keys: set[tuple[int, str, str]] = set()
    url_keys: set[tuple[str, str, str]] = set()
    for issue in issues:
        field = str(issue.get("field") or "")
        issue_type = str(issue.get("issue") or "")
        if issue.get("listing_id"):
            listing_keys.add((int(issue["listing_id"]), field, issue_type))  # type: ignore[arg-type]
        elif issue.get("discovered_url_id"):
            du_keys.add((int(issue["discovered_url_id"]), field, issue_type))  # type: ignore[arg-type]
        else:
            url_keys.add((str(issue.get("url") or ""), field, issue_type))

    seen_listing: set[tuple[int, str, str]] = set()
    seen_du: set[tuple[int, str, str]] = set()
    seen_url: set[tuple[str, str, str]] = set()

    # Look up prior occurrences. We filter on unacknowledged rows only
    # so an acknowledged-then-reappearing issue comes back as `new`.
    if listing_keys:
        rows = session.execute(
            select(
                ValidationIssue.listing_id,
                ValidationIssue.field,
                ValidationIssue.issue,
            )
            .where(
                ValidationIssue.listing_id.in_({k[0] for k in listing_keys}),
                ValidationIssue.acknowledged_at.is_(None),
            )
            .distinct()
        ).all()
        seen_listing = {(r.listing_id, r.field, r.issue) for r in rows}
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
                ValidationIssue.listing_id.is_(None),
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
        if issue.get("listing_id"):
            if (int(issue["listing_id"]), field, issue_type) in seen_listing:  # type: ignore[arg-type]
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
