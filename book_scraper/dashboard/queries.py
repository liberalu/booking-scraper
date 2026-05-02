import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select, text
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

logger = logging.getLogger(__name__)

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


# Severity for scrape_failures (PR 2 of the migration). Driven by
# `error_reason` prefix when present; falls back to http_status range.
# Per-status reasons (`http_404`, `http_503`, ...) classify via the
# range, so we don't need to enumerate every status code.
SCRAPE_FAILURE_SEVERITY: dict[str, str] = {
    "request_error":     "critical",
    "anti_bot_detected": "critical",
    "schema_drift":      "critical",
    "rate_limited":      "warning",
    "robots_disallowed": "warning",
    "soft_404":          "warning",
}


def severity_for_failure(
    error_reason: str | None, http_status: int | None
) -> str:
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


def mark_stale_runs(session: Session) -> int:
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
    marked = 0
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
            marked += 1
    cleaned = sweep_orphaned_processing_items(session)
    if marked or cleaned:
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
        try:
            cron = croniter(job.cron_expression, now)
            next_dt: datetime = cron.get_next(datetime).replace(tzinfo=UTC)
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
            session.query(ValidationIssue.scrape_run_id, ValidationIssue.raw_value)
            .filter(
                ValidationIssue.scrape_run_id.in_(ids),
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


def get_scrape_run_events(session: Session, run_id: int) -> list[dict]:
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
                ValidationIssue.scrape_run_id == run.id,
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
            func.string_agg(
                func.distinct(ShopBookChange.field), ", "
            ).label("changed_fields"),
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
            (latest.c.scrape_url_item_id == ScrapeUrlItem.id)
            & (latest.c.rn == 1),
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
        case((latest.c.lifecycle_state != "already_seen", 1), else_=0)
    ).label("unacked_count")
    acked_expr = func.sum(
        case((latest.c.lifecycle_state == "already_seen", 1), else_=0)
    ).label("acked_count")

    base = (
        session.query(
            latest.c.error_reason,
            latest.c.http_status,
            unacked_expr,
            acked_expr,
        )
        .join(ScrapeUrlItem, ScrapeUrlItem.id == latest.c.scrape_url_item_id)
        .filter(latest.c.rn == 1, ScrapeUrlItem.status == "failed")
        .group_by(latest.c.error_reason, latest.c.http_status)
    )
    if not include_acked:
        # Hide buckets where every latest event is already_seen.
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
    for reason, http, unacked_count, acked_count in rows:
        unacked_count = int(unacked_count or 0)
        acked_count = int(acked_count or 0)
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
            examples_q = examples_q.filter(
                latest.c.lifecycle_state != "already_seen"
            )
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
            (latest.c.scrape_url_item_id == ScrapeUrlItem.id)
            & (latest.c.rn == 1),
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
) -> tuple[
    list[tuple[ScrapeUrlItem, str | None, int | None, str | None]], int
]:
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
            query = query.filter(
                latest_failure.c.error_reason == error_reason
            )
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
        (it, title, sb_id, latest_reason)
        for it, title, sb_id, latest_reason in rows
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
            key=lambda r: (
                r["added_at"] or datetime.min.replace(tzinfo=UTC)
            ),
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
    order: str,
    page: int,
    per_page: int,
) -> tuple[list[dict[str, Any]], int]:
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
                "kind": ISSUE_KIND_VALIDATION,
                "url": issue.url,
                "field": issue.field,
                "issue": issue.issue,
                "raw_value": issue.raw_value,
                "error_reason": None,
                "http_status": None,
                "scrape_run_id": issue.scrape_run_id,
                "shop_book_id": issue.shop_book_id,
                "shop_book_title": shop_book.title if shop_book else None,
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
        session.query(ScrapeFailure, ShopBook)
        .outerjoin(
            ShopBook,
            and_(
                ShopBook.shop_id == ScrapeFailure.shop_id,
                ShopBook.url == ScrapeFailure.url,
            ),
        )
    )

    if state in {"new", "recurring", "already_seen"}:
        query = query.filter(ScrapeFailure.lifecycle_state == state)
    elif state == "open":
        query = query.filter(ScrapeFailure.lifecycle_state != "already_seen")

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
            *[
                ScrapeFailure.error_reason.like(f"{p}%")
                for p in crit_prefixes
            ]
        )
        warn_pred = or_(
            and_(
                ScrapeFailure.http_status.isnot(None),
                ScrapeFailure.http_status >= 400,
                ScrapeFailure.http_status < 600,
            ),
            *[
                ScrapeFailure.error_reason.like(f"{p}%")
                for p in warn_prefixes
            ],
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
        query = query.order_by(
            ScrapeFailure.occurred_at.asc(), ScrapeFailure.id.asc()
        )
    else:
        query = query.order_by(
            ScrapeFailure.occurred_at.desc(), ScrapeFailure.id.desc()
        )

    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    result: list[dict[str, Any]] = []
    for failure, shop_book in rows:
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
        session.execute(data_sql, {**params, "offset": offset, "limit": per_page})
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
    url_unreachable: bool = False,
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
    "book": ShopBook.title,
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
    has_book: bool = False,
    sort_by: str = "discovered",
    sort_order: str = "desc",
    failing: bool = False,
) -> tuple[list, int]:
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
