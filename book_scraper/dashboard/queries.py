import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Date, case, cast, func, or_, select, text
from sqlalchemy.orm import Session, joinedload

from book_scraper.dashboard.shop_book_filters import (
    ShopBookFieldFilter,
    apply_shop_book_field_filters,
)
from book_scraper.db.models import (
    DiscoveredUrl,
    Price,
    ScrapeFailure,
    ScrapeRun,
    ScrapeRunEvent,
    ScrapeUrlItem,
    Shop,
    ShopBook,
    ShopBookChange,
    ShopBookFieldUpdate,
    UrlClassification,
    ValidationIssue,
)
from book_scraper.settings import RETRY_CAP

logger = logging.getLogger(__name__)

_ISBN_RE = re.compile(r"^(?:\d{9}[\dX]|\d{13})$")


def _looks_like_isbn(value: str) -> str | None:
    """Return the normalized ISBN if the input looks like one, else None.

    Strips dashes/spaces, uppercases X. Accepts ISBN-10 (with optional
    trailing X) and ISBN-13. Used by /api/books?search= to choose between
    exact ISBN match and substring title/author match.
    """
    if not value:
        return None
    normalized = value.replace("-", "").replace(" ", "").upper()
    if not normalized:
        return None
    return normalized if _ISBN_RE.fullmatch(normalized) else None

STALE_HEARTBEAT_MINUTES = 5
# Coarse "dead" threshold for the run-list page's per-row badge. Kept
# generous so a momentary heartbeat tick lag does not flag a healthy run.
DEAD_RUN_MINUTES = 30
# Fast threshold for the dashboard reaper. The live view's freshness
# window is ~30s; we wait one extra minute past that before treating the
# run as dead and transitioning the row, which absorbs ordinary tick jitter.
DEAD_RUN_SECONDS = 60

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
    "invalid_isbn": (
        "The scraped ISBN-13 value fails the standard Luhn/check-digit validation"
        " or has the wrong digit count. Often an EAN-13 barcode picked up"
        " instead of the book's ISBN."
    ),
    "invalid_year": (
        "Publication year is outside the plausible range "
        "(before 1400 or in the future). "
        "Parser may be selecting a wrong numeric element."
    ),
    "year_pages_swap": (
        "Year and page-count appear to be swapped — e.g. year=312 and pages=2024."
        " Check the parser's attribute extraction order."
    ),
    "discover_fetch_failed": (
        "Category or sitemap page returned an error or timed out during URL discovery."
        " Transient network issues or a shop-side block."
    ),
    # ValidateService check groups
    "active_no_price": (
        "Book is marked active but has no price on record. The pricing element may have"
        " moved or the product was unpublished from the shop."
    ),
    "book_no_metadata": (
        "Book is classified as a book but is missing key metadata (ISBN, year, or author)."
        " Parser may be too permissive — check the classification logic."
    ),
    "book_no_signals": (
        "Book has no features that classify it as a book (no ISBN, no author, format is"
        " not a binding type). May be a non-book product that slipped through classification."
    ),
    "empty_response": (
        "The product page returned an empty body (HTTP 200 but no content). FlareSolverr"
        " may have timed out, or the shop serves an empty page for bot traffic."
    ),
    "format_is_dimensions": (
        "Format field contains what looks like physical dimensions (e.g. '210×297 mm')"
        " rather than a binding type. The parser is reading the wrong attribute."
    ),
    "in_stock_no_price": (
        "Book is marked in-stock but has no current price. The price may have been removed"
        " or the stock/price selectors are misaligned."
    ),
    "isbn_duplicate": (
        "Two or more shop books share the same ISBN-13. One is likely a data entry error"
        " or a reprinted edition. Check both entries and merge or correct."
    ),
    "match_isbn_drift": (
        "The ISBN on the shop book differs from the ISBN on its canonical book match."
        " One was likely corrected after the match was made — re-match or fix manually."
    ),
    "no_price_history": (
        "No price has ever been recorded for this book. It may never have been successfully"
        " scraped, or was discovered but never scanned."
    ),
    "non_book_has_isbn": (
        "Item classified as non-book but carries an ISBN-13. Re-examine the classification"
        " — it is likely a book."
    ),
    "non_product_active": (
        "A URL classified as non-product is still marked active. Either the classifier is"
        " wrong or the URL changed purpose."
    ),
    "orphan_no_url": (
        "Shop book record exists but has no linked discovered_url. This can happen if the"
        " URL was deleted from discovered_urls or was never discovered."
    ),
    "price_zero": (
        "Price scraped as 0.00. Parser probably matched an empty or placeholder element."
        " Same as zero_price — check parser selectors."
    ),
    "product_url_non_book": (
        "A URL classified as a product page but the shop book at that URL is classified as"
        " non-book. The product exists but is not a book — review classification."
    ),
    "sku_duplicate": (
        "Two shop books share the same shop SKU. SKUs should be unique identifiers —"
        " one entry is likely stale or mislabelled."
    ),
    "slug_title_mismatch": (
        "The URL slug and the scraped title diverge significantly. The parser may be"
        " picking up a wrong title element, or the shop renamed the product without"
        " updating the slug."
    ),
    "stale_active": (
        "Book is marked active but was last seen in a scrape run over 30 days ago."
        " It may have been silently delisted."
    ),
    "title_author_duplicate": (
        "Two or more shop books share the exact title and author. Could be duplicate data"
        " entry or a multi-format edition (print/ebook) that should be a single record."
    ),
    "unmatched_has_isbn": (
        "Book has a valid ISBN but no canonical book match. Either the match phase has not"
        " run yet or the ISBN is not in the canonical catalogue."
    ),
    "unreachable_active": (
        "Book is marked active but the URL consistently returns 404, 410, or connection"
        " error. The product has likely been removed."
    ),
    "url_aliases": (
        "Multiple distinct URLs resolve to the same product (e.g. via redirects or slug"
        " variants). The shop may serve the same page under multiple paths."
    ),
    "year_out_of_range": (
        "Publication year is before 1400 or in the future. The parser is likely picking up"
        " a wrong numeric element (e.g. page count or product ID)."
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
    "invalid_isbn": "warning",
    "invalid_year": "warning",
    "year_pages_swap": "warning",
    "discover_fetch_failed": "warning",
    # ValidateService check groups
    "active_no_price": "critical",
    "book_no_metadata": "warning",
    "book_no_signals": "info",
    "empty_response": "warning",
    "format_is_dimensions": "info",
    "in_stock_no_price": "critical",
    "isbn_duplicate": "warning",
    "match_isbn_drift": "warning",
    "no_price_history": "warning",
    "non_book_has_isbn": "warning",
    "non_product_active": "info",
    "orphan_no_url": "info",
    "price_zero": "critical",
    "product_url_non_book": "info",
    "sku_duplicate": "warning",
    "slug_title_mismatch": "info",
    "stale_active": "warning",
    "title_author_duplicate": "warning",
    "unmatched_has_isbn": "info",
    "unreachable_active": "warning",
    "url_aliases": "info",
    "year_out_of_range": "warning",
}


# Severity for scrape_failures (PR 2 of the migration). Driven by
# `error_reason` prefix when present; falls back to http_status range.
# Per-status reasons (`http_404`, `http_503`, ...) classify via the
# range, so we don't need to enumerate every status code.
SCRAPE_FAILURE_SEVERITY: dict[str, str] = {
    "request_error": "critical",
    "anti_bot_detected": "critical",
    "schema_drift": "critical",
    "rate_limited": "warning",
    "robots_disallowed": "warning",
    "soft_404": "warning",
}


def severity_for_failure(error_reason: str | None, http_status: int | None) -> str:
    """Classify a scrape failure's severity. http_status range wins
    when set so per-status reasons (`http_503`) resolve via the bucket
    without backfilling the data.

    NULL/unknown defaults to `warning` — the operator can still triage
    explicitly via the lifecycle state."""
    if http_status is not None:
        if 400 <= http_status < 500:
            return "warning"
        if 500 <= http_status < 600:
            return "warning"
    if error_reason:
        prefix = error_reason.split(":", 1)[0]
        return SCRAPE_FAILURE_SEVERITY.get(prefix, "warning")
    return "warning"


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


def mark_stale_runs(session: Session) -> list[dict[str, Any]]:
    """Mark runs with no heartbeat for over DEAD_RUN_SECONDS as failed.

    Reaped runs are flagged ``resumable_after_failure`` so the next
    scheduled run inherits any pending items rather than dropping them.
    Pending rows are explicitly NOT touched here; only `processing` rows
    get aborted via ``abort_processing_scrape_url_items``.

    Also reaps runs stuck in `stopping` whose heartbeat has gone stale —
    that means the spider observed the operator-requested stop but its
    `closed()` callback never ran (process crash mid-shutdown). The
    error reason is recorded as `stop_timeout` so the postmortem
    distinguishes it from ordinary heartbeat death.

    Returns a list of dicts with per-run metadata for each killed run.
    Each dict has keys: run_id, shop, phase, close_reason. The dashboard
    reaper logs one WARNING per dict so the postmortem trail names what
    it killed.
    """
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.repo import (
        abort_processing_scrape_url_items,
        emit_scrape_run_event,
        record_scrape_run_failed_issue,
        sweep_orphaned_processing_items,
    )

    cutoff = datetime.now(UTC) - timedelta(seconds=DEAD_RUN_SECONDS)
    # 'paused' is intentionally alive — heartbeat keeps ticking during
    # pause, so a paused run won't appear stale. Do NOT include it here.
    stale = (
        session.query(ScrapeRun)
        .filter(ScrapeRun.status.in_(("running", "stopping")))
        .all()
    )
    killed: list[dict[str, Any]] = []
    for run in stale:
        last_activity = run.last_heartbeat or run.started_at
        if last_activity and last_activity < cutoff:
            reason = "stop_timeout" if run.status == "stopping" else "heartbeat_timeout"
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            run.resumable_after_failure = True
            # close_reason is stamped inside record_scrape_run_failed_issue
            # (first writer wins), keeping the reason on the run row itself.
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
            killed.append({
                "run_id": run.id,
                "shop": run.shop.name if run.shop else "<unknown>",
                "phase": str(run.phase),
                "close_reason": reason,
            })
    cleaned = sweep_orphaned_processing_items(session)
    if killed or cleaned:
        session.commit()
    return killed


