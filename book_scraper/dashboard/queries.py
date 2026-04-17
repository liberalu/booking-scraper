import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session, joinedload

from book_scraper.db.models import (
    DiscoveredUrl,
    Listing,
    ListingChange,
    ListingFieldUpdate,
    Price,
    ScrapeRun,
    Shop,
    ValidationIssue,
)

STALE_HEARTBEAT_MINUTES = 5
DEAD_RUN_HOURS = 2


def _pid_alive(pid: int | None) -> bool | None:
    """Check if a process is alive. Returns None if PID not recorded."""
    if pid is None:
        return None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_run_health(run: ScrapeRun) -> str:
    """Return health status for a running scrape run.

    Returns: 'healthy', 'stale', 'dead', or '' for non-running runs.
    Relies on heartbeat only — PID check is unreliable across Docker
    containers (different PID namespaces).
    """
    if run.status != "running":
        return ""

    now = datetime.now(UTC)
    last_activity = run.last_heartbeat or run.started_at
    if last_activity is None:
        return "dead"
    elapsed = now - last_activity
    if elapsed > timedelta(hours=DEAD_RUN_HOURS):
        return "dead"
    if elapsed > timedelta(minutes=STALE_HEARTBEAT_MINUTES):
        return "stale"
    return "healthy"


def mark_stale_runs(session: Session) -> int:
    """Mark runs with no heartbeat for over DEAD_RUN_HOURS as failed."""
    cutoff = datetime.now(UTC) - timedelta(hours=DEAD_RUN_HOURS)
    stale = session.query(ScrapeRun).filter(ScrapeRun.status == "running").all()
    marked = 0
    for run in stale:
        last_activity = run.last_heartbeat or run.started_at
        if last_activity and last_activity < cutoff:
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            marked += 1
    if marked:
        session.commit()
    return marked


def get_overview_stats(session: Session) -> dict:
    total = session.query(func.count(Listing.id)).scalar() or 0
    active = (
        session.query(func.count(Listing.id))
        .filter(Listing.is_active.is_(True))
        .scalar()
        or 0
    )
    with_isbn = (
        session.query(func.count(Listing.id)).filter(Listing.isbn.isnot(None)).scalar()
        or 0
    )
    total_prices = session.query(func.count(Price.id)).scalar() or 0
    return {
        "total_listings": total,
        "active_listings": active,
        "with_isbn": with_isbn,
        "total_prices": total_prices,
    }


def get_recent_runs(session: Session, limit: int = 20) -> list[ScrapeRun]:
    return (
        session.query(ScrapeRun)
        .options(joinedload(ScrapeRun.shop))
        .order_by(ScrapeRun.started_at.desc())
        .limit(limit)
        .all()
    )


def get_run_detail(session: Session, run_id: int) -> ScrapeRun | None:
    return session.get(ScrapeRun, run_id)


def get_run_issue_summary(
    session: Session, run_id: int
) -> list[dict[str, Any]]:
    """Return validation issues for a run grouped by (field, issue) with counts."""
    rows = (
        session.query(
            ValidationIssue.field,
            ValidationIssue.issue,
            func.count(ValidationIssue.id).label("count"),
        )
        .filter(ValidationIssue.scrape_run_id == run_id)
        .group_by(ValidationIssue.field, ValidationIssue.issue)
        .order_by(func.count(ValidationIssue.id).desc())
        .all()
    )
    return [{"field": r.field, "issue": r.issue, "count": r.count} for r in rows]


def get_validation_summary(
    session: Session, state: str | None = None
) -> list[dict]:
    q = session.query(
        ValidationIssue.issue,
        func.count(ValidationIssue.id).label("count"),
    )
    if state in {"new", "recurring", "already_seen"}:
        q = q.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        q = q.filter(ValidationIssue.lifecycle_state != "already_seen")
    rows = (
        q.group_by(ValidationIssue.issue)
        .order_by(func.count(ValidationIssue.id).desc())
        .all()
    )
    return [{"issue_type": r.issue, "count": r.count} for r in rows]


