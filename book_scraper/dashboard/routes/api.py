# book_scraper/dashboard/routes/api.py
from __future__ import annotations

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
from book_scraper.db.models import ScrapeRun, ScrapeUrlItem, Shop, ShopBook
from book_scraper.db.repo import get_cron_job, list_cron_jobs, toggle_cron_job

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
    processed = (
        terminal_count if terminal_count is not None else run.urls_processed
    )
    return min(99, int(processed / run.urls_total * 100))


def _run_terminal_counts(
    session: Session, run_ids: list[int]
) -> dict[int, int]:
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


def _run_dict(
    run: ScrapeRun, terminal_count: int | None = None
) -> dict[str, Any]:
    started_h = 0.0
    if run.started_at:
        start = run.started_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        started_h = (datetime.now(UTC) - start).total_seconds() / 3600
    return {
        "id": run.id,
        "shop": run.shop.name,
        "phase": run.phase,
        "status": run.status,
        "progress": _progress(run, terminal_count),
        "items": run.items_added + run.items_updated,
        "items_added": run.items_added,
        "items_updated": run.items_updated,
        "errors": run.error_count,
        "errors_4xx": run.errors_4xx,
        "errors_5xx": run.errors_5xx,
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
        # Why the run terminated. Populated for runs finalized after
        # the close_reason column was added; legacy runs return null.
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
            clauses.append(ScrapeRun.id == int(token))
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
    today_cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
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
    terminal = _run_terminal_counts(session, [r.id for r in runs])
    return {
        "runs": [_run_dict(r, terminal_count=terminal.get(r.id)) for r in runs],
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
    phase: str = "scan"  # "scan" | "discover"
    strategy: str = ""  # for discover: "sitemap" | "categories" | "full_crawl"
    mode: str = "delta"  # for scan: "full" | "delta" | "sample"


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
        if mode == "full":
            cmd.extend(["-a", "rescrape=true"])
        elif mode == "sample":
            cmd.extend(["-a", "max_urls=10"])

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
    if req.phase not in ("scan", "discover"):
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
        phase=req.phase, shop=req.shop, strategy=req.strategy, mode=req.mode
    )
    return {
        "status": "started",
        "shop": req.shop,
        "phase": req.phase,
        "strategy": req.strategy,
        "mode": req.mode,
    }


@router.post("/runs/{run_id}/stop")
def api_stop_run(
    run_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
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
        session.commit()
    return {"run_id": run_id, "status": run.status}


@router.post("/runs/{run_id}/pause")
def api_pause_run(
    run_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
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
        session.commit()
    return {"run_id": run_id, "status": run.status}


@router.post("/runs/{run_id}/resume")
def api_resume_run(
    run_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
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
        session.commit()
    return {"run_id": run_id, "status": run.status}


@router.post("/runs/{run_id}/rerun")
def api_rerun_run(
    run_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
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
def api_continue_run(
    run_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
    """Resume an operator-stopped scan run on the same `scrape_runs` row.

    Flips a stopped scan back from 'failed' → 'running', then spawns a
    fresh scrapy subprocess. The spider's `find_resumable_run` matches
    Case A (running + has pending items) and reuses this same row, so
    no new run id is created. Atomic against concurrent /continue calls
    via row-level locking; rolls the row back to its prior terminal
    state if the subprocess can't be spawned.
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
            detail=(
                f"Only operator-stopped runs can be continued; "
                f"status={run.status!r}"
            ),
        )
    if run.phase != "scan":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Continue is only supported for scan runs; phase={run.phase!r}"
            ),
        )
    if get_run_close_reason(session, run) != "stopped_by_operator":
        raise HTTPException(
            status_code=400,
            detail="Only runs stopped by the operator can be continued.",
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
    session.commit()

    try:
        _spawn_scrapy_in_container(
            phase="scan", shop=shop_name, strategy="", mode="delta"
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
    base = _run_dict(run, terminal_count=terminal)
    base.update(item_counts)
    base["items"] = item_counts["items_added"] + item_counts["items_updated"]
    return {**base, "issues": issues, "close_reason": close_reason}


@router.get("/runs/{run_id}/live")
def api_run_live(run_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
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
    failure_groups = get_run_failure_groups(session, run_id)
    recent_activity = get_run_recent_activity(session, run_id, limit=20)

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
    }


@router.get("/runs/{run_id}/urls")
def api_run_urls(
    run_id: int,
    status: str = "all",
    page: int = 1,
    per_page: int = 50,
    sort: str = "started",
    order: str = "desc",
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
        )
        rows = []
        for it, title in items:
            duration_ms: int | None = None
            if it.claimed_at and it.done_at:
                duration_ms = int(
                    (it.done_at - it.claimed_at).total_seconds() * 1000
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
                    "error_reason": it.error_reason,
                    "duration_ms": duration_ms,
                    "request_delay_s": it.request_delay_s,
                    "delay_source": it.delay_source,
                    "item_id": it.id,
                    "discovered_url_id": it.discovered_url_id,
                }
            )
        source = "live"
    else:
        # Discover-run history fallback (last_seen_run_id). Scan runs always
        # have live rows now (cleanup_scrape_url_items was removed).
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
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.isbn.is_(None))
        .scalar()
        or 0
    )
    missing_price = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.price.is_(None))
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

    d = _book_dict(sb)
    d["issues"] = len(issues)
    d["issues_list"] = issues
    d["price_history"] = price_history
    d["changes"] = change_list
    d["description"] = sb.description
    d["image_url"] = sb.image_url
    d["categories"] = sb.categories or []
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
    return d


# ─── Shops ───────────────────────────────────────────────────────────────────


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
        "recent_runs": [
            _run_dict(r, terminal_count=terminal.get(r.id)) for r in runs
        ],
        "rate_settings": rate_settings,
    }


# ─── Cron ────────────────────────────────────────────────────────────────────


@router.get("/cron")
def api_cron(session: Session = Depends(get_db)) -> dict[str, Any]:
    jobs = list_cron_jobs(session)
    result = []
    for j in jobs:
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
                "last_status": "ok",
            }
        )
    return {"jobs": result}


@router.post("/cron/{job_id}/toggle")
def api_cron_toggle(
    job_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
    job = get_cron_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    new_enabled = not job.enabled
    toggle_cron_job(session, job_id)
    session.commit()
    return {"id": job_id, "enabled": new_enabled}


# ─── Issues ──────────────────────────────────────────────────────────────────


@router.get("/issues")
def api_issues(
    state: str = "open",
    shop: str = "",
    issue_type: str = "",
    run_id: int = 0,
    severity: str = "",
    q: str = "",
    page: int = 1,
    per_page: int = 30,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    shop_id = None
    if shop and shop != "all":
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else -1

    run_id_int = run_id if run_id > 0 else None
    page = max(1, page)
    per_page = max(1, min(per_page, 200))
    rows, total = get_issues_page(
        session,
        state=state,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id_int,
        severity=severity,
        q=q,
        page=page,
        per_page=per_page,
    )
    counts = get_validation_lifecycle_counts(
        session, shop_id=shop_id, issue_type=issue_type, run_id=run_id_int, severity=severity, q=q
    )

    issues = [
        {
            "id": r["id"],
            "url": r["url"],
            "field": r["field"],
            "issue": r["issue"],
            "raw_value": r["raw_value"],
            "scrape_run_id": r["scrape_run_id"],
            "shop_book_id": r["shop_book_id"],
            "shop_book_title": r["shop_book_title"],
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
    }


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
