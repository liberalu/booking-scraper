from datetime import UTC, datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from book_scraper.db.models import (
    Listing,
    Price,
    ScrapeRun,
    ValidationIssue,
)

STALE_HEARTBEAT_MINUTES = 5
DEAD_RUN_HOURS = 2


def get_run_health(run: ScrapeRun) -> str:
    """Return health status for a running scrape run.

    Returns: 'healthy', 'stale', 'dead', or '' for non-running runs.
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
    stale = (
        session.query(ScrapeRun)
        .filter(ScrapeRun.status == "running")
        .all()
    )
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
        .order_by(ScrapeRun.started_at.desc())
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


def get_validation_summary(session: Session) -> list[dict]:
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
) -> list[ValidationIssue]:
    return (
        session.query(ValidationIssue)
        .filter(ValidationIssue.issue == issue_type)
        .order_by(ValidationIssue.id.desc())
        .limit(limit)
        .all()
    )


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


def get_price_changes(session: Session, days: int = 7) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    sql = text("""
        WITH ranked AS (
            SELECT
                p.listing_id,
                p.price,
                p.scraped_at,
                LAG(p.price) OVER (
                    PARTITION BY p.listing_id ORDER BY p.scraped_at
                ) AS prev_price
            FROM prices p
            WHERE p.scraped_at >= :cutoff
        )
        SELECT
            r.listing_id,
            l.title,
            r.prev_price,
            r.price AS new_price,
            r.price - r.prev_price AS change,
            r.scraped_at
        FROM ranked r
        JOIN listings l ON l.id = r.listing_id
        WHERE r.prev_price IS NOT NULL
          AND r.price != r.prev_price
        ORDER BY ABS(r.price - r.prev_price) DESC
        LIMIT 50
    """)
    rows = session.execute(sql, {"cutoff": cutoff}).mappings().all()
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
