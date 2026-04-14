import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session, joinedload

from book_scraper.db.models import (
    DiscoveredUrl,
    Listing,
    ListingChange,
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


def get_overview_stats(session: Session) -> dict[str, Any]:
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


def get_recent_runs(
    session: Session,
    limit: int = 20,
    sort_by: str = "",
    sort_order: str = "desc",
) -> list[ScrapeRun]:
    sort_columns = {
        "id": ScrapeRun.id,
        "phase": ScrapeRun.phase,
        "status": ScrapeRun.status,
        "started_at": ScrapeRun.started_at,
        "items_added": ScrapeRun.items_added,
        "items_updated": ScrapeRun.items_updated,
        "error_count": ScrapeRun.error_count,
    }
    order_col = sort_columns.get(sort_by, ScrapeRun.started_at)
    order_expr = order_col.asc() if sort_order == "asc" else order_col.desc()
    return (
        session.query(ScrapeRun)
        .options(joinedload(ScrapeRun.shop))
        .order_by(order_expr)
        .limit(limit)
        .all()
    )


def get_run_detail(
    session: Session, run_id: int
) -> tuple[ScrapeRun | None, list[ValidationIssue]]:
    run = session.get(ScrapeRun, run_id)
    if run is None:
        return None, []
    issues = (
        session.query(ValidationIssue)
        .filter(ValidationIssue.scrape_run_id == run_id)
        .all()
    )
    return run, issues


def get_validation_summary(session: Session) -> list[dict[str, Any]]:
    rows = (
        session.query(
            ValidationIssue.issue,
            func.count(ValidationIssue.id).label("count"),
        )
        .group_by(ValidationIssue.issue)
        .order_by(func.count(ValidationIssue.id).desc())
        .all()
    )
    return [{"issue_type": r.issue, "count": r.count} for r in rows]


def get_validation_by_type(
    session: Session, issue_type: str, limit: int = 100
) -> list[dict[str, Any]]:
    """Get validation issues with listing IDs resolved from URL."""
    issues = (
        session.query(ValidationIssue)
        .filter(ValidationIssue.issue == issue_type)
        .order_by(ValidationIssue.id.desc())
        .limit(limit)
        .all()
    )
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
        SELECT listing_id, title, prev_price, new_price, change, scraped_at
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


def get_inventory_stats(session: Session) -> dict[str, Any]:
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
        query = query.filter(Listing.categories.contains([category]))
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


def get_shop_stats(session: Session, shop_id: int) -> dict[str, Any]:
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


def get_shop_runs(
    session: Session,
    shop_id: int,
    limit: int = 50,
    sort_by: str = "",
    sort_order: str = "desc",
) -> list[ScrapeRun]:
    sort_columns = {
        "id": ScrapeRun.id,
        "phase": ScrapeRun.phase,
        "status": ScrapeRun.status,
        "started_at": ScrapeRun.started_at,
        "items_added": ScrapeRun.items_added,
        "items_updated": ScrapeRun.items_updated,
        "error_count": ScrapeRun.error_count,
    }
    order_col = sort_columns.get(sort_by, ScrapeRun.started_at)
    order_expr = order_col.asc() if sort_order == "asc" else order_col.desc()
    return (
        session.query(ScrapeRun)
        .filter(ScrapeRun.shop_id == shop_id)
        .order_by(order_expr)
        .limit(limit)
        .all()
    )


def get_run_listings(
    session: Session, run_id: int
) -> tuple[list[Listing], list[Listing]]:
    """Get listings created and updated in a specific run."""
    created = (
        session.query(Listing)
        .filter(Listing.last_run_id == run_id, Listing.last_run_action == "created")
        .order_by(Listing.title)
        .all()
    )
    updated = (
        session.query(Listing)
        .filter(Listing.last_run_id == run_id, Listing.last_run_action == "updated")
        .order_by(Listing.title)
        .all()
    )
    return created, updated


def get_shop_field_stats(session: Session, shop_id: int) -> dict[str, Any]:
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

    sort_col = "du.discovered_at"
    if sort_by == "url":
        sort_col = "du.url"
    direction = "ASC" if sort_order == "asc" else "DESC"

    data_sql = text(f"""
        SELECT du.url, du.discovered_at, du.source, du.url_type
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
            {"shop_id": shop_id, "offset": (page - 1) * per_page, "limit": per_page},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows], total
