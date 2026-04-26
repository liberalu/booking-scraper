import logging
import os
import signal
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, get_docker_client, templates
from book_scraper.dashboard.queries import (
    RUN_URL_STATUSES,
    get_recent_runs,
    get_run_changed_fields,
    get_run_detail,
    get_run_discovered_urls,
    get_run_health,
    get_run_issue_summary,
    get_run_price_changes,
    get_run_shop_books,
    get_run_url_breakdown,
    get_run_url_items,
    mark_stale_runs,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_SCRAPY = "/app/.venv/bin/scrapy"

PHASE_COMMANDS: dict[str, list[str]] = {
    "discover_sitemap": [
        _SCRAPY,
        "crawl",
        "discover",
        "-a",
        "shop=vaga",
        "-a",
        "strategy=sitemap",
    ],
    "discover_categories": [
        _SCRAPY,
        "crawl",
        "discover",
        "-a",
        "shop=vaga",
        "-a",
        "strategy=categories",
    ],
    "scan": [_SCRAPY, "crawl", "scan", "-a", "shop=vaga"],
    "rescrape": [
        _SCRAPY,
        "crawl",
        "scan",
        "-a",
        "shop=vaga",
        "-a",
        "rescrape=true",
    ],
}


@router.get("/runs")
def runs_list(request: Request, session: Session = Depends(get_db)):
    mark_stale_runs(session)
    recent_runs = get_recent_runs(session, limit=20)
    run_health = {run.id: get_run_health(run) for run in recent_runs}
    return templates.TemplateResponse(
        request,
        "runs.html",
        {
            "active_page": "runs",
            "runs": recent_runs,
            "run_health": run_health,
        },
    )


_RUN_URLS_PER_PAGE = 50


@router.get("/runs/{run_id}")
def run_detail(
    run_id: int,
    request: Request,
    url_status: str = "all",
    url_page: int = 1,
    session: Session = Depends(get_db),
):
    run = get_run_detail(session, run_id)
    if run is None:
        return HTMLResponse("Run not found", status_code=404)
    health = get_run_health(run)
    issue_summary = get_run_issue_summary(session, run_id)
    created, changed, unchanged, price_changed_ids = get_run_shop_books(session, run_id)
    changed_ids = [sb.id for sb in changed]
    field_changes = get_run_changed_fields(session, run_id, changed_ids)
    price_changes = get_run_price_changes(
        session, run_id, [i for i in changed_ids if i in price_changed_ids]
    )
    # Build {shop_book_id: [(field, old, new), ...]} — skip null→null entries
    changed_info: dict[int, list[tuple[str, str | None, str | None]]] = {}
    for sb in changed:
        entries = [
            (f, o, n)
            for f, o, n in field_changes.get(sb.id, [])
            if o is not None or n is not None
        ]
        if sb.id in price_changed_ids and sb.id in price_changes:
            old_p, new_p = price_changes[sb.id]
            entries.append(("price", old_p, new_p))
        changed_info[sb.id] = entries

    if url_status not in {"all", *RUN_URL_STATUSES}:
        url_status = "all"
    page = max(url_page, 1)

    url_breakdown = get_run_url_breakdown(session, run_id)
    has_live_items = sum(url_breakdown.values()) > 0

    if has_live_items:
        url_rows, url_total = get_run_url_items(
            session,
            run_id,
            status=url_status,
            page=page,
            per_page=_RUN_URLS_PER_PAGE,
        )
        url_source = "live"
    else:
        url_rows, url_total = get_run_discovered_urls(
            session, run_id, page=page, per_page=_RUN_URLS_PER_PAGE
        )
        url_source = "history"

    url_total_pages = max((url_total + _RUN_URLS_PER_PAGE - 1) // _RUN_URLS_PER_PAGE, 1)

    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "active_page": "runs",
            "run": run,
            "issue_summary": issue_summary,
            "health": health,
            "created": created,
            "changed": changed,
            "unchanged": unchanged,
            "changed_info": changed_info,
            "url_breakdown": url_breakdown,
            "url_rows": url_rows,
            "url_total": url_total,
            "url_page": page,
            "url_total_pages": url_total_pages,
            "url_status": url_status,
            "url_source": url_source,
            "url_statuses": list(RUN_URL_STATUSES),
        },
    )


@router.get("/api/runs/{run_id}/status")
def run_status(run_id: int, session: Session = Depends(get_db)):
    """Live status check for a run — used by HTMX polling."""
    run = get_run_detail(session, run_id)
    if run is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    health = get_run_health(run)
    elapsed = None
    if run.started_at:
        end = run.finished_at or datetime.now(UTC)
        elapsed = int((end - run.started_at).total_seconds())

    heartbeat_ago = None
    if run.last_heartbeat:
        heartbeat_ago = int((datetime.now(UTC) - run.last_heartbeat).total_seconds())

    return JSONResponse(
        {
            "id": run.id,
            "status": run.status,
            "health": health,
            "pid": run.pid,
            "urls_processed": run.urls_processed,
            "urls_total": run.urls_total,
            "items_added": run.items_added,
            "items_updated": run.items_updated,
            "error_count": run.error_count,
            "elapsed_seconds": elapsed,
            "heartbeat_seconds_ago": heartbeat_ago,
        }
    )


@router.post("/runs/trigger")
def trigger_run(request: Request, phase: str = "scan"):
    cmd = PHASE_COMMANDS.get(phase)
    if not cmd:
        return HTMLResponse(
            f'<p class="error">Unknown phase: {phase}</p>',
            status_code=400,
        )

    client = get_docker_client()
    if client is None:
        return HTMLResponse(
            '<p class="error">Docker not available</p>',
            status_code=503,
        )

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
        return HTMLResponse(
            '<p class="error">Scraper container not found</p>',
            status_code=503,
        )

    container = containers[0]
    container.exec_run(
        cmd,
        detach=True,
        workdir="/app",
        environment={
            "PYTHONPATH": "/app",
            "DATABASE_URL": "postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper",
        },
    )
    return HTMLResponse(
        f'<p class="success">Started {phase}</p>',
        status_code=200,
    )


@router.post("/runs/{run_id}/kill")
def kill_run(run_id: int, session: Session = Depends(get_db)):
    run = get_run_detail(session, run_id)
    if run is None:
        return HTMLResponse("Run not found", status_code=404)
    if run.status != "running":
        return HTMLResponse("Run is not running", status_code=400)
    if run.pid is None:
        return HTMLResponse("No PID recorded for this run", status_code=400)

    try:
        os.kill(run.pid, signal.SIGTERM)
        logger.info("Sent SIGTERM to PID %d (run #%d)", run.pid, run_id)
        return HTMLResponse(f'<p class="success">Sent SIGTERM to PID {run.pid}</p>')
    except ProcessLookupError:
        from book_scraper.db.repo import record_scrape_run_failed_issue

        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        record_scrape_run_failed_issue(session, run, "killed_pid_dead")
        session.commit()
        return HTMLResponse(f"<p>Process {run.pid} already dead. Marked as failed.</p>")
    except PermissionError:
        return HTMLResponse(
            f'<p class="error">No permission to kill PID {run.pid}</p>',
            status_code=403,
        )