def get_overview_stats(session: Session) -> dict[str, Any]:
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


def get_schedule_info(session: Session) -> list[dict[str, Any]]:
    """Return schedule metadata for every enabled cron job.

    For each job: next firing time (via croniter), time-until-next (seconds),
    and the most recent completed run's finished_at for "last success" badge.
    """
    from croniter import croniter  # type: ignore[import-untyped]

    from book_scraper.db.models import CronJob

    jobs = (
        session.query(CronJob)
        .options(joinedload(CronJob.shop))
        .filter(CronJob.enabled.is_(True))
        .order_by(CronJob.id)
        .all()
    )
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for job in jobs:
        next_dt: datetime | None
        next_in_s: int | None
        try:
            cron = croniter(job.cron_expression, now)
            next_dt = cron.get_next(datetime).replace(tzinfo=UTC)
            next_in_s = int((next_dt - now).total_seconds())
        except Exception:
            next_dt = None
            next_in_s = None

        # scrape_runs stores the combined phase (e.g. 'discover_sitemap').
        # cron_jobs stores phase + strategy separately. Scan has no suffix
        # regardless of strategy — avoid invalid 'scan_delta' enum value.
        if job.phase == "scan":
            run_phase = "scan"
        elif job.phase == "discover" and job.strategy:
            run_phase = f"discover_{job.strategy}"
        else:
            run_phase = job.phase
        last_ok = (
            session.query(ScrapeRun)
            .filter(
                ScrapeRun.shop_id == job.shop_id,
                ScrapeRun.phase == run_phase,
                ScrapeRun.status == "completed",
            )
            .order_by(ScrapeRun.finished_at.desc().nullslast())
            .limit(1)
            .one_or_none()
        )
        out.append(
            {
                "shop": job.shop.name,
                "phase": job.phase,
                "cron_expression": job.cron_expression,
                "next_run_at": next_dt.isoformat() if next_dt else None,
                "next_run_in_s": next_in_s,
                "last_success_at": (
                    last_ok.finished_at.isoformat()
                    if last_ok and last_ok.finished_at
                    else None
                ),
                "last_run_at": (
                    job.last_run_at.isoformat() if job.last_run_at else None
                ),
            }
        )
    return out


def get_run_eta(
    session: Session,
    run_id: int,
    req_per_min: float,
) -> int | None:
    """Estimate minutes remaining for a running scan.

    Uses the current pending URL count divided by the observed request
    rate. Returns None when rate is zero (stalled) or pending count
    is unavailable.
    """
    from book_scraper.db.models import ScrapeUrlItem

    if req_per_min <= 0:
        return None
    pending = (
        session.query(func.count(ScrapeUrlItem.id))
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status == "pending",
        )
        .scalar()
        or 0
    )
    if pending == 0:
        return 0
    return max(1, round(pending / req_per_min))


def get_recent_runs(session: Session, limit: int = 20) -> list[ScrapeRun]:
    return (
        session.query(ScrapeRun)
        .options(joinedload(ScrapeRun.shop))
        .order_by(ScrapeRun.started_at.desc())
        .limit(limit)
        .all()
    )


# Threshold for the repeated-failure banner. N consecutive terminal runs
# of the same shop+phase ending in `failed` with the same `error_reason`
# trigger the banner. 3 catches systemic problems early without flagging
# transient flakes.
REPEATED_FAILURE_THRESHOLD = 3


def get_repeated_failures(
    session: Session, threshold: int = REPEATED_FAILURE_THRESHOLD
) -> list[dict[str, Any]]:
    """Detect shop+phase combinations whose last `threshold` terminal
    runs all ended in `failed` with the same recorded error_reason.

    A genuinely transient failure (different reason each time) does not
    trigger the banner. A success in the window resets the streak.

    Returns one dict per affected (shop, phase): `shop`, `phase`,
    `count` (consecutive failures), `error_reason` (the shared cluster),
    `latest_run_id` (most recent failed run's id, for deep-link).
    """
    from book_scraper.db.models import Shop

    # Pull the last `threshold` terminal runs per (shop, phase). We
    # do this in Python to keep the SQL portable and the logic
    # readable; volume is low (handful of shops × handful of phases).
    pairs = (
        session.query(ScrapeRun.shop_id, ScrapeRun.phase)
        .filter(ScrapeRun.status.in_(("completed", "failed")))
        .group_by(ScrapeRun.shop_id, ScrapeRun.phase)
        .all()
    )
    out: list[dict[str, Any]] = []
    for shop_id, phase in pairs:
        recent = (
            session.query(ScrapeRun)
            .filter(
                ScrapeRun.shop_id == shop_id,
                ScrapeRun.phase == phase,
                ScrapeRun.status.in_(("completed", "failed")),
            )
            .order_by(ScrapeRun.finished_at.desc().nullslast())
            .limit(threshold)
            .all()
        )
        if len(recent) < threshold:
            continue
        if not all(r.status == "failed" for r in recent):
            continue
        # Pull the recorded reason cluster from validation_issues
        # (`record_scrape_run_failed_issue` writes one row per failed run).
        ids = [r.id for r in recent]
        reasons = (
            session.query(ValidationIssue.last_seen_run_id, ValidationIssue.raw_value)
            .filter(
                ValidationIssue.last_seen_run_id.in_(ids),
                ValidationIssue.issue == "scrape_run_failed",
            )
            .all()
        )
        reason_by_run = {r[0]: r[1] for r in reasons}
        observed = {reason_by_run.get(r.id) for r in recent}
        observed.discard(None)
        if len(observed) != 1:
            # Different reasons → genuinely transient; don't alert.
            continue
        shared_reason = next(iter(observed))
        shop_name = session.query(Shop.name).filter(Shop.id == shop_id).scalar() or "?"
        out.append(
            {
                "shop": shop_name,
                "phase": phase,
                "count": threshold,
                "error_reason": shared_reason,
                "latest_run_id": recent[0].id,
            }
        )
    return out


def get_run_detail(session: Session, run_id: int) -> ScrapeRun | None:
    return session.get(ScrapeRun, run_id)


def get_scrape_run_events(session: Session, run_id: int) -> list[dict[str, Any]]:
    """Lifecycle events for a run, oldest first."""
    rows = (
        session.query(ScrapeRunEvent)
        .filter(ScrapeRunEvent.run_id == run_id)
        .order_by(ScrapeRunEvent.created_at.asc(), ScrapeRunEvent.id.asc())
        .all()
    )
    return [
        {
            "id": r.id,
            "event_type": r.event_type,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "actor": r.actor,
            "payload": r.payload,
        }
        for r in rows
    ]


def get_run_close_reason(session: Session, run: ScrapeRun) -> str | None:
    """Why the run reached its current state.

    Returns None for non-terminal runs. For terminal runs:
      - completed + no errors  → 'completed_ok'
      - completed + errors     → 'completed_with_errors'
      - failed                 → reason text from the run's
        `scrape_run_failed` validation issue (heartbeat_timeout,
        stall_timeout, stop_timeout, stopped_by_operator, orphan_on_boot,
        finished_failed, …) or 'failed' if the issue row is missing.
    """
    if run.status == "completed":
        return "completed_with_errors" if run.error_count > 0 else "completed_ok"
    if run.status == "failed":
        row = (
            session.query(ValidationIssue.raw_value)
            .filter(
                ValidationIssue.last_seen_run_id == run.id,
                ValidationIssue.issue == "scrape_run_failed",
            )
            .order_by(ValidationIssue.id.desc())
            .first()
        )
        if row and row[0]:
            return str(row[0])
        return "failed"
    return None


def get_run_item_counts(session: Session, run_id: int) -> dict[str, int]:
    """Return how many shop_books were created and updated in this run.

    More reliable than ScrapeRun.items_added/items_updated, which are
    spider-side batch counters that don't flush on a reaped failure.

    - created: shop_books whose created_run_id == run_id (immutable, set once).
               Runs before the created_run_id migration return 0 (forward-only).
    - updated: DISTINCT shop_book_ids in shop_book_changes for this run.
               This table is append-only — survives crashed/reaped runs.
    """
    created = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.created_run_id == run_id)
        .scalar()
        or 0
    )
    updated = (
        session.query(func.count(func.distinct(ShopBookChange.shop_book_id)))
        .filter(ShopBookChange.scrape_run_id == run_id)
        .scalar()
        or 0
    )
    return {"items_added": int(created), "items_updated": int(updated)}