def get_validation_issues_flat(
    session: Session,
    state: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> tuple[list[dict], int]:
    """Return (rows, total) for a given lifecycle state, paginated.

    Pulls the Listing title when a listing_id is set so the template
    can show a meaningful link instead of the raw URL.
    """
    q = session.query(ValidationIssue)
    if state in {"new", "recurring", "already_seen"}:
        q = q.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        q = q.filter(ValidationIssue.lifecycle_state != "already_seen")
    total = q.count()
    issues = (
        q.order_by(ValidationIssue.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    listing_ids = {i.listing_id for i in issues if i.listing_id}
    titles: dict[int, str] = {}
    if listing_ids:
        rows = (
            session.query(Listing.id, Listing.title)
            .filter(Listing.id.in_(listing_ids))
            .all()
        )
        titles = {row.id: row.title for row in rows}

    rows = [
        {
            "id": i.id,
            "url": i.url,
            "field": i.field,
            "issue": i.issue,
            "raw_value": i.raw_value,
            "scrape_run_id": i.scrape_run_id,
            "listing_id": i.listing_id,
            "listing_title": titles.get(i.listing_id) if i.listing_id else None,
            "discovered_url_id": i.discovered_url_id,
            "lifecycle_state": i.lifecycle_state,
            "acknowledged_at": i.acknowledged_at,
        }
        for i in issues
    ]
    return rows, total


def get_validation_lifecycle_counts(session: Session) -> dict[str, int]:
    rows = (
        session.query(
            ValidationIssue.lifecycle_state,
            func.count(ValidationIssue.id).label("count"),
        )
        .group_by(ValidationIssue.lifecycle_state)
        .all()
    )
    counts = {"new": 0, "recurring": 0, "already_seen": 0}
    for r in rows:
        counts[r.lifecycle_state] = r.count
    counts["open"] = counts["new"] + counts["recurring"]
    return counts


def get_validation_by_type(
    session: Session,
    issue_type: str,
    limit: int = 100,
    state: str | None = None,
    run_id: int | None = None,
) -> list[dict]:
    """Get validation issues with listing IDs resolved from URL."""
    q = session.query(ValidationIssue).filter(ValidationIssue.issue == issue_type)
    if state in {"new", "recurring", "already_seen"}:
        q = q.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        q = q.filter(ValidationIssue.lifecycle_state != "already_seen")
    if run_id is not None:
        q = q.filter(ValidationIssue.scrape_run_id == run_id)
    issues = q.order_by(ValidationIssue.id.desc()).limit(limit).all()
    # Resolve listing IDs by URL
    urls = {i.url for i in issues}
    url_to_listing = {}
    if urls:
        rows = (
            session.query(Listing.url, Listing.id, Listing.title)
            .filter(Listing.url.in_(urls))
            .all()
        )
        url_to_listing = {r.url: {"id": r.id, "title": r.title} for r in rows}

    result = []
    for issue in issues:
        listing = url_to_listing.get(issue.url)
        result.append(
            {
                "id": issue.id,
                "url": issue.url,
                "field": issue.field,
                "issue": issue.issue,
                "raw_value": issue.raw_value,
                "scrape_run_id": issue.scrape_run_id,
                "listing_id": listing["id"] if listing else None,
                "listing_title": listing["title"] if listing else None,
                "lifecycle_state": issue.lifecycle_state,
                "acknowledged_at": issue.acknowledged_at,
            }
        )
    return result


def search_listings(session: Session, query: str, limit: int = 50) -> list[Listing]:
    return (
        session.query(Listing)
        .filter(Listing.title.ilike(f"%{query}%"))
        .order_by(Listing.title)
        .limit(limit)
        .all()
    )


def get_field_updates(session: Session, listing_id: int) -> dict[str, datetime]:
    """Return {field: updated_at} for a listing's tracked fields."""
    rows = (
        session.query(ListingFieldUpdate)
        .filter(ListingFieldUpdate.listing_id == listing_id)
        .all()
    )
    return {r.field: r.updated_at for r in rows}


def get_price_history(session: Session, listing_id: int) -> list[Price]:
    return (
        session.query(Price)
        .filter(Price.listing_id == listing_id)
        .order_by(Price.scraped_at)
        .all()
    )


def get_price_changes(
    session: Session, days: int = 7, shop_id: int | None = None
) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    shop_filter = "AND l.shop_id = :shop_id" if shop_id else ""
    sql = text(f"""
        WITH ranked AS (
            SELECT
                p.listing_id,
                p.price,
                p.scraped_at,
                LAG(p.price) OVER (
                    PARTITION BY p.listing_id ORDER BY p.scraped_at
                ) AS prev_price
            FROM prices p
            JOIN listings l ON l.id = p.listing_id
            WHERE p.scraped_at >= :cutoff
            {shop_filter}
        ),
        changes AS (
            SELECT
                r.listing_id,
                l.title,
                r.prev_price,
                r.price AS new_price,
                r.price - r.prev_price AS change,
                r.scraped_at,
                ROW_NUMBER() OVER (
                    PARTITION BY r.listing_id, r.prev_price, r.price
                    ORDER BY r.scraped_at DESC
                ) AS rn
            FROM ranked r
            JOIN listings l ON l.id = r.listing_id
            WHERE r.prev_price IS NOT NULL
              AND r.price != r.prev_price
        )
        SELECT listing_id, title, prev_price, new_price, change,
               scraped_at
        FROM changes
        WHERE rn = 1
        ORDER BY ABS(change) DESC
        LIMIT 50
    """)
    params: dict[str, Any] = {"cutoff": cutoff}
    if shop_id:
        params["shop_id"] = shop_id
    rows = session.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def get_inventory_stats(session: Session) -> dict:
    total = session.query(func.count(Listing.id)).scalar() or 0
    active = (
        session.query(func.count(Listing.id))
        .filter(Listing.is_active.is_(True))
        .scalar()
        or 0
    )
    with_isbn = (
        session.query(func.count(Listing.id)).filter(Listing.isbn.isnot(None)).scalar()
        or 0
    )
    with_author = (
        session.query(func.count(Listing.id))
        .filter(Listing.author.isnot(None))
        .scalar()
        or 0
    )
    with_year = (
        session.query(func.count(Listing.id)).filter(Listing.year.isnot(None)).scalar()
        or 0
    )
    with_publisher = (
        session.query(func.count(Listing.id))
        .filter(Listing.publisher.isnot(None))
        .scalar()
        or 0
    )

    format_rows = (
        session.query(
            func.coalesce(Listing.format, "unknown").label("fmt"),
            func.count(Listing.id).label("count"),
        )
        .group_by(func.coalesce(Listing.format, "unknown"))
        .order_by(func.count(Listing.id).desc())
        .all()
    )
    by_format = [{"format": r.fmt, "count": r.count} for r in format_rows]

    return {
        "total": total,
        "active": active,
        "with_isbn": with_isbn,
        "with_author": with_author,
        "with_year": with_year,
        "with_publisher": with_publisher,
        "by_format": by_format,
    }


SORT_COLUMNS = {
    "id": Listing.id,
    "title": Listing.title,
    "author": Listing.author,
    "isbn": Listing.isbn,
    "price": Listing.price,
    "year": Listing.year,
    "is_active": Listing.is_active,
    "inactive_since": Listing.inactive_since,
    "last_seen_at": Listing.last_seen_at,
}


def get_listings_page(
    session: Session,
    page: int = 1,
    per_page: int = 50,
    search: str = "",
    author: str = "",
    publisher: str = "",
    category: str = "",
    format_filter: str = "",
    missing_field: str = "",
    shop_id: int | None = None,
    active_filter: str = "",
    has_isbn: bool = False,
    sort_by: str = "",
    sort_order: str = "asc",
) -> tuple[list[Listing], int]:
    """Return paginated listings with filters. Returns (listings, total_count)."""
    query = session.query(Listing).options(joinedload(Listing.shop))

    if shop_id:
        query = query.filter(Listing.shop_id == shop_id)
    if search:
        query = query.filter(Listing.title.ilike(f"%{search}%"))
    if author:
        query = query.filter(Listing.author.ilike(f"%{author}%"))
    if publisher:
        query = query.filter(Listing.publisher.ilike(f"%{publisher}%"))
    if category:
        query = query.filter(Listing.categories.any(category))
    if format_filter:
        if format_filter == "none":
            query = query.filter(Listing.format.is_(None))
        else:
            query = query.filter(Listing.format == format_filter)
    if missing_field:
        if missing_field == "any":
            from sqlalchemy import or_

            query = query.filter(
                or_(
                    Listing.author.is_(None),
                    Listing.isbn.is_(None),
                    Listing.year.is_(None),
                    Listing.publisher.is_(None),
                    Listing.format.is_(None),
                )
            )
        else:
            col = getattr(Listing, missing_field, None)
            if col is not None:
                query = query.filter(col.is_(None))
    if active_filter == "true":
        query = query.filter(Listing.is_active.is_(True))
    elif active_filter == "false":
        query = query.filter(Listing.is_active.is_(False))
    # "all" or "" — no active/inactive filter applied
    if has_isbn:
        query = query.filter(Listing.isbn.isnot(None))

    total = query.count()
    order_col = SORT_COLUMNS.get(sort_by, Listing.last_seen_at)
    if sort_order == "asc":
        query = query.order_by(order_col.asc().nulls_last())
    else:
        query = query.order_by(order_col.desc().nulls_last())
    listings = query.offset((page - 1) * per_page).limit(per_page).all()
    return listings, total


def get_all_categories(session: Session, limit: int = 200) -> list[str]:
    """Get distinct category names (excluding last breadcrumb item)."""
    sql = text("""
        SELECT DISTINCT cat, count(*) as cnt
        FROM (
            SELECT unnest(categories[1:array_length(categories,1)-1]) as cat
            FROM listings
            WHERE categories IS NOT NULL AND array_length(categories,1) > 1
        ) sub
        GROUP BY cat
        ORDER BY cnt DESC
        LIMIT :limit
    """)
    rows = session.execute(sql, {"limit": limit}).all()
    return [row[0] for row in rows]


def get_all_formats(session: Session) -> list[str]:
    """Get distinct format values."""
    rows = (
        session.query(Listing.format)
        .filter(Listing.format.isnot(None))
        .distinct()
        .order_by(Listing.format)
        .all()
    )
    return [r[0] for r in rows]


def get_all_shops(session: Session) -> list[Shop]:
    return session.query(Shop).order_by(Shop.name).all()


def get_shop_by_name(session: Session, name: str) -> Shop | None:
    return session.query(Shop).filter(Shop.name == name).first()


def get_shop_stats(session: Session, shop_id: int) -> dict:
    listings = (
        session.query(func.count(Listing.id))
        .filter(Listing.shop_id == shop_id)
        .scalar()
        or 0
    )
    active = (
        session.query(func.count(Listing.id))
        .filter(Listing.shop_id == shop_id, Listing.is_active.is_(True))
        .scalar()
        or 0
    )
    discovered = (
        session.query(func.count(DiscoveredUrl.id))
        .filter(DiscoveredUrl.shop_id == shop_id)
        .scalar()
        or 0
    )
    prices = (
        session.query(func.count(Price.id))
        .join(Listing)
        .filter(Listing.shop_id == shop_id)
        .scalar()
        or 0
    )
    return {
        "listings": listings,
        "active": active,
        "discovered_urls": discovered,
        "prices": prices,
    }


def get_shop_runs(session: Session, shop_id: int, limit: int = 20) -> list[ScrapeRun]:
    return (
        session.query(ScrapeRun)
        .filter(ScrapeRun.shop_id == shop_id)
        .order_by(ScrapeRun.started_at.desc())
        .limit(limit)
        .all()
    )


def get_run_listings(
    session: Session, run_id: int
) -> tuple[list[Listing], list[Listing], list[Listing]]:
    """Get listings created, changed, and unchanged in a specific run.

    Uses the prices table (append-only, keyed by scrape_run_id) to find
    listings touched by the run.  A listing whose first_seen_at falls within
    the run window *and* whose earliest price row belongs to this run is
    counted as "created".  Among existing listings, those with field changes
    (in listing_changes) or price changes are "changed"; the rest are
    "unchanged".

    Falls back to the legacy last_run_id column when no price rows reference
    the run (e.g. discover-only runs that don't insert prices).
    """
    # All listing IDs that have a price row for this run
    price_listing_ids = (
        session.query(Price.listing_id)
        .filter(Price.scrape_run_id == run_id)
        .distinct()
        .subquery()
    )

    listings_in_run = (
        session.query(Listing)
        .filter(Listing.id.in_(session.query(price_listing_ids.c.listing_id)))
        .order_by(Listing.title)
        .all()
    )

    if not listings_in_run:
        # Fallback: legacy last_run_id (works for the most recent run only)
        created = (
            session.query(Listing)
            .filter(
                Listing.last_run_id == run_id,
                Listing.last_run_action == "created",
            )
            .order_by(Listing.title)
            .all()
        )
        rest = (
            session.query(Listing)
            .filter(
                Listing.last_run_id == run_id,
                Listing.last_run_action == "updated",
            )
            .order_by(Listing.title)
            .all()
        )
        listings_in_run = created + rest
    else:
        created = [
            listing
            for listing in listings_in_run
            if listing.last_run_id == run_id and listing.last_run_action == "created"
        ]
        rest = [listing for listing in listings_in_run if listing not in created]

    if not rest:
        return created, [], []

    # IDs of listings with field-level changes in this run
    changed_ids = set(
        row[0]
        for row in session.query(ListingChange.listing_id)
        .filter(ListingChange.scrape_run_id == run_id)
        .distinct()
        .all()
    )

    # IDs of listings with price changes in this run
    rest_ids = [listing.id for listing in rest]
    if rest_ids:
        # Current run prices
        cur = (
            session.query(Price.listing_id, Price.price, Price.in_stock)
            .filter(
                Price.scrape_run_id == run_id,
                Price.listing_id.in_(rest_ids),
            )
            .subquery()
        )

        # Previous price: most recent price before this run's price
        run_prices = (
            session.query(Price).filter(Price.scrape_run_id == run_id).subquery()
        )
        prev = (
            session.query(
                Price.listing_id,
                Price.price,
                Price.in_stock,
            )
            .filter(
                Price.listing_id.in_(rest_ids),
                Price.scrape_run_id != run_id,
                Price.scraped_at
                < (
                    session.query(func.min(run_prices.c.scraped_at))
                    .filter(
                        run_prices.c.listing_id == Price.listing_id,
                    )
                    .correlate(Price)
                    .scalar_subquery()
                ),
            )
            .distinct(Price.listing_id)
            .order_by(Price.listing_id, Price.scraped_at.desc())
            .subquery()
        )

        # Find listings where price or in_stock differs
        price_changed_rows = (
            session.query(cur.c.listing_id)
            .outerjoin(prev, cur.c.listing_id == prev.c.listing_id)
            .filter(
                (prev.c.listing_id.is_(None))  # first re-scrape (no prev)
                | (cur.c.price != prev.c.price)
                | (cur.c.in_stock != prev.c.in_stock)
            )
            .all()
        )
        # Only count as price-changed if there WAS a previous price
        # (no prev = first scrape of existing listing, not a "change")
        price_changed_rows = (
            session.query(cur.c.listing_id)
            .join(prev, cur.c.listing_id == prev.c.listing_id)
            .filter((cur.c.price != prev.c.price) | (cur.c.in_stock != prev.c.in_stock))
            .all()
        )
        price_changed_ids = {row[0] for row in price_changed_rows}
    else:
        price_changed_ids = set()

    all_changed_ids = changed_ids | price_changed_ids
    changed = [listing for listing in rest if listing.id in all_changed_ids]
    unchanged = [listing for listing in rest if listing.id not in all_changed_ids]

    return created, changed, unchanged


def get_shop_field_stats(session: Session, shop_id: int) -> dict:
    """Get per-field completeness stats for a shop."""
    total = (
        session.query(func.count(Listing.id))
        .filter(Listing.shop_id == shop_id)
        .scalar()
        or 0
    )
    fields = {}
    for field_name in (
        "author",
        "isbn",
        "year",
        "publisher",
        "format",
        "description",
        "image_url",
    ):
        col = getattr(Listing, field_name)
        missing = (
            session.query(func.count(Listing.id))
            .filter(Listing.shop_id == shop_id, col.is_(None))
            .scalar()
            or 0
        )
        fields[field_name] = {"missing": missing, "present": total - missing}
    return {"total": total, "fields": fields}


def get_listing_changes(
    session: Session, listing_id: int, limit: int = 100
) -> list[ListingChange]:
    return (
        session.query(ListingChange)
        .filter(ListingChange.listing_id == listing_id)
        .order_by(ListingChange.changed_at.desc())
        .limit(limit)
        .all()
    )


def get_data_completeness(session: Session) -> list[dict]:
    """Get field completeness percentages for the overview page."""
    total = session.query(func.count(Listing.id)).scalar() or 0
    if total == 0:
        return []
    fields = ["author", "isbn", "publisher", "year", "format"]
    result = []
    for field_name in fields:
        col = getattr(Listing, field_name)
        present = (
            session.query(func.count(Listing.id)).filter(col.isnot(None)).scalar() or 0
        )
        pct = round(present / total * 100, 1) if total > 0 else 0
        result.append(
            {
                "field": field_name,
                "present": present,
                "total": total,
                "pct": pct,
            }
        )
    return result


def get_not_listed_count(session: Session, shop_id: int) -> int:
    """Count discovered URLs that have no matching listing."""
    sql = text("""
        SELECT COUNT(*)
        FROM discovered_urls du
        WHERE du.shop_id = :shop_id
          AND NOT EXISTS (
              SELECT 1 FROM listings l
              WHERE l.shop_id = du.shop_id AND l.url = du.url
          )
    """)
    return session.execute(sql, {"shop_id": shop_id}).scalar() or 0


def get_not_listed_urls(
    session: Session,
    shop_id: int,
    page: int = 1,
    per_page: int = 50,
    sort_by: str = "",
    sort_order: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    """Get discovered URLs that have no matching listing, paginated."""
    count_sql = text("""
        SELECT COUNT(*)
        FROM discovered_urls du
        WHERE du.shop_id = :shop_id
          AND NOT EXISTS (
              SELECT 1 FROM listings l
              WHERE l.shop_id = du.shop_id AND l.url = du.url
          )
    """)
    total = session.execute(count_sql, {"shop_id": shop_id}).scalar() or 0

    sort_col = "du.first_seen_at"
    if sort_by == "url":
        sort_col = "du.url"
    direction = "ASC" if sort_order == "asc" else "DESC"

    data_sql = text(f"""
        SELECT du.url, du.first_seen_at AS discovered_at, du.source, du.url_type
        FROM discovered_urls du
        WHERE du.shop_id = :shop_id
          AND NOT EXISTS (
              SELECT 1 FROM listings l
              WHERE l.shop_id = du.shop_id AND l.url = du.url
          )
        ORDER BY {sort_col} {direction}
        OFFSET :offset LIMIT :limit
    """)
    rows = (
        session.execute(
            data_sql,
            {
                "shop_id": shop_id,
                "offset": (page - 1) * per_page,
                "limit": per_page,
            },
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows], total


DISCOVERED_URL_SORT_COLUMNS = {
    "url": DiscoveredUrl.url,
    "fails": DiscoveredUrl.fail_count,
    "discovered": DiscoveredUrl.first_seen_at,
}


def get_discovered_urls_stats(session: Session, shop_id: int | None = None) -> dict:
    """Get stats for discovered URLs page."""
    base = session.query(DiscoveredUrl)
    if shop_id:
        base = base.filter(DiscoveredUrl.shop_id == shop_id)
    total = base.count()
    in_listings = base.join(
        Listing,
        (Listing.shop_id == DiscoveredUrl.shop_id) & (Listing.url == DiscoveredUrl.url),
    ).count()
    not_in_listings = total - in_listings
    failed = base.filter(DiscoveredUrl.fail_count >= 3).count()
    return {
        "total": total,
        "in_listings": in_listings,
        "not_in_listings": not_in_listings,
        "failed": failed,
    }


def get_discovered_urls_page(
    session: Session,
    page: int = 1,
    per_page: int = 50,
    shop_id: int | None = None,
    source: str = "",
    status: str = "",
    search: str = "",
    sort_by: str = "discovered",
    sort_order: str = "desc",
) -> tuple[list, int]:
    """Return paginated discovered URLs with filters."""
    query = session.query(DiscoveredUrl).options(joinedload(DiscoveredUrl.shop))
    if shop_id:
        query = query.filter(DiscoveredUrl.shop_id == shop_id)
    if source:
        query = query.filter(DiscoveredUrl.source == source)
    if search:
        query = query.filter(DiscoveredUrl.url.ilike(f"%{search}%"))
    if status == "not_in_listings":
        query = query.outerjoin(
            Listing,
            (Listing.shop_id == DiscoveredUrl.shop_id)
            & (Listing.url == DiscoveredUrl.url),
        ).filter(Listing.id.is_(None))
    elif status == "failed":
        query = query.filter(DiscoveredUrl.fail_count >= 3)
    elif status in ("unknown", "product", "non_product"):
        query = query.filter(DiscoveredUrl.url_type == status)
    total = query.count()
    order_col = DISCOVERED_URL_SORT_COLUMNS.get(sort_by, DiscoveredUrl.first_seen_at)
    if sort_order == "asc":
        query = query.order_by(order_col.asc().nulls_last())
    else:
        query = query.order_by(order_col.desc().nulls_last())
    urls = query.offset((page - 1) * per_page).limit(per_page).all()
    return urls, total
