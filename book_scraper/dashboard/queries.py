import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, joinedload

from book_scraper.dashboard.shop_book_filters import (
    ShopBookFieldFilter,
    apply_shop_book_field_filters,
)
from book_scraper.db.models import (
    DiscoveredUrl,
    Price,
    ScrapeRun,
    ScrapeUrlItem,
    Shop,
    ShopBook,
    ShopBookChange,
    ShopBookFieldUpdate,
    UrlClassification,
    ValidationIssue,
)

STALE_HEARTBEAT_MINUTES = 5
DEAD_RUN_MINUTES = 30

ISSUE_DESCRIPTIONS: dict[str, str] = {
    "missing_price": (
        "No price scraped. Parser likely hit a broken or restructured product page."
    ),
    "zero_price": (
        "Price parsed as 0.00. Parser probably matched an empty or wrong element."
    ),
    "price_higher_than_original": (
        "Sale price exceeds the original. Likely a data inversion"
        " — original and current fields may be swapped."
    ),
    "invalid_price": "Price couldn't be parsed as a number. Item was dropped.",
    "invalid_price_original": "Original price couldn't be parsed. Stored as null.",
    "missing_title": "No title scraped. Item was dropped.",
    "suspicious_title": (
        "Title shorter than 2 chars or longer than 300."
        " Parser may be selecting the wrong element."
    ),
    "html_in_text": (
        "HTML tags found in title or author. Raw markup leaked into a text field."
    ),
    "format_mismatch": (
        "Format inconsistent with metadata"
        " — e.g. audiobook has pages, hardcover has duration."
    ),
    "attribute_unknown_key": (
        "A property key not in the shop's allowed attribute list."
        " Add to config or fix the parser."
    ),
    "attribute_invalid_value": (
        "A property value doesn't match the allowed enum or regex in the shop config."
    ),
    "field_cleared": (
        "A field that had a value is now missing. Likely a parser regression."
    ),
    "scrape_run_failed": (
        "A scrape run ended with status=failed. Inspect the run's detail page"
        " to see why (stall, kill, orphan on boot, or downstream error)."
    ),
}

ISSUE_SEVERITY: dict[str, str] = {
    "missing_price": "critical",
    "zero_price": "critical",
    "price_higher_than_original": "critical",
    "invalid_price": "critical",
    "invalid_price_original": "critical",
    "missing_title": "critical",
    "suspicious_title": "warning",
    "html_in_text": "warning",
    "format_mismatch": "warning",
    "attribute_unknown_key": "warning",
    "attribute_invalid_value": "warning",
    "field_cleared": "critical",
    "scrape_run_failed": "critical",
}


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
    if elapsed > timedelta(minutes=DEAD_RUN_MINUTES):
        return "dead"
    if elapsed > timedelta(minutes=STALE_HEARTBEAT_MINUTES):
        return "stale"
    return "healthy"


def mark_stale_runs(session: Session) -> int:
    """Mark runs with no heartbeat for over DEAD_RUN_MINUTES as failed."""
    from book_scraper.db.repo import record_scrape_run_failed_issue

    cutoff = datetime.now(UTC) - timedelta(minutes=DEAD_RUN_MINUTES)
    stale = session.query(ScrapeRun).filter(ScrapeRun.status == "running").all()
    marked = 0
    for run in stale:
        last_activity = run.last_heartbeat or run.started_at
        if last_activity and last_activity < cutoff:
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            record_scrape_run_failed_issue(session, run, "heartbeat_timeout")
            marked += 1
    if marked:
        session.commit()
    return marked