def get_run_books_added(
    session: Session, run_id: int, page: int = 1, per_page: int = 50
) -> tuple[list[ShopBook], int]:
    """Return paginated shop_books created in this run (immutable created_run_id)."""
    query = (
        session.query(ShopBook)
        .options(joinedload(ShopBook.shop))
        .filter(ShopBook.created_run_id == run_id)
        .order_by(ShopBook.title)
    )
    total = query.count()
    books = query.offset((page - 1) * per_page).limit(per_page).all()
    return books, total


def get_run_books_updated(
    session: Session, run_id: int, page: int = 1, per_page: int = 50
) -> tuple[list[tuple[ShopBook, str]], int]:
    """Return paginated shop_books that had tracked field changes in this run.

    Each result is (ShopBook, changed_fields) where changed_fields is a
    comma-separated string of distinct field names that changed (e.g. "price, title").
    """
    subq = (
        session.query(
            ShopBookChange.shop_book_id,
            func.string_agg(func.distinct(ShopBookChange.field), ", ").label(
                "changed_fields"
            ),
        )
        .filter(ShopBookChange.scrape_run_id == run_id)
        .group_by(ShopBookChange.shop_book_id)
        .subquery()
    )
    query = (
        session.query(ShopBook, subq.c.changed_fields)
        .options(joinedload(ShopBook.shop))
        .join(subq, ShopBook.id == subq.c.shop_book_id)
        .order_by(ShopBook.title)
    )
    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    return [(sb, cf) for sb, cf in rows], total


# ─────────────────── Live observability (Stage 2) ────────────────────
# Live-view thresholds — sharper than the run-list page's STALE/DEAD
# constants because the live view refreshes every ~2s and operators
# expect fast feedback. See live observability spec.
LIVE_DEAD_HEARTBEAT_S = 30
LIVE_RATE_WINDOW_S = 60


def get_run_live_health(run: ScrapeRun) -> str:
    """Live-view health verdict for a single run.

    Returns 'healthy' | 'stuck' | 'dead' | '' (non-running).

    Combines heartbeat staleness with claimed_at age on the in-flight
    row(s):
      - heartbeat stale  → 'dead' (process gone)
      - heartbeat fresh + an in-flight row's claimed_at older than
        DOWNLOAD_TIMEOUT × 2 → 'stuck' (alive but hung)
      - else → 'healthy'

    DOWNLOAD_TIMEOUT is fixed at 15 here to match settings.py without
    introducing a Scrapy import in the dashboard codepath.
    """
    if run.status != "running":
        return ""
    now = datetime.now(UTC)
    last_activity = run.last_heartbeat or run.started_at
    if last_activity is None:
        return "dead"
    if (now - last_activity).total_seconds() > LIVE_DEAD_HEARTBEAT_S:
        return "dead"
    return "healthy"  # 'stuck' is decided at the route level, where
    # we already have the in-flight row data and can compute the
    # threshold cheaply without re-querying.


IN_FLIGHT_RENDER_CAP = 50


def get_run_in_flight(session: Session, run_id: int) -> list[dict[str, Any]]:
    """Currently-processing rows for a run.

    Stable order: oldest claimed_at first, then by id. Capped at
    ``IN_FLIGHT_RENDER_CAP`` rows: a healthy live run normally has 1
    (CONCURRENT_REQUESTS_PER_DOMAIN), and a terminal run should have 0
    after `abort_processing_scrape_url_items` fires. A stranded run
    with hundreds of orphaned 'processing' rows would otherwise blow
    up the dashboard's "Now fetching" panel and push the rest of the
    page out of reach.
    """
    rows = (
        session.query(ScrapeUrlItem)
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status == "processing",
        )
        .order_by(ScrapeUrlItem.claimed_at.asc(), ScrapeUrlItem.id.asc())
        .limit(IN_FLIGHT_RENDER_CAP)
        .all()
    )
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for r in rows:
        claimed_at = r.claimed_at
        claimed_age_s: float | None = None
        if claimed_at is not None:
            if claimed_at.tzinfo is None:
                claimed_at = claimed_at.replace(tzinfo=UTC)
            claimed_age_s = max(0.0, (now - claimed_at).total_seconds())
        out.append(
            {
                "url": r.url,
                "claimed_at": (
                    claimed_at.isoformat() if claimed_at is not None else None
                ),
                "claimed_age_s": claimed_age_s,
                "request_delay_s": r.request_delay_s,
                "delay_source": r.delay_source,
                "retry_count": r.retry_count,
            }
        )
    return out


def get_run_rate_window(
    session: Session, run_id: int, seconds: int = LIVE_RATE_WINDOW_S
) -> dict[str, int]:
    """Counts of done / failed rows whose done_at is within the window."""
    cutoff = datetime.now(UTC) - timedelta(seconds=seconds)
    done = (
        session.query(func.count(ScrapeUrlItem.id))
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status == "done",
            ScrapeUrlItem.done_at.isnot(None),
            ScrapeUrlItem.done_at > cutoff,
        )
        .scalar()
        or 0
    )
    failed = (
        session.query(func.count(ScrapeUrlItem.id))
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status == "failed",
            ScrapeUrlItem.done_at.isnot(None),
            ScrapeUrlItem.done_at > cutoff,
        )
        .scalar()
        or 0
    )
    return {
        "window_s": seconds,
        "done": int(done),
        "failed": int(failed),
    }


def _row_to_activity_entry(
    r: "ScrapeUrlItem",
    now: datetime,
    error_reason: str | None = None,
) -> dict[str, Any]:
    """Convert a ScrapeUrlItem into the activity-stream dict shape.

    `error_reason` comes from the latest `scrape_failures` event for the
    item (PR 3 of the migration: the queue's `error_reason` column is
    being dropped). Caller pre-fetches and passes the value; only
    meaningful for rows whose status is `failed`.
    """
    claimed_at = r.claimed_at
    if claimed_at is not None and claimed_at.tzinfo is None:
        claimed_at = claimed_at.replace(tzinfo=UTC)
    done_at = r.done_at
    if done_at is not None and done_at.tzinfo is None:
        done_at = done_at.replace(tzinfo=UTC)
    duration_s: float | None = None
    if claimed_at is not None and done_at is not None:
        duration_s = max(0.0, (done_at - claimed_at).total_seconds())
    done_age_s: float | None = None
    if done_at is not None:
        done_age_s = max(0.0, (now - done_at).total_seconds())
    return {
        "url": r.url,
        "status": r.status,
        "http_status": r.http_status,
        "error_reason": error_reason if r.status == "failed" else None,
        "claimed_at": claimed_at.isoformat() if claimed_at is not None else None,
        "done_at": done_at.isoformat() if done_at is not None else None,
        "duration_s": duration_s,
        "done_age_s": done_age_s,
        "request_delay_s": r.request_delay_s,
        "delay_source": r.delay_source,
        "response_bytes": r.response_bytes,
    }


def get_run_recent_failures(
    session: Session, run_id: int, limit: int = 10
) -> list[dict[str, Any]]:
    """Most-recent failed rows for a run."""
    latest = (
        session.query(
            ScrapeFailure.scrape_url_item_id,
            ScrapeFailure.error_reason,
            func.row_number()
            .over(
                partition_by=ScrapeFailure.scrape_url_item_id,
                order_by=(
                    ScrapeFailure.occurred_at.desc(),
                    ScrapeFailure.id.desc(),
                ),
            )
            .label("rn"),
        )
        .filter(ScrapeFailure.run_id == run_id)
        .subquery()
    )
    rows = (
        session.query(ScrapeUrlItem, latest.c.error_reason)
        .outerjoin(
            latest,
            (latest.c.scrape_url_item_id == ScrapeUrlItem.id) & (latest.c.rn == 1),
        )
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status == "failed",
        )
        .order_by(ScrapeUrlItem.done_at.desc().nullslast(), ScrapeUrlItem.id.desc())
        .limit(limit)
        .all()
    )
    now = datetime.now(UTC)
    return [_row_to_activity_entry(r, now, reason) for r, reason in rows]


FAILURE_RECURRENCE_LOOKBACK_RUNS = 5


