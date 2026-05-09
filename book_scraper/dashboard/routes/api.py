# book_scraper/dashboard/routes/api.py
from __future__ import annotations

import math
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from book_scraper.dashboard.deps import get_db, get_docker_client
from book_scraper.dashboard.queries import (
    ISSUE_DESCRIPTIONS,
    RUN_URL_STATUSES,
    get_all_shops,
    get_data_completeness,
    get_discovered_urls_page,
    get_discovered_urls_stats,
    get_issues_page,
    get_overview_stats,
    get_price_changes,
    get_price_history,
    get_recent_runs,
    get_repeated_failures,
    get_run_books_added,
    get_run_books_updated,
    get_run_close_reason,
    get_run_discovered_urls,
    get_run_eta,
    get_run_failure_groups,
    get_run_in_flight,
    get_run_issue_summary,
    get_run_item_counts,
    get_run_live_health,
    get_run_rate_window,
    get_run_recent_activity,
    get_run_url_breakdown,
    get_run_url_items,
    get_schedule_info,
    get_scrape_activity_by_day,
    get_scrape_run_events,
    get_shop_book_changes,
    get_shop_book_issues,
    get_shop_books_page,
    get_shop_by_name,
    get_shop_field_stats,
    get_shop_runs,
    get_shop_stats,
    get_url_detail,
    get_validation_lifecycle_counts,
    get_validation_summary,
)
from book_scraper.db import scrape_run_events as run_event_types
from book_scraper.db.models import (
    CronJob,
    DiscoveredUrl,
    ScrapeFailure,
    ScrapeRun,
    ScrapeUrlItem,
    Shop,
    ShopBook,
    ShopBookAttribute,
    ShopBookChange,
    ValidationIssue,
)
from book_scraper.db.repo import (
    create_cron_job,
    delete_cron_job,
    emit_scrape_run_event,
    get_cron_job,
    list_cron_jobs,
    toggle_cron_job,
    update_cron_job,
)

router = APIRouter()


# ─── Helpers ────────────────────────────────────────────────────────────────


def _rel(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - dt
    s = max(0, int(delta.total_seconds()))
    if s < 60:
        return "just now"
    m = s // 60
    if m < 60:
        return f"{m}m ago"
    h = m // 60
    if h < 24:
        return f"{h}h ago"
    d = h // 24
    if d < 7:
        return f"{d}d ago"
    w = d // 7
    if w < 5:
        return f"{w}w ago"
    mo = d // 30
    if mo < 12:
        return f"{mo}mo ago"
    return f"{d // 365}y ago"


def _elapsed(run: ScrapeRun) -> str:
    start = run.started_at
    end = run.finished_at or datetime.now(UTC)
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if not start:
        return "—"
    secs = max(0, int((end - start).total_seconds()))
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m" if m else f"{h}h"
    if m:
        return f"{m}m {s}s" if s else f"{m}m"
    return f"{s}s"


def _progress(run: ScrapeRun, terminal_count: int | None = None) -> int:
    """Return progress as a percentage (0–100).

    `terminal_count` is the number of `scrape_url_items` rows in
    terminal state (done | failed) for this run. When provided, progress
    is `terminal / urls_total` — counts non-product fetches and 4xx/5xx
    as progress, since the work for that URL is finished. Falls back to
    `urls_processed / urls_total` when caller didn't fetch the
    breakdown (cheaper for list endpoints that don't need the
    finer-grained number).
    """
    if run.status == "completed":
        return 100
    if not (run.urls_total and run.urls_total > 0):
        return 0
    processed = terminal_count if terminal_count is not None else run.urls_processed
    return min(99, int(processed / run.urls_total * 100))


def _run_terminal_counts(session: Session, run_ids: list[int]) -> dict[int, int]:
    """Bulk-fetch `done + failed` counts for a batch of runs."""
    if not run_ids:
        return {}
    from book_scraper.db.models import ScrapeUrlItem

    rows = (
        session.query(
            ScrapeUrlItem.run_id,
            func.count(ScrapeUrlItem.id),
        )
        .filter(
            ScrapeUrlItem.run_id.in_(run_ids),
            ScrapeUrlItem.status.in_(("done", "failed")),
        )
        .group_by(ScrapeUrlItem.run_id)
        .all()
    )
    return {run_id: count for run_id, count in rows}


def _run_vi_counts(session: Session, run_ids: list[int]) -> dict[int, int]:
    """Bulk-fetch validation issue counts for a batch of run IDs."""
    if not run_ids:
        return {}
    rows = (
        session.query(
            ValidationIssue.scrape_run_id,
            func.count(ValidationIssue.id),
        )
        .filter(ValidationIssue.scrape_run_id.in_(run_ids))
        .group_by(ValidationIssue.scrape_run_id)
        .all()
    )
    return {run_id: count for run_id, count in rows}


def _run_real_item_counts(
    session: Session, run_ids: list[int]
) -> dict[int, dict[str, int]]:
    """Bulk-fetch accurate added/updated counts from DB records.

    Mirrors get_run_item_counts() but for a batch of run IDs.
    - added:   shop_books whose created_run_id is in the batch
    - updated: distinct shop_book_id in shop_book_changes per run
    """
    if not run_ids:
        return {}
    added_rows = (
        session.query(ShopBook.created_run_id, func.count(ShopBook.id))
        .filter(ShopBook.created_run_id.in_(run_ids))
        .group_by(ShopBook.created_run_id)
        .all()
    )
    updated_rows = (
        session.query(
            ShopBookChange.scrape_run_id,
            func.count(func.distinct(ShopBookChange.shop_book_id)),
        )
        .filter(ShopBookChange.scrape_run_id.in_(run_ids))
        .group_by(ShopBookChange.scrape_run_id)
        .all()
    )
    added = {rid: cnt for rid, cnt in added_rows}
    updated = {rid: cnt for rid, cnt in updated_rows}
    return {
        rid: {"items_added": added.get(rid, 0), "items_updated": updated.get(rid, 0)}
        for rid in run_ids
    }


def _parse_phase(phase: str) -> tuple[str, str]:
    """Split 'discover_sitemap' → ('discover', 'sitemap'); 'scan' → ('scan', 'delta')."""  # noqa: E501
    if phase.startswith("discover_"):
        return "discover", phase[len("discover_") :]
    return "scan", "delta"


_DISCOVER_STRATEGIES = frozenset(
    ("sitemap", "categories", "full_crawl", "graphql", "lupasearch")
)


def _cron_run_phase(job_phase: str, job_strategy: str | None) -> str:
    """Compute the scrape_runs.phase value that corresponds to this cron job.

    For discover jobs the DB phase includes the strategy
    (e.g. discover_sitemap). For scan jobs the strategy is UI-only metadata
    (delta/full) and the DB phase is always just 'scan'.
    """
    if job_phase == "scan":
        return "scan"
    if job_strategy and job_strategy in _DISCOVER_STRATEGIES:
        return f"discover_{job_strategy}"
    return job_phase or "scan"


def _run_dict(
    run: ScrapeRun,
    terminal_count: int | None = None,
    vi_count: int = 0,
    items_added: int | None = None,
    items_updated: int | None = None,
) -> dict[str, Any]:
    started_h = 0.0
    if run.started_at:
        start = run.started_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        started_h = (datetime.now(UTC) - start).total_seconds() / 3600
    phase_type, phase_mode = _parse_phase(run.phase)
    _added = items_added if items_added is not None else run.items_added
    _updated = items_updated if items_updated is not None else run.items_updated
    return {
        "id": run.id,
        "shop": run.shop.name,
        "phase": run.phase,
        "phase_type": phase_type,
        "phase_mode": phase_mode,
        "status": run.status,
        "progress": _progress(run, terminal_count),
        "items": _added + _updated,
        "items_added": _added,
        "items_updated": _updated,
        "errors": run.error_count,
        "errors_4xx": run.errors_4xx,
        "errors_5xx": run.errors_5xx,
        "validation_issues": vi_count,
        "elapsed": _elapsed(run),
        "started_ago": _rel(run.started_at),
        "started": _rel(run.started_at),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "urls_total": run.urls_total,
        "urls_processed": run.urls_processed,
        "type": "full",
        "by": "—",
        "startedH": round(started_h, 2),
        "close_reason": run.close_reason,
    }


def _book_dict(sb: ShopBook) -> dict[str, Any]:
    price_str = f"€{sb.price:.2f}" if sb.price is not None else "—"
    if sb.is_active:
        status = "active"
    elif sb.inactive_since:
        status = "out"
    else:
        status = "delisted"
    return {
        "id": sb.id,
        "title": sb.title,
        "author": sb.author or "—",
        "shop": sb.shop.name if sb.shop else "—",
        "isbn": sb.isbn,
        "sku": sb.sku,
        "price": price_str,
        "price_raw": float(sb.price) if sb.price is not None else None,
        "status": status,
        "issues": 0,
        "updated": _rel(sb.last_seen_at),
        "url": sb.url,
        "publisher": sb.publisher,
        "year": sb.year,
        "format": sb.format,
        "type": sb.type,
        "in_stock": sb.in_stock,
        "is_active": sb.is_active,
        "first_seen_at": sb.first_seen_at.isoformat() if sb.first_seen_at else None,
        "last_seen_at": sb.last_seen_at.isoformat() if sb.last_seen_at else None,
        "planned_availability_date": str(sb.planned_availability_date)
        if sb.planned_availability_date
        else None,
        "rating": float(sb.rating) if sb.rating is not None else None,
        "review_count": sb.review_count,
    }


def _url_dict(u: Any) -> dict[str, Any]:
    cls = getattr(u, "classification", None)
    book = getattr(u, "shop_book", None)
    return {
        "id": u.id,
        "url": u.url,
        "shop": u.shop.name if u.shop else "—",
        "url_type": u.url_type or "unknown",
        "source": u.source or "—",
        "fail_count": u.fail_count,
        "status": "error" if u.fail_count >= 3 else "ok",
        "first_seen_at": u.first_seen_at.isoformat() if u.first_seen_at else None,
        "last_seen_ago": _rel(u.last_seen_at),
        "last_scraped_ago": _rel(u.last_seen_at),
        "discovered_ago": _rel(u.first_seen_at),
        "book_title": book.title if book else "—",
        "book_id": book.id if book else None,
        "book_score": cls.book_score if cls else None,
        "is_book": cls.is_book_product if cls else None,
    }


# ─── Overview ───────────────────────────────────────────────────────────────


@router.get("/overview")
def api_overview(session: Session = Depends(get_db)) -> dict[str, Any]:
    stats = get_overview_stats(session)
    completeness = get_data_completeness(session)
    recent_runs = get_recent_runs(session, limit=10)
    issue_clusters = get_validation_summary(session, state="open")
    shops = get_all_shops(session)
    activity = get_scrape_activity_by_day(session, days=14)

    open_issues = sum(c["count"] for c in issue_clusters)

    shop_cards = []
    for s in shops:
        s_stats = get_shop_stats(session, s.id)
        last = get_shop_runs(session, s.id, limit=1)
        last_run = last[0] if last else None
        shop_cards.append(
            {
                "name": s.name,
                "books": s_stats["shop_books"],
                "active": s_stats["active"],
                "issues": 0,
                "last_run_ago": _rel(last_run.started_at if last_run else None),
                "last_run_status": last_run.status if last_run else "—",
            }
        )

    terminal = _run_terminal_counts(session, [r.id for r in recent_runs])
    return {
        "stats": {**stats, "open_issues": open_issues},
        "completeness": [{"field": c["field"], "pct": c["pct"]} for c in completeness],
        "recent_runs": [
            _run_dict(r, terminal_count=terminal.get(r.id)) for r in recent_runs
        ],
        "issue_clusters": issue_clusters[:6],
        "shops": shop_cards,
        "activity": activity,
    }


# ─── Runs ────────────────────────────────────────────────────────────────────


_WHEN_BOUNDS_HOURS = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}