def get_overview_stats(session: Session) -> dict:
    total = session.query(func.count(ShopBook.id)).scalar() or 0
    active = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.is_active.is_(True))
        .scalar()
        or 0
    )
    with_isbn = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.isbn.isnot(None))
        .scalar()
        or 0
    )
    total_prices = session.query(func.count(Price.id)).scalar() or 0
    return {
        "total_shop_books": total,
        "active_shop_books": active,
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


RUN_URL_STATUSES = ("pending", "processing", "done", "failed")


def get_run_url_breakdown(session: Session, run_id: int) -> dict[str, int]:
    """Counts of scrape_url_items per status for a still-running run.

    Returns zeros for finished runs (rows are cleaned up on finish — see
    `cleanup_scrape_url_items`).
    """
    rows = (
        session.query(ScrapeUrlItem.status, func.count(ScrapeUrlItem.id))
        .filter(ScrapeUrlItem.run_id == run_id)
        .group_by(ScrapeUrlItem.status)
        .all()
    )
    counts = dict.fromkeys(RUN_URL_STATUSES, 0)
    for status, count in rows:
        counts[status] = count
    return counts


def get_run_url_items(
    session: Session,
    run_id: int,
    status: str = "all",
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[ScrapeUrlItem], int]:
    """Live URL queue for a running run, paginated. Returns (rows, total)."""
    query = session.query(ScrapeUrlItem).filter(ScrapeUrlItem.run_id == run_id)
    if status in RUN_URL_STATUSES:
        query = query.filter(ScrapeUrlItem.status == status)
    total = query.count()
    rows = (
        query.order_by(
            # processing first, then pending, then done/failed by most-recent
            ScrapeUrlItem.claimed_at.desc().nulls_last(),
            ScrapeUrlItem.id.asc(),
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return rows, total


def get_run_discovered_urls(
    session: Session,
    run_id: int,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[DiscoveredUrl], int]:
    """URLs touched by a finished discover run via `last_seen_run_id`.

    Scan runs read directly from `scrape_url_items` now (rows are kept
    after the run finishes). This helper is only used as the discover-run
    fallback.
    """
    run = session.get(ScrapeRun, run_id)
    if run is None or not run.phase.startswith("discover"):
        return [], 0
    query = session.query(DiscoveredUrl).filter(
        DiscoveredUrl.last_seen_run_id == run_id
    )
    total = query.count()
    rows = (
        query.order_by(DiscoveredUrl.last_checked_at.desc().nulls_last())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return rows, total


def get_run_issue_summary(session: Session, run_id: int) -> list[dict[str, Any]]:
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


def get_validation_summary(session: Session, state: str | None = None) -> list[dict]:
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


def get_validation_lifecycle_counts(
    session: Session,
    shop_id: int | None = None,
    issue_type: str = "",
    run_id: int | None = None,
    q: str = "",
    severity: str = "",
) -> dict[str, int]:
    """Bucket counts of issues (new/recurring/already_seen/open) under the same
    filter semantics as `get_issues_page`. Used by the stat strip + lifecycle tabs."""
    from sqlalchemy import or_

    query = session.query(
        ValidationIssue.lifecycle_state,
        func.count(ValidationIssue.id).label("count"),
    )
    if shop_id is not None or q:
        query = query.join(ScrapeRun, ValidationIssue.scrape_run_id == ScrapeRun.id)
    if shop_id is not None:
        query = query.filter(ScrapeRun.shop_id == shop_id)
    if issue_type:
        query = query.filter(ValidationIssue.issue == issue_type)
    if severity in ("critical", "warning"):
        severity_types = [k for k, v in ISSUE_SEVERITY.items() if v == severity]
        query = query.filter(ValidationIssue.issue.in_(severity_types))
    if run_id is not None:
        query = query.filter(ValidationIssue.scrape_run_id == run_id)
    if q:
        pattern = f"%{q}%"
        query = query.outerjoin(
            ShopBook, ValidationIssue.shop_book_id == ShopBook.id
        ).filter(or_(ValidationIssue.url.ilike(pattern), ShopBook.title.ilike(pattern)))

    rows = query.group_by(ValidationIssue.lifecycle_state).all()
    counts = {"new": 0, "recurring": 0, "already_seen": 0}
    for r in rows:
        counts[r.lifecycle_state] = r.count
    counts["open"] = counts["new"] + counts["recurring"]
    return counts


def get_issues_page(
    session: Session,
    state: str | None = "open",
    shop_id: int | None = None,
    issue_type: str = "",
    run_id: int | None = None,
    q: str = "",
    severity: str = "",
    order: str = "desc",
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Return paginated flat list of validation issues with filters.

    Rows are sorted by scrape_runs.started_at (then ValidationIssue.id) to
    approximate per-issue creation time without adding a column.

    Returns (rows, total).
    """
    from sqlalchemy import or_

    query = (
        session.query(ValidationIssue, ScrapeRun, ShopBook)
        .join(ScrapeRun, ValidationIssue.scrape_run_id == ScrapeRun.id)
        .outerjoin(ShopBook, ValidationIssue.shop_book_id == ShopBook.id)
    )

    if state in {"new", "recurring", "already_seen"}:
        query = query.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        query = query.filter(ValidationIssue.lifecycle_state != "already_seen")

    if shop_id is not None:
        query = query.filter(ScrapeRun.shop_id == shop_id)
    if issue_type:
        query = query.filter(ValidationIssue.issue == issue_type)
    if severity in ("critical", "warning"):
        severity_types = [k for k, v in ISSUE_SEVERITY.items() if v == severity]
        query = query.filter(ValidationIssue.issue.in_(severity_types))
    if run_id is not None:
        query = query.filter(ValidationIssue.scrape_run_id == run_id)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(ValidationIssue.url.ilike(pattern), ShopBook.title.ilike(pattern))
        )

    total = query.count()

    if order == "asc":
        query = query.order_by(
            ScrapeRun.started_at.asc().nulls_last(), ValidationIssue.id.asc()
        )
    else:
        query = query.order_by(
            ScrapeRun.started_at.desc().nulls_last(), ValidationIssue.id.desc()
        )

    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    result: list[dict[str, Any]] = []
    for issue, run, shop_book in rows:
        result.append(
            {
                "id": issue.id,
                "url": issue.url,
                "field": issue.field,
                "issue": issue.issue,
                "raw_value": issue.raw_value,
                "scrape_run_id": issue.scrape_run_id,
                "shop_book_id": issue.shop_book_id,
                "shop_book_title": shop_book.title if shop_book else None,
                "lifecycle_state": issue.lifecycle_state,
                "added_at": run.started_at,
                "severity": ISSUE_SEVERITY.get(issue.issue, "warning"),
            }
        )
    return result, total


def get_validation_by_type(
    session: Session,
    issue_type: str,
    limit: int = 100,
    state: str | None = None,
    run_id: int | None = None,
) -> list[dict]:
    """Get validation issues with shop_book IDs resolved from URL."""
    q = session.query(ValidationIssue).filter(ValidationIssue.issue == issue_type)
    if state in {"new", "recurring", "already_seen"}:
        q = q.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        q = q.filter(ValidationIssue.lifecycle_state != "already_seen")
    if run_id is not None:
        q = q.filter(ValidationIssue.scrape_run_id == run_id)
    issues = q.order_by(ValidationIssue.id.desc()).limit(limit).all()
    # Resolve shop_book IDs by URL
    urls = {i.url for i in issues}
    url_to_shop_book = {}
    if urls:
        rows = (
            session.query(ShopBook.url, ShopBook.id, ShopBook.title)
            .filter(ShopBook.url.in_(urls))
            .all()
        )
        url_to_shop_book = {r.url: {"id": r.id, "title": r.title} for r in rows}

    result = []
    for issue in issues:
        shop_book = url_to_shop_book.get(issue.url)
        result.append(
            {
                "id": issue.id,
                "url": issue.url,
                "field": issue.field,
                "issue": issue.issue,
                "raw_value": issue.raw_value,
                "scrape_run_id": issue.scrape_run_id,
                "shop_book_id": shop_book["id"] if shop_book else None,
                "shop_book_title": shop_book["title"] if shop_book else None,
                "lifecycle_state": issue.lifecycle_state,
                "acknowledged_at": issue.acknowledged_at,
            }
        )
    return result


def search_shop_books(session: Session, query: str, limit: int = 50) -> list[ShopBook]:
    return (
        session.query(ShopBook)
        .filter(ShopBook.title.ilike(f"%{query}%"))
        .order_by(ShopBook.title)
        .limit(limit)
        .all()
    )


def get_field_updates(session: Session, shop_book_id: int) -> dict[str, datetime]:
    """Return {field: updated_at} for a shop_book's tracked fields."""
    rows = (
        session.query(ShopBookFieldUpdate)
        .filter(ShopBookFieldUpdate.shop_book_id == shop_book_id)
        .all()
    )
    return {r.field: r.updated_at for r in rows}


def get_field_history(
    session: Session, shop_book_id: int
) -> dict[str, dict[str, datetime | None]]:
    """Return {field: {first_seen_at, changed_at}} for a shop_book's tracked fields.

    first_seen_at: earliest ShopBookChange where old_value IS NULL for that field
                   (i.e. the first time the field was set). Falls back to
                   shop_book.first_seen_at if no such change record exists.
    changed_at:    ShopBookFieldUpdate.updated_at (last time the field changed).
    """
    updates = (
        session.query(ShopBookFieldUpdate)
        .filter(ShopBookFieldUpdate.shop_book_id == shop_book_id)
        .all()
    )
    if not updates:
        return {}

    changed_map: dict[str, datetime] = {r.field: r.updated_at for r in updates}

    # Earliest "field set from None" change per field
    first_set_rows = (
        session.query(
            ShopBookChange.field,
            func.min(ShopBookChange.changed_at).label("first_at"),
        )
        .filter(
            ShopBookChange.shop_book_id == shop_book_id,
            ShopBookChange.old_value.is_(None),
        )
        .group_by(ShopBookChange.field)
        .all()
    )
    first_set_map: dict[str, datetime] = {r.field: r.first_at for r in first_set_rows}

    sb = session.get(ShopBook, shop_book_id)
    fallback = sb.first_seen_at if sb else None

    result: dict[str, dict[str, datetime | None]] = {}
    for field, changed_at in changed_map.items():
        result[field] = {
            "first_seen_at": first_set_map.get(field, fallback),
            "changed_at": changed_at,
        }
    return result


def get_price_history(session: Session, shop_book_id: int) -> list[Price]:
    return (
        session.query(Price)
        .filter(Price.shop_book_id == shop_book_id)
        .order_by(Price.scraped_at)
        .all()
    )


def get_price_changes(
    session: Session,
    days: int = 7,
    shop_id: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> tuple[list[dict[str, Any]], int]:
    """Return (rows, total) for price changes, paginated by ABS(change)."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    shop_filter = "AND l.shop_id = :shop_id" if shop_id else ""
    cte = f"""
        WITH ranked AS (
            SELECT
                p.shop_book_id,
                p.price,
                p.scraped_at,
                LAG(p.price) OVER (
                    PARTITION BY p.shop_book_id ORDER BY p.scraped_at
                ) AS prev_price
            FROM prices p
            JOIN shop_books l ON l.id = p.shop_book_id
            WHERE p.scraped_at >= :cutoff
            {shop_filter}
        ),
        changes AS (
            SELECT
                r.shop_book_id,
                l.title,
                r.prev_price,
                r.price AS new_price,
                r.price - r.prev_price AS change,
                r.scraped_at,
                ROW_NUMBER() OVER (
                    PARTITION BY r.shop_book_id, r.prev_price, r.price
                    ORDER BY r.scraped_at DESC
                ) AS rn
            FROM ranked r
            JOIN shop_books l ON l.id = r.shop_book_id
            WHERE r.prev_price IS NOT NULL
              AND r.price != r.prev_price
        )
    """
    params: dict[str, Any] = {"cutoff": cutoff}
    if shop_id:
        params["shop_id"] = shop_id

    total = (
        session.execute(
            text(cte + " SELECT COUNT(*) FROM changes WHERE rn = 1"),
            params,
        ).scalar()
        or 0
    )

    page = max(1, page)
    per_page = max(1, min(per_page, 200))
    offset = (page - 1) * per_page
    data_sql = text(
        cte
        + """
        SELECT shop_book_id, title, prev_price, new_price, change, scraped_at
        FROM changes
        WHERE rn = 1
        ORDER BY ABS(change) DESC, scraped_at DESC
        OFFSET :offset LIMIT :limit
    """
    )
    rows = (
        session.execute(
            data_sql, {**params, "offset": offset, "limit": per_page}
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows], int(total)


def get_inventory_stats(session: Session) -> dict:
    total = session.query(func.count(ShopBook.id)).scalar() or 0
    active = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.is_active.is_(True))
        .scalar()
        or 0
    )
    with_isbn = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.isbn.isnot(None))
        .scalar()
        or 0
    )
    with_author = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.author.isnot(None))
        .scalar()
        or 0
    )
    with_year = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.year.isnot(None))
        .scalar()
        or 0
    )
    with_publisher = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.publisher.isnot(None))
        .scalar()
        or 0
    )

    format_rows = (
        session.query(
            func.coalesce(ShopBook.format, "unknown").label("fmt"),
            func.count(ShopBook.id).label("count"),
        )
        .group_by(func.coalesce(ShopBook.format, "unknown"))
        .order_by(func.count(ShopBook.id).desc())
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
    "id": ShopBook.id,
    "title": ShopBook.title,
    "author": ShopBook.author,
    "isbn": ShopBook.isbn,
    "type": ShopBook.type,
    "price": ShopBook.price,
    "year": ShopBook.year,
    "is_active": ShopBook.is_active,
    "inactive_since": ShopBook.inactive_since,
    "last_seen_at": ShopBook.last_seen_at,
}


def get_shop_books_page(
    session: Session,
    page: int = 1,
    per_page: int = 50,
    search: str = "",
    author: str = "",
    publisher: str = "",
    category: str = "",
    type_filter: str = "",
    format_filter: str = "",
    missing_field: str = "",
    shop_id: int | None = None,
    active_filter: str = "",
    has_isbn: bool = False,
    sort_by: str = "",
    sort_order: str = "asc",
    field_filters: dict[str, ShopBookFieldFilter] | None = None,
    attr_key: str = "",
    attr_value: str = "",
) -> tuple[list[ShopBook], int]:
    """Return paginated shop_books with filters. Returns (shop_books, total_count)."""
    query = session.query(ShopBook).options(joinedload(ShopBook.shop))

    if shop_id:
        query = query.filter(ShopBook.shop_id == shop_id)
    if search:
        query = query.filter(ShopBook.title.ilike(f"%{search}%"))
    if author:
        query = query.filter(ShopBook.author.ilike(f"%{author}%"))
    if publisher:
        query = query.filter(ShopBook.publisher.ilike(f"%{publisher}%"))
    if category:
        query = query.filter(ShopBook.categories.any(category))
    if type_filter:
        query = query.filter(ShopBook.type == type_filter)
    if format_filter:
        if format_filter == "none":
            query = query.filter(ShopBook.format.is_(None))
        else:
            query = query.filter(ShopBook.format == format_filter)
    if missing_field:
        if missing_field == "any":
            from sqlalchemy import or_

            query = query.filter(
                or_(
                    ShopBook.author.is_(None),
                    ShopBook.isbn.is_(None),
                    ShopBook.year.is_(None),
                    ShopBook.publisher.is_(None),
                    ShopBook.format.is_(None),
                )
            )
        else:
            col = getattr(ShopBook, missing_field, None)
            if col is not None:
                query = query.filter(col.is_(None))
    if active_filter == "true":
        query = query.filter(ShopBook.is_active.is_(True))
    elif active_filter == "false":
        query = query.filter(ShopBook.is_active.is_(False))
    # "all" or "" — no active/inactive filter applied
    if has_isbn:
        query = query.filter(ShopBook.isbn.isnot(None))
    if attr_key:
        from sqlalchemy import exists

        from book_scraper.db.models import ShopBookAttribute

        attr_subq = session.query(ShopBookAttribute).filter(
            ShopBookAttribute.shop_book_id == ShopBook.id,
            ShopBookAttribute.key == attr_key,
        )
        if attr_value:
            attr_subq = attr_subq.filter(ShopBookAttribute.value == attr_value)
        query = query.filter(exists(attr_subq))
    if field_filters:
        query = apply_shop_book_field_filters(query, field_filters)

    total = query.count()
    order_col = SORT_COLUMNS.get(sort_by, ShopBook.last_seen_at)
    if sort_order == "asc":
        query = query.order_by(order_col.asc().nulls_last())
    else:
        query = query.order_by(order_col.desc().nulls_last())
    shop_books = query.offset((page - 1) * per_page).limit(per_page).all()
    return shop_books, total


def get_all_categories(session: Session, limit: int = 200) -> list[str]:
    """Get distinct category names (excluding last breadcrumb item)."""
    sql = text("""
        SELECT DISTINCT cat, count(*) as cnt
        FROM (
            SELECT unnest(categories[1:array_length(categories,1)-1]) as cat
            FROM shop_books
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
        session.query(ShopBook.format)
        .filter(ShopBook.format.isnot(None))
        .distinct()
        .order_by(ShopBook.format)
        .all()
    )
    return [r[0] for r in rows]


def get_attribute_keys(session: Session, shop_id: int | None = None) -> list[str]:
    """Return distinct attribute keys (sorted) across all shop_books."""
    from book_scraper.db.models import ShopBookAttribute

    query = session.query(ShopBookAttribute.key).distinct()
    if shop_id is not None:
        query = query.join(
            ShopBook, ShopBookAttribute.shop_book_id == ShopBook.id
        ).filter(ShopBook.shop_id == shop_id)
    return sorted(r[0] for r in query.all())


def get_attribute_values(
    session: Session, key: str, shop_id: int | None = None
) -> list[str]:
    """Return distinct non-null attribute values for a given key (sorted)."""
    from book_scraper.db.models import ShopBookAttribute

    query = (
        session.query(ShopBookAttribute.value)
        .filter(ShopBookAttribute.key == key, ShopBookAttribute.value.isnot(None))
        .distinct()
    )
    if shop_id is not None:
        query = query.join(
            ShopBook, ShopBookAttribute.shop_book_id == ShopBook.id
        ).filter(ShopBook.shop_id == shop_id)
    return sorted(r[0] for r in query.all())


def get_all_types(session: Session) -> list[str]:
    """Get distinct shop-book type values."""
    rows = (
        session.query(ShopBook.type)
        .filter(ShopBook.type.isnot(None))
        .distinct()
        .order_by(ShopBook.type)
        .all()
    )
    return [r[0] for r in rows]


def get_all_shops(session: Session) -> list[Shop]:
    return session.query(Shop).order_by(Shop.name).all()


def get_shop_by_name(session: Session, name: str) -> Shop | None:
    return session.query(Shop).filter(Shop.name == name).first()


def get_shop_stats(session: Session, shop_id: int) -> dict:
    shop_books = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.shop_id == shop_id)
        .scalar()
        or 0
    )
    active = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.shop_id == shop_id, ShopBook.is_active.is_(True))
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
        .join(ShopBook)
        .filter(ShopBook.shop_id == shop_id)
        .scalar()
        or 0
    )
    return {
        "shop_books": shop_books,
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


def get_run_changed_fields(
    session: Session, run_id: int, shop_book_ids: list[int]
) -> dict[int, list[tuple[str, str | None, str | None]]]:
    """Return {shop_book_id: [(field, old_value, new_value), ...]} for this run."""
    if not shop_book_ids:
        return {}
    rows = (
        session.query(
            ShopBookChange.shop_book_id,
            ShopBookChange.field,
            ShopBookChange.old_value,
            ShopBookChange.new_value,
        )
        .filter(
            ShopBookChange.scrape_run_id == run_id,
            ShopBookChange.shop_book_id.in_(shop_book_ids),
        )
        .all()
    )
    result: dict[int, list[tuple[str, str | None, str | None]]] = {}
    for row in rows:
        result.setdefault(row.shop_book_id, []).append(
            (row.field, row.old_value, row.new_value)
        )
    return result


def get_run_price_changes(
    session: Session, run_id: int, shop_book_ids: list[int]
) -> dict[int, tuple[str, str]]:
    """Return old/new prices for price-changed shop books in a run."""
    if not shop_book_ids:
        return {}
    cur_rows = (
        session.query(Price.shop_book_id, Price.price)
        .filter(Price.scrape_run_id == run_id, Price.shop_book_id.in_(shop_book_ids))
        .all()
    )
    cur_map = {r.shop_book_id: r.price for r in cur_rows}
    if not cur_map:
        return {}
    # Per-book cutoff: earliest scraped_at for this book within the run
    run_prices = (
        session.query(
            Price.shop_book_id,
            func.min(Price.scraped_at).label("run_scraped_at"),
        )
        .filter(Price.scrape_run_id == run_id, Price.shop_book_id.in_(shop_book_ids))
        .group_by(Price.shop_book_id)
        .subquery()
    )
    prev_rows = (
        session.query(Price.shop_book_id, Price.price)
        .join(run_prices, Price.shop_book_id == run_prices.c.shop_book_id)
        .filter(
            Price.scrape_run_id != run_id,
            Price.scraped_at < run_prices.c.run_scraped_at,
        )
        .distinct(Price.shop_book_id)
        .order_by(Price.shop_book_id, Price.scraped_at.desc())
        .all()
    )
    prev_map = {r.shop_book_id: r.price for r in prev_rows}
    return {
        sb_id: (str(prev_map[sb_id]), str(cur_map[sb_id]))
        for sb_id in shop_book_ids
        if sb_id in cur_map and sb_id in prev_map and cur_map[sb_id] != prev_map[sb_id]
    }


def get_run_shop_books(
    session: Session, run_id: int
) -> tuple[list[ShopBook], list[ShopBook], list[ShopBook], set[int]]:
    """Get shop_books created, changed, and unchanged in a specific run.

    Uses the prices table (append-only, keyed by scrape_run_id) to find
    shop_books touched by the run.  A shop_book whose first_seen_at falls within
    the run window *and* whose earliest price row belongs to this run is
    counted as "created".  Among existing shop_books, those with field changes
    (in shop_book_changes) or price changes are "changed"; the rest are
    "unchanged".

    Falls back to the legacy last_run_id column when no price rows reference
    the run (e.g. discover-only runs that don't insert prices).
    """
    # All shop_book IDs that have a price row for this run
    price_shop_book_ids = (
        session.query(Price.shop_book_id)
        .filter(Price.scrape_run_id == run_id)
        .distinct()
        .subquery()
    )

    shop_books_in_run = (
        session.query(ShopBook)
        .filter(ShopBook.id.in_(session.query(price_shop_book_ids.c.shop_book_id)))
        .order_by(ShopBook.title)
        .all()
    )

    if not shop_books_in_run:
        # Fallback: legacy last_run_id (works for the most recent run only)
        created = (
            session.query(ShopBook)
            .filter(
                ShopBook.last_run_id == run_id,
                ShopBook.last_run_action == "created",
            )
            .order_by(ShopBook.title)
            .all()
        )
        rest = (
            session.query(ShopBook)
            .filter(
                ShopBook.last_run_id == run_id,
                ShopBook.last_run_action == "updated",
            )
            .order_by(ShopBook.title)
            .all()
        )
        shop_books_in_run = created + rest
    else:
        created = [
            shop_book
            for shop_book in shop_books_in_run
            if shop_book.last_run_id == run_id
            and shop_book.last_run_action == "created"
        ]
        rest = [
            shop_book for shop_book in shop_books_in_run if shop_book not in created
        ]

    if not rest:
        return created, [], [], set()

    # IDs of shop_books with field-level changes in this run
    changed_ids = set(
        row[0]
        for row in session.query(ShopBookChange.shop_book_id)
        .filter(ShopBookChange.scrape_run_id == run_id)
        .distinct()
        .all()
    )

    # IDs of shop_books with price changes in this run
    rest_ids = [shop_book.id for shop_book in rest]
    if rest_ids:
        # Current run prices
        cur = (
            session.query(Price.shop_book_id, Price.price, Price.in_stock)
            .filter(
                Price.scrape_run_id == run_id,
                Price.shop_book_id.in_(rest_ids),
            )
            .subquery()
        )

        # Previous price: most recent price before this run's price
        run_prices = (
            session.query(Price).filter(Price.scrape_run_id == run_id).subquery()
        )
        prev = (
            session.query(
                Price.shop_book_id,
                Price.price,
                Price.in_stock,
            )
            .filter(
                Price.shop_book_id.in_(rest_ids),
                Price.scrape_run_id != run_id,
                Price.scraped_at
                < (
                    session.query(func.min(run_prices.c.scraped_at))
                    .filter(
                        run_prices.c.shop_book_id == Price.shop_book_id,
                    )
                    .correlate(Price)
                    .scalar_subquery()
                ),
            )
            .distinct(Price.shop_book_id)
            .order_by(Price.shop_book_id, Price.scraped_at.desc())
            .subquery()
        )

        # Find shop_books where price or in_stock differs
        price_changed_rows = (
            session.query(cur.c.shop_book_id)
            .outerjoin(prev, cur.c.shop_book_id == prev.c.shop_book_id)
            .filter(
                (prev.c.shop_book_id.is_(None))  # first re-scrape (no prev)
                | (cur.c.price != prev.c.price)
                | (cur.c.in_stock != prev.c.in_stock)
            )
            .all()
        )
        # Only count as price-changed if there WAS a previous price
        # (no prev = first scrape of existing shop_book, not a "change")
        price_changed_rows = (
            session.query(cur.c.shop_book_id)
            .join(prev, cur.c.shop_book_id == prev.c.shop_book_id)
            .filter((cur.c.price != prev.c.price) | (cur.c.in_stock != prev.c.in_stock))
            .all()
        )
        price_changed_ids = {row[0] for row in price_changed_rows}
    else:
        price_changed_ids = set()

    all_changed_ids = changed_ids | price_changed_ids
    changed = [shop_book for shop_book in rest if shop_book.id in all_changed_ids]
    unchanged = [shop_book for shop_book in rest if shop_book.id not in all_changed_ids]

    return created, changed, unchanged, price_changed_ids


def get_shop_field_stats(session: Session, shop_id: int) -> dict:
    """Get per-field completeness stats for a shop."""
    total = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.shop_id == shop_id)
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
        col = getattr(ShopBook, field_name)
        missing = (
            session.query(func.count(ShopBook.id))
            .filter(ShopBook.shop_id == shop_id, col.is_(None))
            .scalar()
            or 0
        )
        fields[field_name] = {"missing": missing, "present": total - missing}
    return {"total": total, "fields": fields}


def get_shop_book_issues(session: Session, shop_book_id: int) -> list[dict[str, Any]]:
    rows = (
        session.query(ValidationIssue)
        .filter(ValidationIssue.shop_book_id == shop_book_id)
        .order_by(ValidationIssue.id.desc())
        .all()
    )
    return [
        {
            "id": issue.id,
            "issue": issue.issue,
            "field": issue.field,
            "raw_value": issue.raw_value,
            "lifecycle_state": issue.lifecycle_state,
            "scrape_run_id": issue.scrape_run_id,
            "severity": ISSUE_SEVERITY.get(issue.issue, "warning"),
        }
        for issue in rows
    ]


def get_shop_book_changes(
    session: Session, shop_book_id: int, limit: int = 100
) -> list[ShopBookChange]:
    return (
        session.query(ShopBookChange)
        .filter(ShopBookChange.shop_book_id == shop_book_id)
        .order_by(ShopBookChange.changed_at.desc())
        .limit(limit)
        .all()
    )


def get_data_completeness(session: Session) -> list[dict]:
    """Get field completeness percentages for the overview page."""
    total = session.query(func.count(ShopBook.id)).scalar() or 0
    if total == 0:
        return []
    fields = ["author", "isbn", "publisher", "year", "format"]
    result = []
    for field_name in fields:
        col = getattr(ShopBook, field_name)
        present = (
            session.query(func.count(ShopBook.id)).filter(col.isnot(None)).scalar() or 0
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
    """Count discovered URLs that have no matching shop_book."""
    sql = text("""
        SELECT COUNT(*)
        FROM discovered_urls du
        WHERE du.shop_id = :shop_id
          AND NOT EXISTS (
              SELECT 1 FROM shop_books l
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
    """Get discovered URLs that have no matching shop_book, paginated."""
    count_sql = text("""
        SELECT COUNT(*)
        FROM discovered_urls du
        WHERE du.shop_id = :shop_id
          AND NOT EXISTS (
              SELECT 1 FROM shop_books l
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
              SELECT 1 FROM shop_books l
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
    "score": UrlClassification.book_score,
}


def get_discovered_urls_stats(session: Session, shop_id: int | None = None) -> dict:
    """Get stats for discovered URLs page."""
    base = session.query(DiscoveredUrl)
    if shop_id:
        base = base.filter(DiscoveredUrl.shop_id == shop_id)
    total = base.count()
    in_shop_books = base.join(
        ShopBook,
        (ShopBook.shop_id == DiscoveredUrl.shop_id)
        & (ShopBook.url == DiscoveredUrl.url),
    ).count()
    not_in_shop_books = total - in_shop_books
    failed = base.filter(DiscoveredUrl.fail_count >= 3).count()
    return {
        "total": total,
        "in_shop_books": in_shop_books,
        "not_in_shop_books": not_in_shop_books,
        "failed": failed,
    }


def get_discovered_urls_page(
    session: Session,
    page: int = 1,
    per_page: int = 50,
    shop_id: int | None = None,
    source: str = "",
    url_type: str = "",
    search: str = "",
    score_min: int | None = None,
    is_book: str = "",
    sort_by: str = "discovered",
    sort_order: str = "desc",
) -> tuple[list, int]:
    """Return paginated discovered URLs with filters."""
    query = (
        session.query(DiscoveredUrl)
        .options(joinedload(DiscoveredUrl.shop))
        .outerjoin(
            UrlClassification, UrlClassification.discovered_url_id == DiscoveredUrl.id
        )
    )
    if shop_id:
        query = query.filter(DiscoveredUrl.shop_id == shop_id)
    if source:
        query = query.filter(DiscoveredUrl.source == source)
    if url_type:
        query = query.filter(DiscoveredUrl.url_type == url_type)
    if search:
        query = query.filter(DiscoveredUrl.url.ilike(f"%{search}%"))
    if score_min is not None:
        query = query.filter(UrlClassification.book_score >= score_min)
    if is_book == "book":
        query = query.filter(UrlClassification.is_book_product.is_(True))
    elif is_book == "not_book":
        query = query.filter(UrlClassification.is_book_product.is_(False))
    total = query.count()
    order_col = DISCOVERED_URL_SORT_COLUMNS.get(sort_by, DiscoveredUrl.first_seen_at)
    if sort_order == "asc":
        query = query.order_by(order_col.asc().nulls_last())
    else:
        query = query.order_by(order_col.desc().nulls_last())
    urls = query.offset((page - 1) * per_page).limit(per_page).all()
    return urls, total


def get_scrape_activity_by_day(session: Session, days: int = 14) -> list[int]:
    """Return items scraped per day for the last N days (oldest first, zeros filled)."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    sql = text("""
        SELECT
            DATE(started_at AT TIME ZONE 'UTC') AS day,
            SUM(items_added + items_updated) AS items
        FROM scrape_runs
        WHERE started_at >= :cutoff AND status = 'completed'
        GROUP BY day
        ORDER BY day
    """)
    rows = session.execute(sql, {"cutoff": cutoff}).mappings().all()
    day_map: dict[str, int] = {str(r["day"]): int(r["items"]) for r in rows}
    result = []
    for i in range(days):
        day = (datetime.now(UTC) - timedelta(days=days - 1 - i)).date()
        result.append(day_map.get(str(day), 0))
    return result


def get_url_detail(
    session: Session, url_id: int
) -> tuple["DiscoveredUrl", "UrlClassification | None"] | None:
    stmt = (
        select(DiscoveredUrl)
        .options(
            joinedload(DiscoveredUrl.shop),
            joinedload(DiscoveredUrl.shop_book),
            joinedload(DiscoveredUrl.classification),
        )
        .where(DiscoveredUrl.id == url_id)
    )
    url = session.execute(stmt).unique().scalar_one_or_none()
    if url is None:
        return None
    return url, url.classification