def get_run_failure_groups(
    session: Session,
    run_id: int,
    limit_examples: int = 3,
    include_acked: bool = False,
) -> list[dict[str, Any]]:
    """Failure types for a run, grouped by (error_reason, http_status).

    Reads from the append-only `scrape_failures` event log (PR 2 of the
    scrape-failures migration). Two filters in tandem ensure the card
    reflects "what is failed *right now* in this run", not the historical
    timeline:
    - Pick each item's latest event by `occurred_at` via ROW_NUMBER().
    - JOIN `scrape_url_items` and require `status='failed'` so a URL that
      was retried and succeeded falls off the card immediately.

    `recurring_in_runs` is computed status-blind against the last
    `FAILURE_RECURRENCE_LOOKBACK_RUNS` prior runs for the same shop —
    operators want to know "how often has this kind of failure happened",
    even for buckets that already cleared in earlier runs.

    `include_acked=False` (default) hides groups whose latest event is
    `lifecycle_state='already_seen'`.
    """
    run = session.get(ScrapeRun, run_id)
    if run is None:
        return []

    # Subquery: latest scrape_failures event per (run_id, scrape_url_item).
    latest = (
        session.query(
            ScrapeFailure.id,
            ScrapeFailure.scrape_url_item_id,
            ScrapeFailure.error_reason,
            ScrapeFailure.http_status,
            ScrapeFailure.lifecycle_state,
            ScrapeFailure.error_detail,
            func.row_number()
            .over(
                partition_by=ScrapeFailure.scrape_url_item_id,
                order_by=(
                    ScrapeFailure.occurred_at.desc(),
                    ScrapeFailure.id.desc(),
                ),
            )
            .label("rn"),
        )
        .filter(ScrapeFailure.run_id == run_id)
        .subquery()
    )

    # Conditional aggregation: count latest-failed events per bucket, split
    # by lifecycle state so the UI can show "(N unacked · M total)" without
    # a second roundtrip.
    unacked_expr = func.sum(
        case((latest.c.lifecycle_state != "acknowledged", 1), else_=0)
    ).label("unacked_count")
    acked_expr = func.sum(
        case((latest.c.lifecycle_state == "acknowledged", 1), else_=0)
    ).label("acked_count")
    # Group-level retry-cap stats: surface per-bucket "max attempts seen" and
    # "how many items already exhausted the cap" so operators can spot
    # buckets where retries won't help anymore (Task 12 of the
    # restart-and-retry plan).
    max_attempts_expr = func.max(ScrapeUrlItem.attempts).label("max_attempts")
    capped_expr = func.sum(
        case((ScrapeUrlItem.attempts >= RETRY_CAP, 1), else_=0)
    ).label("capped_count")

    base = (
        session.query(
            latest.c.error_reason,
            latest.c.http_status,
            unacked_expr,
            acked_expr,
            max_attempts_expr,
            capped_expr,
        )
        .join(ScrapeUrlItem, ScrapeUrlItem.id == latest.c.scrape_url_item_id)
        .filter(latest.c.rn == 1, ScrapeUrlItem.status == "failed")
        .group_by(latest.c.error_reason, latest.c.http_status)
    )
    if not include_acked:
        # Hide buckets where every latest event is acknowledged.
        base = base.having(unacked_expr > 0)

    rows = base.order_by(unacked_expr.desc(), acked_expr.desc()).all()

    # Recurrence lookup: for each (reason, http) bucket in this run, count
    # how many of the last N prior runs (same shop) had ≥1 scrape_failures
    # event in the same bucket. Status-blind: history is the question.
    prior_run_ids: list[int] = []
    if rows:
        prior_run_ids = [
            rid
            for (rid,) in (
                session.query(ScrapeRun.id)
                .filter(
                    ScrapeRun.shop_id == run.shop_id,
                    ScrapeRun.id != run_id,
                    ScrapeRun.started_at.isnot(None),
                )
                .order_by(ScrapeRun.started_at.desc())
                .limit(FAILURE_RECURRENCE_LOOKBACK_RUNS)
                .all()
            )
        ]

    out: list[dict[str, Any]] = []
    for (
        reason,
        http,
        unacked_count,
        acked_count,
        max_attempts,
        capped_count,
    ) in rows:
        unacked_count = int(unacked_count or 0)
        acked_count = int(acked_count or 0)
        max_attempts = int(max_attempts or 0)
        capped_count = int(capped_count or 0)
        recurring_runs = 0
        if prior_run_ids:
            reason_pred = (
                ScrapeFailure.error_reason.is_(None)
                if reason is None
                else ScrapeFailure.error_reason == reason
            )
            http_pred = (
                ScrapeFailure.http_status.is_(None)
                if http is None
                else ScrapeFailure.http_status == http
            )
            recurring_runs = (
                session.query(func.count(func.distinct(ScrapeFailure.run_id)))
                .filter(
                    ScrapeFailure.run_id.in_(prior_run_ids),
                    reason_pred,
                    http_pred,
                )
                .scalar()
                or 0
            )

        # Examples come from the same latest-failed slice the count was
        # computed from — so retried-and-succeeded URLs are excluded.
        # Each example carries `error_detail` (full traceback / message) so
        # the UI can show it inline without a second roundtrip.
        examples_reason_pred = (
            latest.c.error_reason.is_(None)
            if reason is None
            else latest.c.error_reason == reason
        )
        examples_http_pred = (
            latest.c.http_status.is_(None)
            if http is None
            else latest.c.http_status == http
        )
        examples_q = (
            session.query(ScrapeUrlItem.url, latest.c.error_detail)
            .join(latest, latest.c.scrape_url_item_id == ScrapeUrlItem.id)
            .filter(
                latest.c.rn == 1,
                ScrapeUrlItem.status == "failed",
                examples_reason_pred,
                examples_http_pred,
            )
        )
        if not include_acked:
            examples_q = examples_q.filter(latest.c.lifecycle_state != "acknowledged")
        examples = [
            {
                "url": url,
                # Cap detail to keep payloads small even with monster tracebacks.
                "error_detail": (detail[:4000] if detail else None),
            }
            for url, detail in examples_q.limit(limit_examples).all()
        ]

        # `count` preserves prior contract: when default include_acked=False,
        # it equals the number of currently-failed unacked rows. When
        # include_acked=True, it equals total latest-failed rows in the
        # bucket so headers can still sum to a meaningful total.
        count = unacked_count if not include_acked else unacked_count + acked_count

        out.append(
            {
                "reason": reason,
                "reason_display": reason or "unknown",
                "reason_is_null": reason is None,
                "http": http,
                "http_is_null": http is None,
                "count": count,
                "unacked_count": unacked_count,
                "acked_count": acked_count,
                "recurring_in_runs": int(recurring_runs),
                "max_attempts": max_attempts,
                "capped_count": capped_count,
                "examples": examples,
            }
        )
    return out


def get_run_recent_activity(
    session: Session, run_id: int, limit: int = 20
) -> list[dict[str, Any]]:
    """Most-recent done OR failed rows for a run, newest first.

    Returns full timing detail: start (claimed_at), finish (done_at),
    duration, throttle delay applied, response bytes. Used by the live
    panel so an operator can see exactly when each request started and
    finished, not just relative ages.

    Failed rows include their `error_reason` from the latest
    `scrape_failures` event (PR 3 — `scrape_url_items.error_reason` was
    dropped); done rows pass `error_reason=None` through.
    """
    latest = (
        session.query(
            ScrapeFailure.scrape_url_item_id,
            ScrapeFailure.error_reason,
            func.row_number()
            .over(
                partition_by=ScrapeFailure.scrape_url_item_id,
                order_by=(
                    ScrapeFailure.occurred_at.desc(),
                    ScrapeFailure.id.desc(),
                ),
            )
            .label("rn"),
        )
        .filter(ScrapeFailure.run_id == run_id)
        .subquery()
    )
    rows = (
        session.query(ScrapeUrlItem, latest.c.error_reason)
        .outerjoin(
            latest,
            (latest.c.scrape_url_item_id == ScrapeUrlItem.id) & (latest.c.rn == 1),
        )
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status.in_(("done", "failed")),
            ScrapeUrlItem.done_at.isnot(None),
        )
        .order_by(ScrapeUrlItem.done_at.desc(), ScrapeUrlItem.id.desc())
        .limit(limit)
        .all()
    )
    now = datetime.now(UTC)
    return [_row_to_activity_entry(r, now, reason) for r, reason in rows]


RUN_URL_STATUSES = ("pending", "processing", "done", "failed")