@router.get("/schedule")
def api_schedule(session: Session = Depends(get_db)) -> dict[str, Any]:
    """Enabled cron jobs with next-firing time and last-success timestamp.

    Consumed by the run-list page header to show 'Next run in 4h 23m'
    and 'Last success: 3h ago' badges.
    """
    return {"items": get_schedule_info(session)}


@router.get("/runs/repeated-failures")
def api_repeated_failures(
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Detect (shop, phase) combinations whose last N terminal runs all
    failed with the same `error_reason`. Surfaces a top-of-page banner
    on the run-list view so unattended operation doesn't silently rot.
    """
    items = get_repeated_failures(session)
    return {"items": items}


@router.get("/runs")
def api_runs(
    shop: str = "all",
    phase: str = "all",
    status: str = "all",
    when: str = "any",
    q: str = "",
    page: int = 1,
    per_page: int = 30,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from datetime import timedelta

    from sqlalchemy import String, cast, or_

    # Phase is a Postgres ENUM — cast to text for ILIKE / LIKE.
    phase_text = cast(ScrapeRun.phase, String)

    query = (
        session.query(ScrapeRun)
        .join(Shop, ScrapeRun.shop_id == Shop.id)
        .options(joinedload(ScrapeRun.shop))
        .order_by(ScrapeRun.started_at.desc())
    )
    if shop and shop != "all":
        query = query.filter(Shop.name == shop)
    if phase and phase != "all":
        if phase == "discover":
            # No literal "discover" enum value — match the variants.
            query = query.filter(phase_text.like("discover\\_%"))
        elif phase in (
            "scan",
            "discover_sitemap",
            "discover_categories",
            "discover_full_crawl",
        ):
            query = query.filter(ScrapeRun.phase == phase)
        # Unknown phase → silently match nothing rather than 500.
    if status and status != "all":
        query = query.filter(ScrapeRun.status == status)
    if when in _WHEN_BOUNDS_HOURS:
        cutoff = datetime.now(UTC) - timedelta(hours=_WHEN_BOUNDS_HOURS[when])
        query = query.filter(ScrapeRun.started_at >= cutoff)
    if q.strip():
        token = q.strip()
        like = f"%{token}%"
        clauses = [Shop.name.ilike(like), phase_text.ilike(like)]
        if token.isdigit():
            clauses.append(ScrapeRun.id == int(token))  # type: ignore[arg-type]
        query = query.filter(or_(*clauses))

    total = query.count()
    all_time = session.query(func.count(ScrapeRun.id)).scalar() or 0
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    runs = query.offset((page - 1) * per_page).limit(per_page).all()

    running_now = (
        session.query(func.count(ScrapeRun.id))
        .filter(ScrapeRun.status == "running")
        .scalar()
        or 0
    )
    # Use 24h window so the KPI matches what the "24h" filter shows
    today_cutoff = datetime.now(UTC) - timedelta(hours=24)
    today_total = (
        session.query(func.count(ScrapeRun.id))
        .filter(ScrapeRun.started_at >= today_cutoff)
        .scalar()
        or 0
    )
    today_ok = (
        session.query(func.count(ScrapeRun.id))
        .filter(ScrapeRun.started_at >= today_cutoff, ScrapeRun.status == "completed")
        .scalar()
        or 0
    )
    today_failed = (
        session.query(func.count(ScrapeRun.id))
        .filter(ScrapeRun.started_at >= today_cutoff, ScrapeRun.status == "failed")
        .scalar()
        or 0
    )

    pages = max(1, (total + per_page - 1) // per_page) if total else 1
    run_ids = [r.id for r in runs]
    terminal = _run_terminal_counts(session, run_ids)
    vi_counts = _run_vi_counts(session, run_ids)
    real_counts = _run_real_item_counts(session, run_ids)
    return {
        "runs": [
            _run_dict(
                r,
                terminal_count=terminal.get(r.id),
                vi_count=vi_counts.get(r.id, 0),
                items_added=real_counts.get(r.id, {}).get("items_added"),
                items_updated=real_counts.get(r.id, {}).get("items_updated"),
            )
            for r in runs
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "kpis": {
            "running_now": running_now,
            "today_total": today_total,
            "today_ok": today_ok,
            "today_failed": today_failed,
            "all_time": all_time,
        },
    }


class NewRunRequest(BaseModel):
    shop: str
    phase: str = "scan"
    strategy: str = ""
    mode: str = "delta"
    urls: str = ""  # specific URL(s) for single-item rescrape; bypasses mode
    cron_job_id: int | None = None


def _preflight_checks(
    session: Session, shop_name: str, run_phase: str
) -> tuple[Shop, ScrapeRun | None]:
    """Validate prerequisites before spawning scrapy. Raises HTTPException
    on the first failed check; returns (shop, existing_active_run_or_None).

    Checks:
    - shop exists in DB
    - shop config TOML loads
    - no `running` or `stopping` run for the same shop+phase

    DB reachability is implicit: pool_pre_ping (Track A #11) validates
    every connection at checkout, so a stale socket triggers an
    OperationalError on the first SELECT below rather than mid-run.
    """
    shop = get_shop_by_name(session, shop_name)
    if not shop:
        raise HTTPException(status_code=404, detail=f"Unknown shop: {shop_name}")

    # Shop config TOML must load — validates the parser/spider can boot.
    try:
        from book_scraper.config import load_shop_config

        load_shop_config(shop_name)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Shop config failed to load: {exc}",
        ) from exc

    # No active run for the same shop+phase. `stopping` is also active —
    # firing a second run while the first is still tearing down would
    # double the load on the target.
    existing = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == shop.id,
            ScrapeRun.phase == run_phase,
            ScrapeRun.status.in_(("running", "stopping", "paused")),
        )
        .first()
    )
    return shop, existing


def _spawn_scrapy_in_container(
    *,
    phase: str,
    shop: str,
    strategy: str = "",
    mode: str = "delta",
    urls: str = "",
    cron_job_id: int | None = None,
) -> None:
    """Fire-and-forget a `scrapy crawl` inside the scraper container.

    Raises HTTPException(503) if the docker client or scraper container
    is unreachable.
    """
    client = get_docker_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Docker not available")

    project = os.environ.get("COMPOSE_PROJECT_NAME", "book-scraper")
    containers = client.containers.list(
        filters={
            "label": [
                "com.docker.compose.service=scraper",
                f"com.docker.compose.project={project}",
            ]
        }
    )
    if not containers:
        raise HTTPException(status_code=503, detail="Scraper container not found")

    cmd = ["/app/.venv/bin/scrapy", "crawl", phase, "-a", f"shop={shop}"]
    if phase == "discover" and strategy:
        cmd.extend(["-a", f"strategy={strategy}"])
    if phase == "scan":
        if urls:
            cmd.extend(["-a", f"urls={urls}"])
        elif mode == "full":
            cmd.extend(["-a", "rescrape=true"])
        elif mode == "sample":
            cmd.extend(["-a", "max_urls=10"])
    if cron_job_id is not None:
        cmd.extend(["-a", f"cron_job_id={cron_job_id}"])

    containers[0].exec_run(
        cmd,
        detach=True,
        workdir="/app",
        environment={
            "PYTHONPATH": "/app",
            "DATABASE_URL": (
                "postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper"
            ),
        },
    )


@router.post("/runs")
def api_create_run(
    req: NewRunRequest, session: Session = Depends(get_db)
) -> dict[str, Any]:
    """Trigger a scrape via docker exec into the scraper container."""
    if req.phase not in ("scan", "discover", "match"):
        raise HTTPException(status_code=400, detail=f"Unknown phase: {req.phase}")

    run_phase = (
        f"discover_{req.strategy}"
        if req.phase == "discover" and req.strategy
        else req.phase
    )
    shop, existing = _preflight_checks(session, req.shop, run_phase)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A {run_phase} run for {shop.name} is already "
                f"{existing.status} (run #{existing.id})."
            ),
        )

    _spawn_scrapy_in_container(
        phase=req.phase,
        shop=req.shop,
        strategy=req.strategy,
        mode=req.mode,
        urls=req.urls,
        cron_job_id=req.cron_job_id,
    )
    return {
        "status": "started",
        "shop": req.shop,
        "phase": req.phase,
        "strategy": req.strategy,
        "mode": req.mode,
    }


@router.post("/runs/{run_id}/stop")
def api_stop_run(run_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Request a clean stop of an active run.

    DB-mediated: flips `status` from 'running' to 'stopping' under a
    race-safe UPDATE. The spider's HeartbeatExtension observes the
    transition on its next tick and exits cleanly; the spider's
    `closed()` callback transitions to 'failed' with
    error_reason='stopped_by_operator'. If the spider never sees the
    transition (e.g. process died), the dashboard reaper marks the
    run failed via heartbeat_timeout after DEAD_RUN_SECONDS.

    Idempotent: clicking on an already-stopping/terminal run is a 200
    no-op carrying the current status.
    """
    run = session.get(ScrapeRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status == "running":
        run.status = "stopping"
        emit_scrape_run_event(
            session,
            run_id,
            run_event_types.STOP_REQUESTED,
            actor=run_event_types.ACTOR_OPERATOR,
        )
        session.commit()
    return {"run_id": run_id, "status": run.status}


@router.post("/runs/{run_id}/pause")
def api_pause_run(run_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Request a graceful pause of a running scan.

    DB-mediated: flips `status` from 'running' to 'paused'. The spider
    polls status between requests and enters a sleep loop on 'paused'.
    The heartbeat keeps ticking during pause so the reaper doesn't kill
    the run. Resume with POST /api/runs/{id}/resume.

    Idempotent: pausing an already-paused or terminal run is a 200
    no-op carrying the current status.
    """
    run = session.get(ScrapeRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status == "running":
        run.status = "paused"
        emit_scrape_run_event(
            session,
            run_id,
            run_event_types.PAUSED,
            payload={"previous_status": "running"},
            actor=run_event_types.ACTOR_OPERATOR,
        )
        session.commit()
    return {"run_id": run_id, "status": run.status}


@router.post("/runs/{run_id}/resume")
def api_resume_run(run_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Resume a paused run.

    Flips `status` from 'paused' back to 'running'. The spider's pause
    loop observes the transition on its next poll and resumes dispatching
    requests. Idempotent: resuming a non-paused run is a no-op.
    """
    run = session.get(ScrapeRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status == "paused":
        run.status = "running"
        # Refresh heartbeat so the reaper doesn't immediately kill this
        # run — a long pause leaves last_heartbeat hours stale.
        run.last_heartbeat = datetime.now(UTC)
        emit_scrape_run_event(
            session,
            run_id,
            run_event_types.RESUMED,
            payload={"previous_status": "paused"},
            actor=run_event_types.ACTOR_OPERATOR,
        )
        session.commit()
    return {"run_id": run_id, "status": run.status}


@router.post("/runs/{run_id}/rerun")
def api_rerun_run(run_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Re-fire a failed run.

    Flags the failed run `resumable_after_failure=True` so Track A's
    `find_resumable_run` picks it up; the new scrapy subprocess then
    inherits the original run's pending queue via
    `inherit_pending_items`. Old run row stays for postmortem; new run
    gets its own id.
    """
    run = (
        session.query(ScrapeRun)
        .options(joinedload(ScrapeRun.shop))
        .filter(ScrapeRun.id == run_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("failed", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Only terminal runs can be re-run; status={run.status!r}",
        )

    # Pre-flight first so we surface DB / config / concurrent-run
    # problems before firing the subprocess.
    shop, existing = _preflight_checks(session, run.shop.name, run.phase)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A {run.phase} run for {shop.name} is already "
                f"{existing.status} (run #{existing.id})."
            ),
        )

    # Mark the failed run resumable so the new scrapy process adopts
    # its queue. completed runs have no pending items, so the flag is
    # harmless.
    if run.status == "failed":
        run.resumable_after_failure = True
    emit_scrape_run_event(
        session,
        run_id,
        run_event_types.RERUN,
        payload={"previous_status": run.status},
        actor=run_event_types.ACTOR_OPERATOR,
    )
    session.commit()

    # Phase form: `scan` or `discover_<strategy>` or `discover` plain.
    phase: str
    strategy: str
    if run.phase.startswith("discover_"):
        phase = "discover"
        strategy = run.phase[len("discover_") :]
    else:
        phase = run.phase
        strategy = ""

    _spawn_scrapy_in_container(
        phase=phase, shop=run.shop.name, strategy=strategy, mode="delta"
    )
    return {"status": "started", "rerun_of": run_id, "shop": run.shop.name}


@router.post("/runs/{run_id}/continue")
def api_continue_run(run_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Resume a failed run on the same `scrape_runs` row.

    Flips the run from 'failed' → 'running', then spawns a fresh scrapy
    subprocess. The spider's `find_resumable_run` matches Case A
    (running + has pending items) and reuses this same row, so no new
    run id is created. Works for both scan and discover phases.
    Atomic against concurrent /continue calls via row-level locking;
    rolls the row back to its prior terminal state if spawn fails.
    """
    run = (
        session.query(ScrapeRun)
        .filter(ScrapeRun.id == run_id)
        .with_for_update(of=ScrapeRun)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status != "failed":
        raise HTTPException(
            status_code=400,
            detail=(f"Only failed runs can be continued; status={run.status!r}"),
        )

    pending_count = (
        session.query(func.count(ScrapeUrlItem.id))
        .filter(
            ScrapeUrlItem.run_id == run.id,
            ScrapeUrlItem.status == "pending",
        )
        .scalar()
        or 0
    )
    if pending_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Nothing left to continue: no pending URLs on this run.",
        )

    shop_name = session.query(Shop.name).filter(Shop.id == run.shop_id).scalar()
    if shop_name is None:
        raise HTTPException(status_code=404, detail="Shop not found")

    shop, existing = _preflight_checks(session, shop_name, run.phase)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A {run.phase} run for {shop.name} is already "
                f"{existing.status} (run #{existing.id})."
            ),
        )

    original_close_reason = run.close_reason
    original_finished_at = run.finished_at
    original_last_heartbeat = run.last_heartbeat
    original_pid = run.pid

    run.status = "running"
    run.finished_at = None
    run.close_reason = None
    run.last_heartbeat = datetime.now(UTC)
    run.pid = None
    emit_scrape_run_event(
        session,
        run_id,
        run_event_types.CONTINUED,
        payload={"pending_count": int(pending_count)},
        actor=run_event_types.ACTOR_OPERATOR,
    )
    session.commit()

    cont_phase: str
    cont_strategy: str
    if run.phase.startswith("discover_"):
        cont_phase = "discover"
        cont_strategy = run.phase[len("discover_") :]
    else:
        cont_phase = run.phase
        cont_strategy = ""

    try:
        _spawn_scrapy_in_container(
            phase=cont_phase, shop=shop_name, strategy=cont_strategy, mode="delta"
        )
    except Exception:
        session.query(ScrapeRun).filter(ScrapeRun.id == run_id).update(
            {
                "status": "failed",
                "finished_at": original_finished_at,
                "close_reason": original_close_reason,
                "last_heartbeat": original_last_heartbeat,
                "pid": original_pid,
            }
        )
        session.commit()
        raise

    return {"status": "continued", "run_id": run_id, "shop": shop_name}


@router.post("/runs/{run_id}/retry")
def api_retry_run_failures(
    run_id: int,
    error_reason: str = "",
    error_reason_is_null: bool = False,
    http_status: int | None = None,
    http_status_is_null: bool = False,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Reset failed scrape_url_items to pending so they get re-scraped.

    Filters mirror the failure-card buttons: card-level "Retry all" sends
    no filters; per-group "Retry group" sends the bucket's reason+http
    keys (with `*_is_null` flags for the nullable buckets — same sentinel
    contract as `/api/runs/{id}/urls`).

    For terminal runs (`failed`/`completed`) this also re-spawns the
    spider so the resets actually get processed (mirrors `/continue`).
    For alive runs (`running`/`paused`/`stopping`) the resident spider
    picks the rows up on its next claim cycle — no spawn needed.

    Row resets are committed before the spawn attempt: if spawn fails we
    roll the run state back, but the rows stay `pending` so the operator
    can retry the spawn (or call `/continue`) without losing the reset.
    """
    run = (
        session.query(ScrapeRun)
        .filter(ScrapeRun.id == run_id)
        .with_for_update(of=ScrapeRun)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.phase != "scan":
        raise HTTPException(
            status_code=400,
            detail=f"Retry is only supported for scan runs; phase={run.phase!r}",
        )

    # Candidate selection: items whose latest scrape_failures event matches
    # the requested bucket AND whose queue row is currently `failed`. The
    # window-function subquery mirrors the failure card's grouping query so
    # retry acts on exactly the rows the operator just saw.
    needs_failure_filter = (
        error_reason_is_null
        or bool(error_reason)
        or http_status_is_null
        or http_status is not None
    )
    candidate_q = session.query(ScrapeUrlItem.id).filter(
        ScrapeUrlItem.run_id == run.id,
        ScrapeUrlItem.status == "failed",
    )
    if needs_failure_filter:
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
            .filter(ScrapeFailure.run_id == run.id)
            .subquery()
        )
        candidate_q = candidate_q.join(
            latest_failure,
            latest_failure.c.scrape_url_item_id == ScrapeUrlItem.id,
        ).filter(latest_failure.c.rn == 1)
        if error_reason_is_null:
            candidate_q = candidate_q.filter(latest_failure.c.error_reason.is_(None))
        elif error_reason:
            candidate_q = candidate_q.filter(
                latest_failure.c.error_reason == error_reason
            )
        if http_status_is_null:
            candidate_q = candidate_q.filter(latest_failure.c.http_status.is_(None))
        elif http_status is not None:
            candidate_q = candidate_q.filter(
                latest_failure.c.http_status == http_status
            )

    candidate_ids = [r[0] for r in candidate_q.all()]
    matches = len(candidate_ids)
    if matches == 0:
        raise HTTPException(
            status_code=400,
            detail="No matching failed URLs to retry.",
        )

    is_terminal = run.status in ("failed", "completed")
    shop_name: str | None = None
    if is_terminal:
        # Validate spawn prerequisites BEFORE we touch any rows so we
        # don't end up with pending rows for a run that can't be revived.
        shop_name = session.query(Shop.name).filter(Shop.id == run.shop_id).scalar()
        if shop_name is None:
            raise HTTPException(status_code=404, detail="Shop not found")
        shop, existing = _preflight_checks(session, shop_name, run.phase)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A {run.phase} run for {shop.name} is already "
                    f"{existing.status} (run #{existing.id})."
                ),
            )

    session.query(ScrapeUrlItem).filter(ScrapeUrlItem.id.in_(candidate_ids)).update(
        {
            "status": "pending",
            # PR 3: error_reason column dropped. http_status is the
            # last-response cache; reset it so a retry that succeeds
            # doesn't display the prior failure's status alongside `done`.
            "http_status": None,
            "claimed_at": None,
            "done_at": None,
        },
        synchronize_session=False,
    )

    retry_payload: dict[str, Any] = {"rows_reset": int(matches)}
    if error_reason_is_null:
        retry_payload["error_reason_filter"] = None
    elif error_reason:
        retry_payload["error_reason_filter"] = error_reason
    if http_status_is_null:
        retry_payload["http_status_filter"] = None
    elif http_status is not None:
        retry_payload["http_status_filter"] = http_status

    emit_scrape_run_event(
        session,
        run_id,
        run_event_types.RETRY_FAILURES,
        payload=retry_payload,
        actor=run_event_types.ACTOR_OPERATOR,
    )

    if not is_terminal:
        session.commit()
        return {
            "retried": int(matches),
            "run_id": run_id,
            "run_status": run.status,
            "spawned": False,
        }

    original_close_reason = run.close_reason
    original_finished_at = run.finished_at
    original_last_heartbeat = run.last_heartbeat
    original_pid = run.pid
    original_status = run.status

    run.status = "running"
    run.finished_at = None
    run.close_reason = None
    run.last_heartbeat = datetime.now(UTC)
    run.pid = None
    session.commit()

    try:
        assert shop_name is not None  # guarded above for is_terminal branch
        _spawn_scrapy_in_container(
            phase="scan", shop=shop_name, strategy="", mode="delta"
        )
    except Exception:
        session.query(ScrapeRun).filter(ScrapeRun.id == run_id).update(
            {
                "status": original_status,
                "finished_at": original_finished_at,
                "close_reason": original_close_reason,
                "last_heartbeat": original_last_heartbeat,
                "pid": original_pid,
            }
        )
        session.commit()
        raise

    return {
        "retried": int(matches),
        "run_id": run_id,
        "run_status": "running",
        "spawned": True,
    }


@router.post("/runs/{run_id}/failures/ack")
def api_acknowledge_run_failures(
    run_id: int,
    error_reason: str = "",
    error_reason_is_null: bool = False,
    http_status: int | None = None,
    http_status_is_null: bool = False,
    note: str = "",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Mark a failure-card bucket as `already_seen` so it stops surfacing.

    Filter contract mirrors `/retry` and `/urls`: pass the bucket's
    `error_reason` + `http_status` (with `*_is_null` flags for the
    nullable buckets). The endpoint flips `lifecycle_state` to
    `already_seen` for every `scrape_failures` row in the run that
    matches — including history events, so a retried-and-still-failing
    URL doesn't pop back as `new` on the next attempt.
    """
    run = session.get(ScrapeRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    update_filter = [ScrapeFailure.run_id == run_id]
    if error_reason_is_null:
        update_filter.append(ScrapeFailure.error_reason.is_(None))
    elif error_reason:
        update_filter.append(ScrapeFailure.error_reason == error_reason)
    if http_status_is_null:
        update_filter.append(ScrapeFailure.http_status.is_(None))
    elif http_status is not None:
        update_filter.append(ScrapeFailure.http_status == http_status)

    matches = (
        session.query(func.count(ScrapeFailure.id)).filter(*update_filter).scalar() or 0
    )
    if matches == 0:
        raise HTTPException(
            status_code=400,
            detail="No matching scrape_failures rows to acknowledge.",
        )

    now = datetime.now(UTC)
    update_values: dict[str, Any] = {
        "lifecycle_state": "already_seen",
        "acknowledged_at": now,
    }
    if note:
        update_values["acknowledged_note"] = note

    session.query(ScrapeFailure).filter(*update_filter).update(
        update_values,  # type: ignore[arg-type]
        synchronize_session=False,
    )
    session.commit()

    return {
        "acknowledged": int(matches),
        "run_id": run_id,
        "error_reason": None if error_reason_is_null else (error_reason or None),
        "http_status": None
        if http_status_is_null
        else (http_status if http_status is not None else None),
    }


@router.get("/runs/{run_id}")
def api_run_detail(run_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    run = (
        session.query(ScrapeRun)
        .options(joinedload(ScrapeRun.shop))
        .filter(ScrapeRun.id == run_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    issues = get_run_issue_summary(session, run_id)
    terminal = _run_terminal_counts(session, [run_id]).get(run_id)
    close_reason = get_run_close_reason(session, run)
    item_counts = get_run_item_counts(session, run_id)
    pending_count = (
        session.query(func.count(ScrapeUrlItem.id))
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status == "pending",
        )
        .scalar()
        or 0
    )
    base = _run_dict(run, terminal_count=terminal)
    base.update(item_counts)
    base["items"] = item_counts["items_added"] + item_counts["items_updated"]
    events = get_scrape_run_events(session, run_id)
    return {
        **base,
        "issues": issues,
        "close_reason": close_reason,
        "pending_count": pending_count,
        "events": events,
    }


@router.get("/runs/{run_id}/books")
def api_run_books(
    run_id: int,
    type: str = "added",
    page: int = 1,
    per_page: int = 50,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    run = session.get(ScrapeRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if type not in ("added", "updated"):
        raise HTTPException(status_code=400, detail="type must be 'added' or 'updated'")
    page = max(1, page)
    per_page = max(1, min(100, per_page))
    if type == "added":
        books, total = get_run_books_added(
            session, run_id, page=page, per_page=per_page
        )
        serialised = [_book_dict(b) for b in books]
    else:
        rows, total = get_run_books_updated(
            session, run_id, page=page, per_page=per_page
        )
        serialised = [{**_book_dict(sb), "changed_fields": cf} for sb, cf in rows]
    pages = max(math.ceil(total / per_page), 1)
    return {"books": serialised, "total": total, "page": page, "pages": pages}


@router.get("/runs/{run_id}/live")
def api_run_live(
    run_id: int,
    include_acked: bool = False,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Live observability snapshot for a single run.

    Polled by HFRunDetail every ~2s while the run is 'running'.
    Everything is derived from scrape_url_items + scrape_runs — no
    new tables, no in-memory state.

    Health verdict: 'dead' if heartbeat > 30s old; 'stuck' if heartbeat
    fresh but an in-flight row's claimed_at exceeds DOWNLOAD_TIMEOUT*2
    (= 30s); 'healthy' otherwise. See live observability spec.
    """
    run = session.get(ScrapeRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    now = datetime.now(UTC)
    last_heartbeat = run.last_heartbeat
    if last_heartbeat is not None and last_heartbeat.tzinfo is None:
        last_heartbeat = last_heartbeat.replace(tzinfo=UTC)
    last_heartbeat_age_s: float | None = None
    if last_heartbeat is not None:
        last_heartbeat_age_s = max(0.0, (now - last_heartbeat).total_seconds())

    in_flight = get_run_in_flight(session, run_id)
    rate = get_run_rate_window(session, run_id)
    failure_groups = get_run_failure_groups(
        session, run_id, include_acked=include_acked
    )
    recent_activity = get_run_recent_activity(session, run_id, limit=20)
    events = get_scrape_run_events(session, run_id)

    health = get_run_live_health(run)
    # Refine to 'stuck' when heartbeat is fresh but the oldest in-flight
    # row has been claimed for longer than 2× the network timeout.
    hung_threshold_s = 30.0  # DOWNLOAD_TIMEOUT (15) × 2
    if health == "healthy":
        for row in in_flight:
            age = row.get("claimed_age_s") or 0.0
            if age > hung_threshold_s:
                health = "stuck"
                break

    # ETA: estimate minutes remaining based on pending URL count / rate.
    req_per_min: float = 0.0
    if rate and rate.get("window_s", 0) > 0:
        req_per_min = (rate["done"] / rate["window_s"]) * 60
    eta_min = (
        get_run_eta(session, run_id, req_per_min) if run.status == "running" else None
    )

    return {
        "run_id": run_id,
        "status": run.status,
        "health": health,
        "last_heartbeat_age_s": last_heartbeat_age_s,
        "in_flight": in_flight,
        "rate": rate,
        "eta_min": eta_min,
        "failure_groups": failure_groups,
        "recent_activity": recent_activity,
        "events": events,
    }


@router.get("/runs/{run_id}/urls")
def api_run_urls(
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
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """URL queue (live `scrape_url_items`) or history (`discovered_urls`)
    for a run, with status counts and pagination."""
    run = session.get(ScrapeRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    breakdown = get_run_url_breakdown(session, run_id)
    has_live = sum(breakdown.values()) > 0
    page = max(page, 1)
    per_page = max(min(per_page, 200), 1)

    if has_live:
        if status not in {"all", *RUN_URL_STATUSES}:
            status = "all"
        if order not in ("asc", "desc"):
            order = "desc"
        items, total = get_run_url_items(
            session,
            run_id,
            status=status,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
            error_reason=error_reason,
            error_reason_is_null=error_reason_is_null,
            http_status=http_status,
            http_status_is_null=http_status_is_null,
        )
        rows = []
        for it, title, shop_book_id, latest_error_reason in items:
            duration_ms: int | None = None
            if it.claimed_at and it.done_at:
                duration_ms = int((it.done_at - it.claimed_at).total_seconds() * 1000)
            # error_reason now sourced from the latest scrape_failures
            # event (PR 3). Surface it only on currently-failed rows so a
            # retried-and-succeeded URL doesn't show its old failure.
            display_error_reason = (
                latest_error_reason if it.status == "failed" else None
            )
            rows.append(
                {
                    "url": it.url,
                    "title": title,
                    "status": it.status,
                    "url_type": it.url_type,
                    "claimed_at": it.claimed_at.isoformat() if it.claimed_at else None,
                    "done_at": it.done_at.isoformat() if it.done_at else None,
                    "http_status": it.http_status,
                    "error_reason": display_error_reason,
                    "duration_ms": duration_ms,
                    "request_delay_s": it.request_delay_s,
                    "delay_source": it.delay_source,
                    "response_bytes": it.response_bytes,
                    "item_id": it.id,
                    "discovered_url_id": it.discovered_url_id,
                    "shop_book_id": shop_book_id,
                    "attempts": it.attempts,
                }
            )
        source = "live"
    else:
        # Fallback for old discover runs that completed before items were kept.
        # New runs (both scan and discover) always have live rows.
        items_du, total = get_run_discovered_urls(
            session, run_id, page=page, per_page=per_page
        )
        rows = [
            {
                "id": du.id,
                "url": du.url,
                "url_type": du.url_type,
                "last_http_status": du.last_http_status,
                "last_checked_at": (
                    du.last_checked_at.isoformat() if du.last_checked_at else None
                ),
            }
            for du in items_du
        ]
        source = "history"
        status = "all"

    pages = max((total + per_page - 1) // per_page, 1)
    return {
        "source": source,
        "breakdown": breakdown,
        "status": status,
        "statuses": list(RUN_URL_STATUSES),
        "sort": sort,
        "order": order,
        "rows": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


# ─── Shop Books ──────────────────────────────────────────────────────────────


@router.get("/shop-books")
def api_shop_books(
    page: int = 1,
    per_page: int = 30,
    search: str = "",
    shop: str = "",
    active: str = "",
    missing_field: str = "",
    type_filter: str = "",
    format_filter: str = "",
    has_isbn: bool = False,
    url_unreachable: bool = False,
    category: str = "",
    sort_by: str = "",
    sort_order: str = "desc",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    shop_id = None
    if shop and shop != "all":
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else -1  # unknown shop → match nothing

    page = max(1, page)
    per_page = max(1, min(per_page, 200))
    books, total = get_shop_books_page(
        session,
        page=page,
        per_page=per_page,
        search=search,
        shop_id=shop_id,
        active_filter=active if active and active != "all" else "",
        missing_field=missing_field if missing_field and missing_field != "any" else "",
        type_filter=type_filter if type_filter and type_filter != "all" else "",
        format_filter=format_filter if format_filter and format_filter != "all" else "",
        has_isbn=has_isbn,
        url_unreachable=url_unreachable,
        category=category.strip() if category.strip() else "",
        sort_by=sort_by,
        sort_order=sort_order,
    )

    total_books = session.query(func.count(ShopBook.id)).scalar() or 0
    active_books = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.is_active.is_(True))
        .scalar()
        or 0
    )
    missing_isbn = (
        session.query(func.count(ShopBook.id)).filter(ShopBook.isbn.is_(None)).scalar()
        or 0
    )
    missing_price = (
        session.query(func.count(ShopBook.id)).filter(ShopBook.price.is_(None)).scalar()
        or 0
    )
    unreachable_books = (
        session.query(func.count(ShopBook.id))
        .join(
            DiscoveredUrl,
            (DiscoveredUrl.shop_book_id == ShopBook.id)
            & (DiscoveredUrl.url_type == "unreachable"),
        )
        .scalar()
        or 0
    )

    pages = max(1, (total + per_page - 1) // per_page) if total else 1
    return {
        "books": [_book_dict(b) for b in books],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "kpis": {
            "total": total_books,
            "active": active_books,
            "missing_isbn": missing_isbn,
            "missing_price": missing_price,
            "unreachable": unreachable_books,
        },
    }


@router.get("/shop-books/{book_id}")
def api_shop_book_detail(
    book_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
    sb = (
        session.query(ShopBook)
        .options(joinedload(ShopBook.shop))
        .filter(ShopBook.id == book_id)
        .first()
    )
    if not sb:
        raise HTTPException(status_code=404, detail="Book not found")

    issues = get_shop_book_issues(session, book_id)
    prices = get_price_history(session, book_id)
    changes = get_shop_book_changes(session, book_id, limit=20)

    price_history = [
        {
            "scraped_at": p.scraped_at.isoformat(),
            "price": float(p.price) if p.price is not None else None,
            "in_stock": p.in_stock,
        }
        for p in prices
    ]
    change_list = [
        {
            "field": c.field,
            "old_value": c.old_value,
            "new_value": c.new_value,
            "changed_at": c.changed_at.isoformat() if c.changed_at else None,
        }
        for c in changes
    ]

    url_count = (
        session.query(func.count(DiscoveredUrl.id))
        .filter(DiscoveredUrl.shop_book_id == book_id)
        .scalar()
        or 0
    )
    run_ids: list[int] = [c.scrape_run_id for c in changes if c.scrape_run_id]
    if sb.last_run_id and sb.last_run_id not in run_ids:
        run_ids.insert(0, sb.last_run_id)
    run_count = len(set(run_ids))
    recent_runs: list[dict[str, Any]] = []
    if run_ids:
        runs_q = (
            session.query(ScrapeRun)
            .options(joinedload(ScrapeRun.shop))
            .filter(ScrapeRun.id.in_(set(run_ids)))
            .order_by(ScrapeRun.started_at.desc())
            .limit(20)
            .all()
        )
        t_map = _run_terminal_counts(session, [r.id for r in runs_q])
        recent_runs = [_run_dict(r, terminal_count=t_map.get(r.id)) for r in runs_q]

    # URL reachability + classification — join by shop_book_id FK
    linked_url = (
        session.query(DiscoveredUrl)
        .options(joinedload(DiscoveredUrl.classification))
        .filter(DiscoveredUrl.shop_book_id == book_id)
        .first()
    )
    cls = linked_url.classification if linked_url else None

    # Load shop_book_attributes (translator, dimensions, cover_type,
    # language, pages, color, original_title, is_new, …) — captured by
    # the parsers but previously not surfaced on the detail view.
    attributes = (
        session.query(ShopBookAttribute)
        .filter(ShopBookAttribute.shop_book_id == book_id)
        .order_by(ShopBookAttribute.key)
        .all()
    )
    attribute_map = {a.key: a.value for a in attributes}

    d = _book_dict(sb)
    d["issues"] = len(issues)
    d["issues_list"] = issues
    d["price_history"] = price_history
    d["changes"] = change_list
    d["description"] = sb.description
    d["image_url"] = sb.image_url
    d["categories"] = sb.categories or []
    d["attributes"] = attribute_map
    d["url_count"] = url_count
    d["run_count"] = run_count
    d["runs"] = recent_runs
    d["url_status"] = linked_url.url_type if linked_url else None
    d["url_fail_count"] = linked_url.fail_count if linked_url else 0
    d["classification"] = (
        {
            "book_score": cls.book_score,
            "is_book_product": cls.is_book_product,
            "reasons": cls.reasons or [],
            "classified_at": cls.classified_at.isoformat()
            if cls.classified_at
            else None,
            "classified_ago": _rel(cls.classified_at),
        }
        if cls
        else None
    )
    return d


# ─── URLs ────────────────────────────────────────────────────────────────────


@router.get("/urls")
def api_urls(
    page: int = 1,
    per_page: int = 30,
    shop: str = "",
    url_type: str = "",
    search: str = "",
    is_book: str = "",
    failing: bool = False,
    has_book: bool = False,
    sort_by: str = "discovered",
    sort_order: str = "desc",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    shop_id = None
    if shop and shop != "all":
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else -1

    page = max(1, page)
    per_page = max(1, min(per_page, 200))
    urls, total = get_discovered_urls_page(
        session,
        page=page,
        per_page=per_page,
        shop_id=shop_id,
        url_type=url_type if url_type and url_type != "all" else "",
        search=search,
        is_book=is_book if is_book and is_book != "any" else "",
        failing=failing,
        has_book=has_book,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    stats = get_discovered_urls_stats(session, shop_id=shop_id)
    pages = max(1, (total + per_page - 1) // per_page) if total else 1

    return {
        "urls": [_url_dict(u) for u in urls],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "stats": stats,
    }


@router.get("/urls/{url_id}")
def api_url_detail(url_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    result = get_url_detail(session, url_id)
    if result is None:
        raise HTTPException(status_code=404, detail="URL not found")
    url, cls = result
    d = _url_dict(url)
    if cls:
        d["classification"] = {
            "book_score": cls.book_score,
            "is_book_product": cls.is_book_product,
            "reasons": cls.reasons if hasattr(cls, "reasons") else [],
        }
    d["last_http_status"] = url.last_http_status
    d["url_type"] = url.url_type
    d["last_checked_at"] = (
        url.last_checked_at.isoformat() if url.last_checked_at else None
    )
    d["last_checked_ago"] = _rel(url.last_checked_at)

    # Check history from scrape_url_items via discovered_url_id
    items_q = (
        session.query(ScrapeUrlItem, ScrapeRun)
        .join(ScrapeRun, ScrapeUrlItem.run_id == ScrapeRun.id)
        .filter(
            ScrapeUrlItem.discovered_url_id == url_id,
            ScrapeUrlItem.status.in_(["done", "failed"]),
        )
        .order_by(ScrapeRun.started_at.desc())
        .limit(20)
        .all()
    )
    d["check_history"] = [
        {
            "run_id": item.run_id,
            "when": _rel(run.started_at),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "http_status": item.http_status,
            "status": "error"
            if not item.http_status or item.http_status >= 400
            else "ok",
            "done_at": item.done_at.isoformat() if item.done_at else None,
        }
        for item, run in items_q
    ]
    return d


# ─── Shops ───────────────────────────────────────────────────────────────────


def _configured_discover_strategies(shop_name: str) -> list[str]:
    """Return the discover strategy names that this shop has wired up.

    Used by the dashboard's run/schedule dialogs to render only the
    options that will actually work — pegasas, for example, exposes
    `graphql` + `lupasearch` but not `sitemap`/`categories`.
    """
    try:
        from book_scraper.config import load_shop_config

        cfg = load_shop_config(shop_name)
    except Exception:
        return []
    available: list[str] = []
    # Order matches the dialog: cheap-and-fast first, slowest last.
    for name in (
        "sitemap",
        "categories",
        "graphql",
        "lupasearch",
        "ibiblioteka_api",
        "full_crawl",
    ):
        if getattr(cfg.discover, name, None) is not None:
            available.append(name)
    return available


@router.get("/books")
def api_books(
    data_source: str | None = None,
    has_isbn: bool | None = None,
    has_shops: bool | None = None,
    year: int | None = None,
    page: int = 1,
    per_page: int = 50,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import list_books

    return list_books(
        session,
        data_source=data_source,
        has_isbn=has_isbn,
        has_shops=has_shops,
        year=year,
        page=page,
        per_page=per_page,
    )


@router.get("/books/{book_id}")
def api_book_detail(book_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    from book_scraper.dashboard.queries import book_detail

    detail = book_detail(session, book_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return detail


@router.get("/shops")
def api_shops(session: Session = Depends(get_db)) -> dict[str, Any]:
    shops = get_all_shops(session)
    result = []
    for s in shops:
        stats = get_shop_stats(session, s.id)
        runs = get_shop_runs(session, s.id, limit=1)
        last = runs[0] if runs else None
        result.append(
            {
                "id": s.id,
                "name": s.name,
                "base_url": s.base_url,
                "books": stats["shop_books"],
                "active": stats["active"],
                "discovered_urls": stats["discovered_urls"],
                "prices": stats["prices"],
                "last_run_ago": _rel(last.started_at if last else None),
                "last_run_status": last.status if last else "—",
                "discover_strategies": _configured_discover_strategies(s.name),
            }
        )
    return {"shops": result}


@router.get("/shops/{shop_name}")
def api_shop_detail(
    shop_name: str, session: Session = Depends(get_db)
) -> dict[str, Any]:
    shop = get_shop_by_name(session, shop_name)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    stats = get_shop_stats(session, shop.id)
    field_stats = get_shop_field_stats(session, shop.id)
    runs = get_shop_runs(session, shop.id, limit=20)
    last_run = runs[0] if runs else None
    terminal = _run_terminal_counts(session, [r.id for r in runs])
    rate_settings = {s.key: s.value for s in shop.settings}
    return {
        "id": shop.id,
        "name": shop.name,
        "base_url": shop.base_url,
        **stats,
        "books": stats["shop_books"],
        "last_run_ago": _rel(last_run.started_at if last_run else None),
        "last_run_status": last_run.status if last_run else "—",
        "field_stats": field_stats,
        "recent_runs": [_run_dict(r, terminal_count=terminal.get(r.id)) for r in runs],
        "rate_settings": rate_settings,
        "discover_strategies": _configured_discover_strategies(shop.name),
    }


# ─── Cron ────────────────────────────────────────────────────────────────────


def _fmt_next(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return "in < 1m"
    m = seconds // 60
    if m < 60:
        return f"in {m}m"
    h, m = divmod(m, 60)
    return f"in {h}h {m}m" if m else f"in {h}h"


def _fmt_dur(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m" if m else f"{h}h"
    if m:
        return f"{m}m {s}s" if s else f"{m}m"
    return f"{s}s"


def _cron_job_metrics(
    session: Session,
    shop_id: int,
    run_phase: str,
) -> dict[str, Any]:
    """Return last_status, last_run_at, and avg_duration_s for a cron job."""
    last_run = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == shop_id,
            ScrapeRun.phase == run_phase,
            ScrapeRun.status.in_(["completed", "failed"]),
        )
        .order_by(ScrapeRun.finished_at.desc().nullslast())
        .limit(1)
        .one_or_none()
    )
    last_status = (
        "ok"
        if (last_run and last_run.status == "completed")
        else ("fail" if last_run else None)
    )

    # Average duration from last 30 completed runs
    recent = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == shop_id,
            ScrapeRun.phase == run_phase,
            ScrapeRun.status == "completed",
            ScrapeRun.finished_at.isnot(None),
        )
        .order_by(ScrapeRun.finished_at.desc().nullslast())
        .limit(30)
        .all()
    )
    durations = [
        (r.finished_at - r.started_at).total_seconds()
        for r in recent
        if r.finished_at and r.started_at
    ]
    avg_dur_s = sum(durations) / len(durations) if durations else None

    return {
        "last_status": last_status,
        "avg_dur_s": avg_dur_s,
    }


@router.get("/cron")
def api_cron(session: Session = Depends(get_db)) -> dict[str, Any]:
    from croniter import croniter  # type: ignore[import-untyped]

    jobs = list_cron_jobs(session)
    now = datetime.now(UTC)
    result = []
    for j in jobs:
        try:
            run_phase = _cron_run_phase(j.phase, j.strategy)
            next_dt: datetime | None
            next_in_s: int | None
            try:
                cron = croniter(j.cron_expression, now)
                next_dt = cron.get_next(datetime).replace(tzinfo=UTC)
                next_in_s = int((next_dt - now).total_seconds())
            except Exception:
                next_dt = None
                next_in_s = None

            metrics = _cron_job_metrics(session, j.shop_id, run_phase)
            chain_job = (
                session.get(CronJob, j.chain_to_job_id) if j.chain_to_job_id else None
            )
            chain_to_name = (
                f"{chain_job.shop.name}.{chain_job.phase}"
                f".{chain_job.strategy or 'default'}"
                if chain_job
                else None
            )
            result.append(
                {
                    "id": j.id,
                    "name": f"{j.shop.name}.{j.phase}.{j.strategy or 'default'}",
                    "shop": j.shop.name,
                    "phase": j.phase,
                    "strategy": j.strategy or "",
                    "args": j.args or "",
                    "cron": j.cron_expression,
                    "enabled": j.enabled,
                    "last": _rel(j.last_run_at),
                    "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
                    "last_status": metrics["last_status"] or "ok",
                    "next": _fmt_next(next_in_s) if j.enabled else "—",
                    "next_run_at": (
                        next_dt.isoformat() if next_dt and j.enabled else None
                    ),
                    "avg_dur": _fmt_dur(metrics["avg_dur_s"]),
                    "chain_to_id": j.chain_to_job_id,
                    "chain_to_name": chain_to_name,
                }
            )
        except Exception:
            import logging as _logging

            _logging.getLogger(__name__).exception("api_cron: skipping job %d", j.id)
    return {"jobs": result}


@router.get("/cron/{job_id}/detail")
def api_cron_detail(job_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    from zoneinfo import ZoneInfo

    from croniter import croniter

    job = get_cron_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    run_phase = _cron_run_phase(job.phase, job.strategy)
    now = datetime.now(UTC)
    tz = ZoneInfo("Europe/Vilnius")
    today = now.astimezone(tz).date()

    # Upcoming 5 fire times
    upcoming: list[dict[str, Any]] = []
    if job.enabled:
        try:
            cron = croniter(job.cron_expression, now)
            for _ in range(5):
                nxt = cron.get_next(datetime).replace(tzinfo=UTC)
                nxt_local = nxt.astimezone(tz)
                nxt_date = nxt_local.date()
                delta_s = int((nxt - now).total_seconds())
                if nxt_date == today:
                    date_label = "today"
                elif (nxt_date - today).days == 1:
                    date_label = "tomorrow"
                else:
                    date_label = nxt_local.strftime("%-d %b")
                upcoming.append(
                    {
                        "when": _fmt_next(delta_s),
                        "at": nxt_local.strftime("%H:%M"),
                        "date": date_label,
                    }
                )
        except Exception:
            pass

    # Last 24 terminal runs for heatmap
    last24_runs = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == job.shop_id,
            ScrapeRun.phase == run_phase,
            ScrapeRun.status.in_(["completed", "failed"]),
        )
        .order_by(ScrapeRun.finished_at.desc().nullslast())
        .limit(24)
        .all()
    )
    last24 = [
        "ok" if r.status == "completed" else "fail" for r in reversed(last24_runs)
    ]

    # Stats: last 24h and last 30d
    from datetime import timedelta

    cutoff_24h = now - timedelta(hours=24)
    cutoff_30d = now - timedelta(days=30)
    runs_24h = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == job.shop_id,
            ScrapeRun.phase == run_phase,
            ScrapeRun.status.in_(["completed", "failed"]),
            ScrapeRun.finished_at >= cutoff_24h,
        )
        .all()
    )
    ok_24h = sum(1 for r in runs_24h if r.status == "completed")
    fail_24h = sum(1 for r in runs_24h if r.status == "failed")

    runs_30d = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == job.shop_id,
            ScrapeRun.phase == run_phase,
            ScrapeRun.status.in_(["completed", "failed"]),
            ScrapeRun.finished_at >= cutoff_30d,
        )
        .all()
    )
    total_30d = len(runs_30d)
    ok_30d = sum(1 for r in runs_30d if r.status == "completed")
    success_rate_30d = round(ok_30d / total_30d * 100, 1) if total_30d else None

    durations = [
        (r.finished_at - r.started_at).total_seconds()
        for r in runs_30d
        if r.status == "completed" and r.finished_at and r.started_at
    ]
    avg_dur_s = sum(durations) / len(durations) if durations else None

    last_run = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == job.shop_id,
            ScrapeRun.phase == run_phase,
            ScrapeRun.status.in_(["completed", "failed"]),
        )
        .order_by(ScrapeRun.finished_at.desc().nullslast())
        .limit(1)
        .one_or_none()
    )
    last_status = None
    if last_run:
        last_status = "ok" if last_run.status == "completed" else "fail"

    # Recent run history (last 20)
    recent_runs = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == job.shop_id,
            ScrapeRun.phase == run_phase,
        )
        .order_by(ScrapeRun.started_at.desc())
        .limit(20)
        .all()
    )
    runs_out = []
    for r in recent_runs:
        dur_s = None
        if r.finished_at and r.started_at:
            dur_s = (r.finished_at - r.started_at).total_seconds()
        runs_out.append(
            {
                "id": r.id,
                "started": _rel(r.started_at),
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "dur": _fmt_dur(dur_s),
                "dur_s": dur_s,
                "items": r.items_added + r.items_updated,
                "errors": r.error_count,
                "status": r.status,
            }
        )

    return {
        "id": job.id,
        "name": f"{job.shop.name}.{job.phase}.{job.strategy or 'default'}",
        "shop": job.shop.name,
        "phase": job.phase,
        "strategy": job.strategy or "",
        "cron": job.cron_expression,
        "enabled": job.enabled,
        "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
        "chain_to_id": job.chain_to_job_id,
        "upcoming": upcoming,
        "last24": last24,
        "stats": {
            "total_24h": len(runs_24h),
            "ok_24h": ok_24h,
            "fail_24h": fail_24h,
            "success_rate_30d": success_rate_30d,
            "avg_dur": _fmt_dur(avg_dur_s),
            "avg_dur_s": avg_dur_s,
            "last_status": last_status,
            "last_run_ago": _rel(last_run.finished_at) if last_run else "—",
        },
        "runs": runs_out,
    }


@router.post("/cron/{job_id}/toggle")
def api_cron_toggle(job_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    job = get_cron_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    new_enabled = not job.enabled
    toggle_cron_job(session, job_id)
    session.commit()
    return {"id": job_id, "enabled": new_enabled}


def _chain_would_create_cycle(
    session: Any, current_job_id: int | None, chain_to_id: int
) -> bool:
    """Return True if setting chain_to_id on current_job_id would create a cycle.

    Walks the chain from chain_to_id upward; returns True if current_job_id is
    ever reached. current_job_id=None means a new job (no self-reference possible).
    """
    visited: set[int] = set()
    next_id: int | None = chain_to_id
    while next_id is not None:
        if next_id == current_job_id:
            return True
        if next_id in visited:
            break  # existing cycle in data — stop walking
        visited.add(next_id)
        job = session.get(CronJob, next_id)
        if job is None:
            break
        next_id = job.chain_to_job_id
    return False


class _CronJobBody(BaseModel):
    shop: str
    phase: str
    strategy: str = ""
    cron_expression: str
    chain_to_id: int | None = None


@router.post("/cron")
def api_cron_create(
    body: _CronJobBody, session: Session = Depends(get_db)
) -> dict[str, Any]:
    shop = get_shop_by_name(session, body.shop)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    if body.phase not in ("discover", "scan"):
        raise HTTPException(
            status_code=422, detail="phase must be 'discover' or 'scan'"
        )
    if body.chain_to_id is not None:
        chain_target = get_cron_job(session, body.chain_to_id)
        if chain_target is None:
            raise HTTPException(status_code=404, detail="Chain target job not found")
        # New job has no id yet — cycle detection only needed if chain_to_id
        # transitively loops back on itself (impossible for a new job, skip).
    strategy = body.strategy.strip() or None
    job = create_cron_job(
        session,
        shop_id=shop.id,
        phase=body.phase,
        strategy=strategy,
        args="",
        cron_expression=body.cron_expression,
        chain_to_job_id=body.chain_to_id,
    )
    session.commit()
    return {
        "id": job.id,
        "name": f"{shop.name}.{job.phase}.{job.strategy or 'default'}",
    }


class _CronJobPatch(BaseModel):
    cron_expression: str | None = None
    phase: str | None = None
    strategy: str | None = None
    chain_to_id: int | None = None
    clear_chain: bool = False


@router.patch("/cron/{job_id}")
def api_cron_update(
    job_id: int, body: _CronJobPatch, session: Session = Depends(get_db)
) -> dict[str, Any]:
    job = get_cron_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    fields: dict[str, Any] = {}
    if body.cron_expression is not None:
        fields["cron_expression"] = body.cron_expression
    if body.phase is not None:
        if body.phase not in ("discover", "scan"):
            raise HTTPException(
                status_code=422, detail="phase must be 'discover' or 'scan'"
            )
        fields["phase"] = body.phase
    if body.strategy is not None:
        fields["strategy"] = body.strategy.strip() or None
    if body.chain_to_id is not None and body.clear_chain:
        raise HTTPException(
            status_code=422, detail="Provide chain_to_id or clear_chain, not both"
        )
    if body.chain_to_id is not None:
        if body.chain_to_id == job_id:
            raise HTTPException(status_code=422, detail="A job cannot chain to itself")
        chain_target = get_cron_job(session, body.chain_to_id)
        if chain_target is None:
            raise HTTPException(status_code=404, detail="Chain target job not found")
        if _chain_would_create_cycle(session, job_id, body.chain_to_id):
            raise HTTPException(status_code=422, detail="Chain would create a cycle")
        fields["chain_to_job_id"] = body.chain_to_id
    elif body.clear_chain:
        fields["chain_to_job_id"] = None
    if fields:
        update_cron_job(session, job_id, **fields)
        session.commit()
    return {"id": job_id}


@router.delete("/cron/{job_id}")
def api_cron_delete(job_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    job = get_cron_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    delete_cron_job(session, job_id)
    session.commit()
    return {"id": job_id}


# ─── Issues ──────────────────────────────────────────────────────────────────


@router.get("/issues")
def api_issues(
    state: str = "open",
    shop: str = "",
    issue_type: str = "",
    run_id: int = 0,
    url_type: str = "",
    book_type: str = "",
    severity: str = "",
    q: str = "",
    page: int = 1,
    per_page: int = 30,
    kind: str = "all",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Issues inbox. PR 2 of the scrape-failures migration: when
    `kind="all"` the response merges `validation_issues` (parser-level
    data quality) with `scrape_failures` (transport / HTTP-level events).
    `kind="validation"` or `"scrape_failure"` narrows to one source.

    Each row carries a `kind` field so the frontend can color/route per
    type. `error_reason` and `http_status` are NULL on validation rows
    and populated on scrape-failure rows.
    """
    shop_id = None
    if shop and shop != "all":
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else -1

    run_id_int = run_id if run_id > 0 else None
    url_type_filter = url_type if url_type and url_type != "all" else ""
    book_type_filter = book_type if book_type and book_type != "all" else ""
    page = max(1, page)
    per_page = max(1, min(per_page, 200))
    if kind not in ("all", "validation", "scrape_failure"):
        kind = "all"
    rows, total = get_issues_page(
        session,
        state=state,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id_int,
        severity=severity,
        url_type=url_type_filter,
        book_type=book_type_filter,
        q=q,
        page=page,
        per_page=per_page,
        kind=kind,
    )
    counts = get_validation_lifecycle_counts(
        session,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id_int,
        severity=severity,
        q=q,
    )

    issues = [
        {
            "id": r["id"],
            "kind": r.get("kind", "validation"),
            "url": r["url"],
            "field": r["field"],
            "issue": r["issue"],
            "raw_value": r["raw_value"],
            "error_reason": r.get("error_reason"),
            "http_status": r.get("http_status"),
            "scrape_run_id": r["scrape_run_id"],
            "shop_book_id": r["shop_book_id"],
            "shop_book_title": r["shop_book_title"],
            "url_type": r.get("url_type"),
            "book_type": r.get("book_type"),
            "lifecycle_state": r["lifecycle_state"],
            "severity": r["severity"],
            "added_at": r["added_at"].isoformat() if r["added_at"] else None,
            "added_ago": _rel(r["added_at"]),
            "description": ISSUE_DESCRIPTIONS.get(r["issue"], ""),
        }
        for r in rows
    ]

    pages = max(1, (total + per_page - 1) // per_page) if total else 1
    return {
        "issues": issues,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "counts": counts,
        "kind": kind,
    }


@router.get("/issues/{issue_id}")
def api_issue_detail(
    issue_id: int,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import ISSUE_DESCRIPTIONS, ISSUE_SEVERITY

    row = (
        session.query(ValidationIssue, ScrapeRun, ShopBook, Shop)
        .join(ScrapeRun, ValidationIssue.scrape_run_id == ScrapeRun.id)
        .outerjoin(ShopBook, ValidationIssue.shop_book_id == ShopBook.id)
        .outerjoin(Shop, ScrapeRun.shop_id == Shop.id)
        .filter(ValidationIssue.id == issue_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue, run, shop_book, shop = row
    return {
        "id": issue.id,
        "kind": "validation",
        "url": issue.url,
        "field": issue.field,
        "issue": issue.issue,
        "raw_value": issue.raw_value,
        "scrape_run_id": issue.scrape_run_id,
        "shop_book_id": issue.shop_book_id,
        "shop_book_title": shop_book.title if shop_book else None,
        "shop_name": shop.name if shop else None,
        "lifecycle_state": issue.lifecycle_state,
        "acknowledged_at": issue.acknowledged_at.isoformat()
        if issue.acknowledged_at
        else None,
        "severity": ISSUE_SEVERITY.get(issue.issue, "warning"),
        "added_at": run.started_at.isoformat() if run.started_at else None,
        "added_ago": _rel(run.started_at),
        "description": ISSUE_DESCRIPTIONS.get(issue.issue, ""),
    }


@router.patch("/issues/{issue_id}/lifecycle")
def api_issue_lifecycle(
    issue_id: int,
    state: str,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    allowed = {"new", "recurring", "already_seen"}
    if state not in allowed:
        raise HTTPException(status_code=400, detail=f"state must be one of {allowed}")

    issue = session.get(ValidationIssue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.lifecycle_state = state
    if state == "already_seen":
        issue.acknowledged_at = datetime.now(UTC)
    else:
        issue.acknowledged_at = None
    session.commit()
    return {"id": issue_id, "lifecycle_state": state}


# ─── Prices ──────────────────────────────────────────────────────────────────


@router.get("/prices")
def api_prices(
    days: int = 7,
    shop: str = "",
    page: int = 1,
    per_page: int = 30,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    shop_id = None
    if shop and shop != "all":
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else -1

    changes, total = get_price_changes(
        session, days=days, shop_id=shop_id, page=page, per_page=per_page
    )
    pages = max(1, (total + per_page - 1) // per_page) if total else 1
    return {
        "changes": [
            {
                "shop_book_id": c["shop_book_id"],
                "title": c["title"],
                "prev_price": float(c["prev_price"])
                if c["prev_price"] is not None
                else None,
                "new_price": float(c["new_price"])
                if c["new_price"] is not None
                else None,
                "change": float(c["change"]) if c["change"] is not None else None,
                "scraped_at": c["scraped_at"].isoformat() if c["scraped_at"] else None,
                "scraped_ago": _rel(c["scraped_at"]),
            }
            for c in changes
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "days": days,
    }