def get_run_url_breakdown(session: Session, run_id: int) -> dict[str, int]:
    """Counts of scrape_url_items per status for a run.

    scrape_url_items rows are now kept after the run finishes (used to be
    deleted via the removed `cleanup_scrape_url_items`), so this returns
    real counts for both live and terminal runs.
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


RUN_URL_SORT_KEYS = (
    "id",
    "started",  # claimed_at
    "done",  # done_at
    "duration",  # done_at - claimed_at
    "status",
    "http",  # http_status
    "url_type",
    "url",
    "title",
)


def get_run_url_items(
    session: Session,
    run_id: int,
    status: str = "all",
    page: int = 1,
    per_page: int = 50,
    sort: str = "started",
    order: str = "desc",
    error_reason: str = "",
    error_reason_is_null: bool = False,
    http_status: int | None = None,
    http_status_is_null: bool = False,
) -> tuple[list[tuple[ScrapeUrlItem, str | None, int | None, str | None]], int]:
    """Live URL queue for a run, paginated. Returns
    ((item, title, shop_book_id, latest_error_reason), total).

    `title` and `shop_book_id` are left-joined from `shop_books` (matched on
    shop_id + url) and are `None` for URLs that didn't produce a book product.

    `latest_error_reason` is the `error_reason` of the latest
    `scrape_failures` event for the item (or NULL if the item has no failure
    history). PR 3 of the migration: `scrape_url_items.error_reason` is
    going away, so the History card reads the reason from this projection.

    The `error_reason` / `http_status` filters target the failure-group
    keys on the Failures card. Both columns are nullable, so each has an
    explicit `*_is_null` flag — that flag wins if both are sent (defensive,
    avoids any string-sentinel ambiguity).
    """
    from sqlalchemy import case

    needs_failure_filter = (
        error_reason_is_null
        or bool(error_reason)
        or http_status_is_null
        or http_status is not None
    )

    # Always JOIN the latest scrape_failures event so the row builder can
    # display the reason without a second query. INNER JOIN when filtering
    # (rows without a matching event are excluded), LEFT OUTER otherwise.
    latest_failure = (
        session.query(
            ScrapeFailure.scrape_url_item_id,
            ScrapeFailure.error_reason,
            ScrapeFailure.http_status,
            func.row_number()
            .over(
                partition_by=ScrapeFailure.scrape_url_item_id,
                order_by=(
                    ScrapeFailure.occurred_at.desc(),
                    ScrapeFailure.id.desc(),
                ),
            )
            .label("rn"),
        )
        .filter(ScrapeFailure.run_id == run_id)
        .subquery()
    )

    query = (
        session.query(
            ScrapeUrlItem,
            ShopBook.title,
            ShopBook.id,
            latest_failure.c.error_reason,
        )
        .outerjoin(
            ShopBook,
            (ShopBook.shop_id == ScrapeUrlItem.shop_id)
            & (ShopBook.url == ScrapeUrlItem.url),
        )
        .filter(ScrapeUrlItem.run_id == run_id)
    )
    if status in RUN_URL_STATUSES:
        query = query.filter(ScrapeUrlItem.status == status)

    if needs_failure_filter:
        query = query.join(
            latest_failure,
            latest_failure.c.scrape_url_item_id == ScrapeUrlItem.id,
        ).filter(latest_failure.c.rn == 1)
        if error_reason_is_null:
            query = query.filter(latest_failure.c.error_reason.is_(None))
        elif error_reason:
            query = query.filter(latest_failure.c.error_reason == error_reason)
        if http_status_is_null:
            query = query.filter(latest_failure.c.http_status.is_(None))
        elif http_status is not None:
            query = query.filter(latest_failure.c.http_status == http_status)
    else:
        query = query.outerjoin(
            latest_failure,
            (latest_failure.c.scrape_url_item_id == ScrapeUrlItem.id)
            & (latest_failure.c.rn == 1),
        )

    total = query.count()

    if sort not in RUN_URL_SORT_KEYS:
        sort = "started"
    desc = order != "asc"

    sort_col: Any
    if sort == "id":
        sort_col = ScrapeUrlItem.id
    elif sort == "started":
        sort_col = ScrapeUrlItem.claimed_at
    elif sort == "done":
        sort_col = ScrapeUrlItem.done_at
    elif sort == "duration":
        # Approx duration; rows with no claimed_at sort last via nulls_last.
        sort_col = ScrapeUrlItem.done_at - ScrapeUrlItem.claimed_at
    elif sort == "status":
        # Stable, intuitive order: processing → pending → failed → done.
        sort_col = case(
            (ScrapeUrlItem.status == "processing", 0),
            (ScrapeUrlItem.status == "pending", 1),
            (ScrapeUrlItem.status == "failed", 2),
            (ScrapeUrlItem.status == "done", 3),
            else_=4,
        )
    elif sort == "http":
        sort_col = ScrapeUrlItem.http_status
    elif sort == "url_type":
        sort_col = ScrapeUrlItem.url_type
    elif sort == "title":
        sort_col = ShopBook.title
    else:  # url
        sort_col = ScrapeUrlItem.url

    ordering = sort_col.desc().nulls_last() if desc else sort_col.asc().nulls_last()
    rows = (
        query.order_by(ordering, ScrapeUrlItem.id.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return [
        (it, title, sb_id, latest_reason) for it, title, sb_id, latest_reason in rows
    ], total


_PHASE_TO_SOURCE: dict[str, str] = {
    "discover_sitemap": "sitemap",
    "discover_categories": "category",
    "discover_full_crawl": "full_crawl",
}


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
    source = _PHASE_TO_SOURCE.get(run.phase)
    if source:
        query = query.filter(DiscoveredUrl.source == source)
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
        .filter(ValidationIssue.last_seen_run_id == run_id)
        .group_by(ValidationIssue.field, ValidationIssue.issue)
        .order_by(func.count(ValidationIssue.id).desc())
        .all()
    )
    return [{"field": r.field, "issue": r.issue, "count": r.count} for r in rows]


def get_validation_summary(
    session: Session, state: str | None = None
) -> list[dict[str, Any]]:
    q = session.query(
        ValidationIssue.issue,
        func.count(ValidationIssue.id).label("count"),
    )
    if state in {"new", "acknowledged", "snoozed", "resolved"}:
        q = q.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        q = q.filter(ValidationIssue.lifecycle_state == "new")
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
    """Bucket counts of issues by lifecycle state under the same filter
    semantics as `get_issues_page`. Used by the stat strip + lifecycle tabs."""
    from sqlalchemy import or_

    query = session.query(
        ValidationIssue.lifecycle_state,
        func.count(ValidationIssue.id).label("cnt"),
    )
    if shop_id is not None:
        query = query.filter(ValidationIssue.shop_id == shop_id)
    if issue_type:
        query = query.filter(ValidationIssue.issue == issue_type)
    if run_id is not None:
        query = query.filter(ValidationIssue.last_seen_run_id == run_id)
    if severity:
        severity_types = [k for k, v in ISSUE_SEVERITY.items() if v == severity]
        query = query.filter(ValidationIssue.issue.in_(severity_types))
    if q:
        pattern = f"%{q}%"
        query = query.outerjoin(
            ShopBook, ValidationIssue.shop_book_id == ShopBook.id
        ).filter(or_(ValidationIssue.url.ilike(pattern), ShopBook.title.ilike(pattern)))
    rows = query.group_by(ValidationIssue.lifecycle_state).all()
    counts = {r.lifecycle_state: r.cnt for r in rows}
    return {
        "new": counts.get("new", 0),
        "acknowledged": counts.get("acknowledged", 0),
        "snoozed": counts.get("snoozed", 0),
        "resolved": counts.get("resolved", 0),
        "total": sum(counts.values()),
    }


def get_issue_counts(session: Session, shop_id: int | None = None) -> dict[str, int]:
    """Return counts by lifecycle state for badge display."""
    q = select(
        ValidationIssue.lifecycle_state,
        func.count().label("cnt"),
    ).group_by(ValidationIssue.lifecycle_state)
    if shop_id is not None:
        q = q.where(ValidationIssue.shop_id == shop_id)
    rows = session.execute(q).all()
    counts = {r.lifecycle_state: r.cnt for r in rows}
    return {
        "new": counts.get("new", 0),
        "acknowledged": counts.get("acknowledged", 0),
        "snoozed": counts.get("snoozed", 0),
        "resolved": counts.get("resolved", 0),
        "total": sum(counts.values()),
    }


ISSUE_KIND_VALIDATION = "validation"
ISSUE_KIND_SCRAPE_FAILURE = "scrape_failure"


def get_issues_page(
    session: Session,
    state: str | None = "open",
    shop_id: int | None = None,
    issue_type: str = "",
    run_id: int | None = None,
    q: str = "",
    severity: str = "",
    url_type: str = "",
    book_type: str = "",
    order: str = "desc",
    page: int = 1,
    per_page: int = 50,
    kind: str = "all",
) -> tuple[list[dict[str, Any]], int]:
    """Return paginated flat list of issues with filters.

    PR 2 of the scrape-failures migration: the inbox now spans both
    `validation_issues` (parser-level data quality) and `scrape_failures`
    (transport / HTTP-level events). `kind="validation"` or
    `"scrape_failure"` narrows to one source; the default `"all"` merges
    them and pages the combined result.

    Rows from `validation_issues` are sorted by `scrape_runs.started_at`
    (added_at proxy). Rows from `scrape_failures` use their own
    `occurred_at`. The merged view sorts by added_at across both.

    Returns (rows, total).
    """

    rows: list[dict[str, Any]] = []
    total = 0

    # Single-kind: helper paginates directly. Merged: fetch up to
    # `page*per_page` rows from each source, merge, sort, slice. The
    # pigeonhole holds — the Nth-newest merged row must be in the top
    # N*per_page from at least one source.
    helper_page = 1 if kind == "all" else page
    helper_per_page = page * per_page if kind == "all" else per_page

    if kind in ("all", ISSUE_KIND_VALIDATION):
        v_rows, v_total = _get_validation_issues_page(
            session,
            state=state,
            shop_id=shop_id,
            issue_type=issue_type,
            run_id=run_id,
            q=q,
            severity=severity,
            url_type=url_type,
            book_type=book_type,
            order=order,
            page=helper_page,
            per_page=helper_per_page,
        )
        rows.extend(v_rows)
        total += v_total

    if kind in ("all", ISSUE_KIND_SCRAPE_FAILURE):
        f_rows, f_total = _get_scrape_failures_page(
            session,
            state=state,
            shop_id=shop_id,
            issue_type=issue_type,
            run_id=run_id,
            q=q,
            severity=severity,
            order=order,
            page=helper_page,
            per_page=helper_per_page,
        )
        rows.extend(f_rows)
        total += f_total

    if kind == "all":
        rows.sort(
            key=lambda r: r["added_at"] or datetime.min.replace(tzinfo=UTC),
            reverse=(order != "asc"),
        )
        start = (page - 1) * per_page
        rows = rows[start : start + per_page]

    return rows, total


def _get_validation_issues_page(
    session: Session,
    *,
    state: str | None,
    shop_id: int | None,
    issue_type: str,
    run_id: int | None,
    q: str,
    severity: str,
    url_type: str,
    book_type: str,
    order: str,
    page: int,
    per_page: int,
) -> tuple[list[dict[str, Any]], int]:
    query = (
        session.query(ValidationIssue, ScrapeRun, ShopBook, DiscoveredUrl, Shop)
        .join(ScrapeRun, ValidationIssue.last_seen_run_id == ScrapeRun.id)
        .outerjoin(ShopBook, ValidationIssue.shop_book_id == ShopBook.id)
        .outerjoin(
            DiscoveredUrl,
            (DiscoveredUrl.url == ValidationIssue.url)
            & (DiscoveredUrl.shop_id == ScrapeRun.shop_id),
        )
        .outerjoin(Shop, Shop.id == ScrapeRun.shop_id)
    )

    if state in {"new", "acknowledged", "snoozed", "resolved"}:
        query = query.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        # Legacy alias: treat as 'new'
        query = query.filter(ValidationIssue.lifecycle_state == "new")
    # empty string or None = no filter

    if shop_id is not None:
        query = query.filter(ScrapeRun.shop_id == shop_id)
    if issue_type:
        query = query.filter(ValidationIssue.issue == issue_type)
    if severity in ("critical", "warning"):
        severity_types = [k for k, v in ISSUE_SEVERITY.items() if v == severity]
        query = query.filter(ValidationIssue.issue.in_(severity_types))
    if run_id is not None:
        query = query.filter(ValidationIssue.last_seen_run_id == run_id)
    if url_type:
        query = query.filter(DiscoveredUrl.url_type == url_type)
    if book_type:
        query = query.filter(ShopBook.type == book_type)
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
    for issue, run, shop_book, disc_url, shop in rows:
        result.append(
            {
                "id": issue.id,
                "kind": ISSUE_KIND_VALIDATION,
                "url": issue.url,
                "field": issue.field,
                "issue": issue.issue,
                "raw_value": issue.raw_value,
                "error_reason": None,
                "http_status": None,
                # backwards-compat alias for frontend code not yet updated
                "scrape_run_id": issue.last_seen_run_id,
                "last_seen_run_id": issue.last_seen_run_id,
                "first_seen_run_id": issue.first_seen_run_id,
                "run_count": issue.run_count,
                "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None,
                "snoozed_until": issue.snoozed_until.isoformat() if issue.snoozed_until else None,
                "shop_book_id": issue.shop_book_id,
                "shop_book_title": shop_book.title if shop_book else None,
                "shop_id": run.shop_id,
                "shop_name": shop.name if shop else None,
                "url_type": disc_url.url_type if disc_url else None,
                "book_type": shop_book.type if shop_book else None,
                "lifecycle_state": issue.lifecycle_state,
                "added_at": run.started_at,
                "severity": ISSUE_SEVERITY.get(issue.issue, "warning"),
            }
        )
    return result, total


def _get_scrape_failures_page(
    session: Session,
    *,
    state: str | None,
    shop_id: int | None,
    issue_type: str,
    run_id: int | None,
    q: str,
    severity: str,
    order: str,
    page: int,
    per_page: int,
) -> tuple[list[dict[str, Any]], int]:
    """Inbox slice over `scrape_failures`. Mirrors the validation helper's
    filter contract: `state` maps to lifecycle_state; `severity` filters
    via the range/prefix logic in `severity_for_failure`."""
    from sqlalchemy import and_, or_

    query = (
        session.query(ScrapeFailure, ShopBook, Shop)
        .outerjoin(
            ShopBook,
            and_(
                ShopBook.shop_id == ScrapeFailure.shop_id,
                ShopBook.url == ScrapeFailure.url,
            ),
        )
        .outerjoin(Shop, Shop.id == ScrapeFailure.shop_id)
    )

    if state in {"new", "acknowledged", "snoozed", "resolved"}:
        query = query.filter(ScrapeFailure.lifecycle_state == state)
    elif state == "open":
        query = query.filter(ScrapeFailure.lifecycle_state != "acknowledged")

    if shop_id is not None:
        query = query.filter(ScrapeFailure.shop_id == shop_id)
    if run_id is not None:
        query = query.filter(ScrapeFailure.run_id == run_id)
    if issue_type:
        # `issue_type` doubles as the error_reason filter for this source.
        query = query.filter(ScrapeFailure.error_reason == issue_type)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                ScrapeFailure.url.ilike(pattern),
                ShopBook.title.ilike(pattern),
            )
        )
    if severity in ("critical", "warning"):
        # Mirror severity_for_failure() in SQL via CASE: http_status range
        # wins, else error_reason prefix lookup, else default warning.
        crit_prefixes = [
            k for k, v in SCRAPE_FAILURE_SEVERITY.items() if v == "critical"
        ]
        warn_prefixes = [
            k for k, v in SCRAPE_FAILURE_SEVERITY.items() if v == "warning"
        ]
        # error_reason prefix matched via LIKE 'prefix%'
        crit_pred = or_(
            *[ScrapeFailure.error_reason.like(f"{p}%") for p in crit_prefixes]
        )
        warn_pred = or_(
            and_(
                ScrapeFailure.http_status.isnot(None),
                ScrapeFailure.http_status >= 400,
                ScrapeFailure.http_status < 600,
            ),
            *[ScrapeFailure.error_reason.like(f"{p}%") for p in warn_prefixes],
        )
        if severity == "critical":
            # critical = matches a critical prefix AND not an http range
            query = query.filter(
                and_(
                    crit_pred,
                    or_(
                        ScrapeFailure.http_status.is_(None),
                        ScrapeFailure.http_status < 400,
                        ScrapeFailure.http_status >= 600,
                    ),
                )
            )
        else:  # warning
            query = query.filter(warn_pred)

    total = query.count()

    if order == "asc":
        query = query.order_by(ScrapeFailure.occurred_at.asc(), ScrapeFailure.id.asc())
    else:
        query = query.order_by(
            ScrapeFailure.occurred_at.desc(), ScrapeFailure.id.desc()
        )

    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    result: list[dict[str, Any]] = []
    for failure, shop_book, shop in rows:
        result.append(
            {
                "id": failure.id,
                "kind": ISSUE_KIND_SCRAPE_FAILURE,
                "url": failure.url,
                "field": "response",
                "issue": failure.error_reason or "unknown",
                "raw_value": str(failure.http_status)
                if failure.http_status is not None
                else None,
                "error_reason": failure.error_reason,
                "http_status": failure.http_status,
                "scrape_run_id": failure.run_id,
                "shop_book_id": shop_book.id if shop_book else None,
                "shop_book_title": shop_book.title if shop_book else None,
                "shop_id": failure.shop_id,
                "shop_name": shop.name if shop else None,
                "lifecycle_state": failure.lifecycle_state,
                "added_at": failure.occurred_at,
                "severity": severity_for_failure(
                    failure.error_reason, failure.http_status
                ),
            }
        )
    return result, total


def get_validation_by_type(
    session: Session,
    issue_type: str,
    limit: int = 100,
    state: str | None = None,
    run_id: int | None = None,
) -> list[dict[str, Any]]:
    """Get validation issues with shop_book IDs resolved from URL."""
    q = session.query(ValidationIssue).filter(ValidationIssue.issue == issue_type)
    if state in {"new", "acknowledged", "snoozed", "resolved"}:
        q = q.filter(ValidationIssue.lifecycle_state == state)
    elif state == "open":
        q = q.filter(ValidationIssue.lifecycle_state == "new")
    if run_id is not None:
        q = q.filter(ValidationIssue.last_seen_run_id == run_id)
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
                "scrape_run_id": issue.last_seen_run_id,
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


def get_book_price_history(
    session: Session, book_id: int, days: int = 30
) -> list[dict[str, Any]]:
    """Return 30-day daily price series for every shop linked to book_id.

    Returns [{"shop": str, "series": [{"date": "YYYY-MM-DD", "price": float}]}].
    Series sorted ascending by date. Days with no scrape are omitted (sparse is fine).
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from book_scraper.db.models import Price, Shop, ShopBook

    cutoff = datetime.now(UTC) - timedelta(days=days)

    rows = session.execute(
        select(
            Shop.name.label("shop"),
            func.date_trunc("day", Price.scraped_at).label("day"),
            func.max(Price.price).label("price"),
        )
        .join(ShopBook, Price.shop_book_id == ShopBook.id)
        .join(Shop, ShopBook.shop_id == Shop.id)
        .where(ShopBook.book_id == book_id)
        .where(Price.scraped_at >= cutoff)
        .group_by(Shop.name, func.date_trunc("day", Price.scraped_at))
        .order_by(Shop.name, func.date_trunc("day", Price.scraped_at))
    ).all()

    series: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        shop = row.shop
        if shop not in series:
            series[shop] = []
        series[shop].append({
            "date": row.day.strftime("%Y-%m-%d"),
            "price": float(row.price),
        })

    return [{"shop": shop, "series": pts} for shop, pts in series.items()]


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
        session.execute(data_sql, {**params, "offset": offset, "limit": per_page})
        .mappings()
        .all()
    )
    return [dict(r) for r in rows], int(total)


def get_inventory_stats(session: Session) -> dict[str, Any]:
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
    url_unreachable: bool = False,
    linked_filter: str = "",
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
        from sqlalchemy import or_ as _or

        query = query.filter(
            _or(
                ShopBook.title.ilike(f"%{search}%"),
                ShopBook.author.ilike(f"%{search}%"),
                ShopBook.isbn.ilike(f"%{search}%"),
            )
        )
    if author:
        query = query.filter(ShopBook.author.ilike(f"%{author}%"))
    if publisher:
        query = query.filter(ShopBook.publisher.ilike(f"%{publisher}%"))
    if category:
        # SQLAlchemy stubs don't model PG ARRAY.any(value) — accepts a
        # scalar at runtime (Postgres ANY() match) but the stub demands
        # a ColumnElement[bool].
        query = query.filter(ShopBook.categories.any(category))  # type: ignore[arg-type]
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
    if linked_filter == "linked":
        query = query.filter(ShopBook.book_id.isnot(None))
    elif linked_filter == "not_linked":
        query = query.filter(ShopBook.book_id.is_(None))
    if url_unreachable:
        query = query.join(
            DiscoveredUrl,
            (DiscoveredUrl.shop_book_id == ShopBook.id)
            & (DiscoveredUrl.url_type == "unreachable"),
        )
    if attr_key:
        from sqlalchemy import exists

        from book_scraper.db.models import ShopBookAttribute

        attr_subq = session.query(ShopBookAttribute).filter(
            ShopBookAttribute.shop_book_id == ShopBook.id,
            ShopBookAttribute.key == attr_key,
        )
        if attr_value:
            attr_subq = attr_subq.filter(ShopBookAttribute.value == attr_value)
        # SQLAlchemy 2.0 stubs prefer exists(select()) over the legacy
        # exists(query) form; runtime is fine with a Query.
        query = query.filter(exists(attr_subq))  # type: ignore[arg-type]
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


def get_shop_stats(session: Session, shop_id: int) -> dict[str, Any]:
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


def get_shop_field_stats(session: Session, shop_id: int) -> dict[str, Any]:
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
            "scrape_run_id": issue.last_seen_run_id,
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


def get_data_completeness(session: Session) -> list[dict[str, Any]]:
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


def get_issues_groups(
    session: Session,
    group_by: str = "type",
    state: str | None = None,
    shop_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return grouped issue counts for the grouped-view toggle.

    group_by='type'      -> one row per issue_type across all shops.
    group_by='type_shop' -> one row per (issue_type, shop).
    state                -> optional filter: 'new'|'acknowledged'|'snoozed'|'resolved'.
    shop_id              -> optional shop scope.
    """
    count_cols = [
        func.count().label("total"),
        func.count()
        .filter(ValidationIssue.lifecycle_state == "new")
        .label("cnt_new"),
        func.count()
        .filter(ValidationIssue.lifecycle_state == "acknowledged")
        .label("cnt_acknowledged"),
        func.count()
        .filter(ValidationIssue.lifecycle_state == "snoozed")
        .label("cnt_snoozed"),
        func.count()
        .filter(ValidationIssue.lifecycle_state == "resolved")
        .label("cnt_resolved"),
    ]

    if group_by == "type_shop":
        q = (
            select(
                ValidationIssue.issue.label("issue_type"),
                Shop.name.label("shop_name"),
                Shop.id.label("shop_id_val"),
                *count_cols,
            )
            .outerjoin(Shop, Shop.id == ValidationIssue.shop_id)
        )
    else:
        q = select(
            ValidationIssue.issue.label("issue_type"),
            *count_cols,
        )

    if shop_id is not None:
        q = q.where(ValidationIssue.shop_id == shop_id)
    if state:
        q = q.where(ValidationIssue.lifecycle_state == state)

    if group_by == "type_shop":
        q = q.group_by(ValidationIssue.issue, Shop.name, Shop.id).order_by(
            func.count().desc(), ValidationIssue.issue
        )
    else:
        q = q.group_by(ValidationIssue.issue).order_by(func.count().desc())

    rows = session.execute(q).all()

    is_type_shop = group_by == "type_shop"
    return [
        {
            "issue_type": r.issue_type,
            "shop_name": r.shop_name if is_type_shop else None,
            "shop_id": r.shop_id_val if is_type_shop else None,
            "severity": ISSUE_SEVERITY.get(r.issue_type, "warning"),
            "total": r.total,
            "by_state": {
                "new": r.cnt_new,
                "acknowledged": r.cnt_acknowledged,
                "snoozed": r.cnt_snoozed,
                "resolved": r.cnt_resolved,
            },
        }
        for r in rows
    ]


def get_issues_trend(
    session: Session, days: int = 14, state: str | None = "new"
) -> dict[str, list[int]]:
    """Return per-day issue counts for each issue type over the last N days.

    Returns {issue_type: [count_day_-N, ..., count_day_0]} suitable for sparklines.
    Counts ValidationIssue rows by day, using the last_seen_run's started_at
    as the timestamp (ValidationIssue itself has no created_at column).
    """
    end = datetime.now(UTC).date()
    start = end - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=UTC)

    q = (
        select(
            ValidationIssue.issue.label("issue_type"),
            cast(ScrapeRun.started_at, Date).label("day"),
            func.count().label("cnt"),
        )
        .join(ScrapeRun, ScrapeRun.id == ValidationIssue.last_seen_run_id)
        .where(ScrapeRun.started_at >= start_dt)
    )
    if state:
        q = q.where(ValidationIssue.lifecycle_state == state)
    q = q.group_by(ValidationIssue.issue, cast(ScrapeRun.started_at, Date))

    rows = session.execute(q).all()

    by_key = {(r.issue_type, r.day): r.cnt for r in rows}
    types = {r.issue_type for r in rows}

    result: dict[str, list[int]] = {}
    for t in types:
        series = []
        for i in range(days):
            d = start + timedelta(days=i)
            series.append(by_key.get((t, d), 0))
        result[t] = series
    return result


DISCOVERED_URL_SORT_COLUMNS = {
    "url": DiscoveredUrl.url,
    "fails": DiscoveredUrl.fail_count,
    "discovered": DiscoveredUrl.first_seen_at,
    "score": UrlClassification.book_score,
    "book": ShopBook.title,
}


def get_discovered_urls_stats(
    session: Session, shop_id: int | None = None
) -> dict[str, Any]:
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
    has_book: bool = False,
    sort_by: str = "discovered",
    sort_order: str = "desc",
    failing: bool = False,
) -> tuple[list[Any], int]:
    """Return paginated discovered URLs with filters."""
    needs_book_join = sort_by == "book" or has_book
    query = (
        session.query(DiscoveredUrl)
        .options(joinedload(DiscoveredUrl.shop), joinedload(DiscoveredUrl.shop_book))
        .outerjoin(
            UrlClassification, UrlClassification.discovered_url_id == DiscoveredUrl.id
        )
    )
    if needs_book_join:
        query = query.outerjoin(ShopBook, ShopBook.id == DiscoveredUrl.shop_book_id)
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
        # URLs either classified as books OR linked to a shop_book via FK
        from sqlalchemy import or_ as _or

        query = query.filter(
            _or(
                UrlClassification.is_book_product.is_(True),
                DiscoveredUrl.shop_book_id.isnot(None),
            )
        )
    elif is_book == "not_book":
        query = query.filter(UrlClassification.is_book_product.is_(False))
    if failing:
        query = query.filter(DiscoveredUrl.fail_count >= 3)
    if has_book:
        query = query.filter(DiscoveredUrl.shop_book_id.isnot(None))
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


def list_books(
    session: Session,
    *,
    data_source: str | None = None,
    has_isbn: bool | None = None,
    has_shops: bool | None = None,
    has_conflicts: bool | None = None,
    shop_count_min: int | None = None,
    shop_count_max: int | None = None,
    year: int | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    from sqlalchemy import func, select

    from book_scraper.db.models import (
        Author,
        Book,
        BookAuthor,
        BookIsbn,
        Publisher,
        ShopBook,
    )

    base = select(Book)
    if data_source:
        base = base.where(Book.data_source == data_source)
    if year is not None:
        base = base.where(Book.year == year)
    if has_isbn is True:
        base = base.where(Book.id.in_(select(BookIsbn.book_id).distinct()))
    elif has_isbn is False:
        base = base.where(~Book.id.in_(select(BookIsbn.book_id).distinct()))
    if has_shops is True:
        base = base.where(
            Book.id.in_(
                select(ShopBook.book_id).where(ShopBook.book_id.is_not(None)).distinct()
            )
        )
    elif has_shops is False:
        base = base.where(
            ~Book.id.in_(
                select(ShopBook.book_id).where(ShopBook.book_id.is_not(None)).distinct()
            )
        )

    # has_conflicts filter — books where shop_books disagree on metadata fields
    if has_conflicts is True or has_conflicts is False:
        conflict_ids = (
            select(ShopBook.book_id)
            .where(ShopBook.book_id.isnot(None))
            .group_by(ShopBook.book_id)
            .having(
                or_(
                    func.count(func.distinct(func.lower(ShopBook.title))) > 1,
                    func.count(func.distinct(func.lower(ShopBook.author))) > 1,
                    func.count(func.distinct(ShopBook.year)) > 1,
                    func.count(func.distinct(func.lower(ShopBook.publisher))) > 1,
                )
            )
        )
        if has_conflicts is True:
            base = base.where(Book.id.in_(conflict_ids))
        else:
            base = base.where(~Book.id.in_(conflict_ids))

    # shop_count range filter: subquery that groups shop_books by book_id
    if shop_count_min is not None or shop_count_max is not None:
        sc = (
            select(
                ShopBook.book_id.label("bid"),
                func.count(ShopBook.id).label("n"),
            )
            .where(ShopBook.book_id.isnot(None))
            .group_by(ShopBook.book_id)
        )
        if shop_count_min is not None:
            sc = sc.having(func.count(ShopBook.id) >= shop_count_min)
        if shop_count_max is not None:
            sc = sc.having(func.count(ShopBook.id) <= shop_count_max)
        sc_sub = sc.subquery()
        base = base.where(Book.id.in_(select(sc_sub.c.bid)))

    if search and search.strip():
        as_isbn = _looks_like_isbn(search)
        if as_isbn:
            base = base.where(
                Book.id.in_(
                    select(BookIsbn.book_id).where(BookIsbn.isbn == as_isbn)
                )
            )
        else:
            like = f"%{search.strip()}%"
            base = base.where(
                or_(
                    Book.title.ilike(like),
                    Book.id.in_(
                        select(BookAuthor.book_id)
                        .join(Author, Author.id == BookAuthor.author_id)
                        .where(Author.name.ilike(like))
                    ),
                )
            )

    total = session.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()

    rows = (
        session.execute(
            base.order_by(Book.created_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        .scalars()
        .all()
    )

    book_ids = [b.id for b in rows]

    # Batch: price min/max + shop_count per book
    price_rows = (
        session.execute(
            select(
                ShopBook.book_id,
                func.min(ShopBook.price).label("price_min"),
                func.max(ShopBook.price).label("price_max"),
                func.count(ShopBook.id).label("shop_count"),
            )
            .where(ShopBook.book_id.in_(book_ids))
            .group_by(ShopBook.book_id)
        ).all()
        if book_ids
        else []
    )
    price_by_book = {
        r.book_id: (r.price_min, r.price_max, r.shop_count) for r in price_rows
    }

    # Batch: which of the book_ids on this page have metadata conflicts
    conflict_set: set[int] = set()
    if book_ids:
        conflict_rows = session.execute(
            select(ShopBook.book_id)
            .where(ShopBook.book_id.in_(book_ids))
            .group_by(ShopBook.book_id)
            .having(
                or_(
                    func.count(func.distinct(func.lower(ShopBook.title))) > 1,
                    func.count(func.distinct(func.lower(ShopBook.author))) > 1,
                    func.count(func.distinct(ShopBook.year)) > 1,
                    func.count(func.distinct(func.lower(ShopBook.publisher))) > 1,
                )
            )
        ).scalars().all()
        conflict_set = set(conflict_rows)

    out = []
    for b in rows:
        pub_name = None
        if b.publisher_id:
            pub_name = session.execute(
                select(Publisher.name).where(Publisher.id == b.publisher_id)
            ).scalar_one_or_none()
        authors = (
            session.execute(
                select(Author.name)
                .join(BookAuthor)
                .where(BookAuthor.book_id == b.id, BookAuthor.role == "author")
                .order_by(BookAuthor.position)
            )
            .scalars()
            .all()
        )
        primary_isbn = session.execute(
            select(BookIsbn.isbn).where(BookIsbn.book_id == b.id).limit(1)
        ).scalar_one_or_none()
        price_min, price_max, shop_count = price_by_book.get(b.id, (None, None, 0))
        out.append(
            {
                "id": b.id,
                "title": b.title,
                "year": b.year,
                "data_source": b.data_source,
                "libis_code": b.libis_code,
                "publisher": pub_name,
                "primary_isbn": primary_isbn,
                "authors": list(authors),
                "shop_count": shop_count,
                "price_min": float(price_min) if price_min is not None else None,
                "price_max": float(price_max) if price_max is not None else None,
                "has_conflicts": b.id in conflict_set,
            }
        )

    return {
        "books": out,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 1,
    }


def get_book_stats(session: Session) -> dict[str, Any]:
    """Aggregate stats for the books KPI strip."""
    from book_scraper.db.models import Book, ShopBook

    total = session.execute(select(func.count(Book.id))).scalar_one()
    enriched = session.execute(
        select(func.count(Book.id)).where(Book.data_source != "shop_inferred")
    ).scalar_one()

    # Shop counts per book (only books that have shop_books)
    book_shop_counts = session.execute(
        select(
            ShopBook.book_id,
            func.count(ShopBook.id).label("n"),
        )
        .where(ShopBook.book_id.isnot(None))
        .group_by(ShopBook.book_id)
    ).all()

    multi_shop = sum(1 for _, n in book_shop_counts if n >= 2)
    single_shop = sum(1 for _, n in book_shop_counts if n == 1)
    total_listings = sum(n for _, n in book_shop_counts)
    avg_shops = total_listings / len(book_shop_counts) if book_shop_counts else 0

    # Conflict detection: books where shops disagree on metadata.
    # A book is in conflict if its linked shop_books have >1 distinct non-null
    # value for any of: title, author, year, publisher (case-insensitive strings).
    conflicts_query = (
        select(ShopBook.book_id)
        .where(ShopBook.book_id.isnot(None))
        .group_by(ShopBook.book_id)
        .having(
            or_(
                func.count(func.distinct(func.lower(ShopBook.title))) > 1,
                func.count(func.distinct(func.lower(ShopBook.author))) > 1,
                func.count(func.distinct(ShopBook.year)) > 1,
                func.count(func.distinct(func.lower(ShopBook.publisher))) > 1,
            )
        )
    )
    conflicts = session.execute(
        select(func.count()).select_from(conflicts_query.subquery())
    ).scalar_one()

    return {
        "total": total,
        "enriched": enriched,
        "enriched_pct": round(enriched / total * 100, 1) if total else 0,
        "multi_shop": multi_shop,
        "single_shop": single_shop,
        "avg_shops": round(avg_shops, 1),
        "conflicts": conflicts,
    }


def book_detail(session: Session, book_id: int) -> dict[str, Any] | None:
    from sqlalchemy import select

    from book_scraper.db.models import (
        Author,
        Book,
        BookAuthor,
        BookIsbn,
        Publisher,
        Series,
        Shop,
        ShopBook,
    )

    book = session.execute(select(Book).where(Book.id == book_id)).scalar_one_or_none()
    if book is None:
        return None

    pub_name = None
    if book.publisher_id:
        pub_name = session.execute(
            select(Publisher.name).where(Publisher.id == book.publisher_id)
        ).scalar_one_or_none()
    series_title = None
    if book.series_id:
        series_title = session.execute(
            select(Series.title).where(Series.id == book.series_id)
        ).scalar_one_or_none()

    isbns = session.execute(
        select(BookIsbn.isbn, BookIsbn.isbn_type).where(BookIsbn.book_id == book_id)
    ).all()
    authors = session.execute(
        select(Author.name, BookAuthor.role)
        .join(BookAuthor, BookAuthor.author_id == Author.id)
        .where(BookAuthor.book_id == book_id)
        .order_by(BookAuthor.role, BookAuthor.position)
    ).all()
    shops = session.execute(
        select(
            Shop.name,
            ShopBook.id.label("shop_book_id"),
            ShopBook.url,
            ShopBook.price,
            ShopBook.in_stock,
            ShopBook.last_seen_at,
            ShopBook.first_seen_at,
            ShopBook.is_active,
            ShopBook.match_status,
            ShopBook.title.label("shop_title"),
            ShopBook.author.label("shop_author"),
            ShopBook.year.label("shop_year"),
            ShopBook.isbn.label("shop_isbn"),
            ShopBook.publisher.label("shop_publisher"),
            ShopBook.format.label("shop_format"),
            ShopBook.match_method,
        )
        .join(ShopBook, ShopBook.shop_id == Shop.id)
        .where(ShopBook.book_id == book_id)
        .order_by(Shop.name)
    ).all()

    # Earliest first_seen_at across all shops linked to this book.
    first_matched = None
    if shops:
        timestamps = [s.first_seen_at for s in shops if s.first_seen_at]
        if timestamps:
            first_matched = min(timestamps).isoformat()

    # Build ibiblioteka URLs when this is an ibiblioteka-sourced book.
    # scraped_url  — the JSON API endpoint stored on books.source_url (set by
    #   the scan pipeline since the ibiblioteka spider emits BookItem, not
    #   ShopBookItem, so there are no shop_books rows for this shop).
    # ibiblioteka_page_url — the human-readable SPA page on ibiblioteka.lt,
    #   constructed from the numeric API id embedded in scraped_url.
    scraped_url: str | None = book.source_url
    ibiblioteka_page_url: str | None = None
    if scraped_url:
        numeric_id = scraped_url.rstrip("/").split("/")[-1]
        if numeric_id.isdigit():
            ibiblioteka_page_url = (
                f"https://ibiblioteka.lt/metis/publication/{numeric_id}"
            )

    return {
        "id": book.id,
        "title": book.title,
        "title_full": book.title_full,
        "data_source": book.data_source,
        "libis_code": book.libis_code,
        "year": book.year,
        "publisher": pub_name,
        "series": series_title,
        "release_place": book.release_place,
        "type": book.type,
        "format": book.format,
        "pages": book.pages,
        "duration": book.duration,
        "dimensions": book.dimensions,
        "language": book.language,
        "translated_from": book.translated_from,
        "description": book.description,
        "cover_url": book.cover_url,
        "udc_codes": book.udc_codes,
        "subjects": book.subjects,
        "audience": book.audience,
        "isbns": [{"isbn": isbn, "type": typ} for isbn, typ in isbns],
        "authors": [{"name": n, "role": r} for n, r in authors],
        "first_matched_at": first_matched,
        "scraped_url": scraped_url,
        "ibiblioteka_page_url": ibiblioteka_page_url,
        "shops": [
            {
                "shop":           row.name,
                "shop_book_id":   row.shop_book_id,
                "url":            row.url,
                "price":          str(row.price) if row.price is not None else None,
                "in_stock":       row.in_stock,
                "last_seen_at":   row.last_seen_at.isoformat() if row.last_seen_at else None,
                "first_seen_at":  row.first_seen_at.isoformat() if row.first_seen_at else None,
                "is_active":      row.is_active,
                "match_status":   row.match_status,
                "title":          row.shop_title,
                "author":         row.shop_author,
                "year":           row.shop_year,
                "isbn":           row.shop_isbn,
                "publisher":      row.shop_publisher,
                "format":         row.shop_format,
                "match_method":   row.match_method,
            }
            for row in shops
        ],
    }
