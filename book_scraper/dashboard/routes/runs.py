import logging
import os
import signal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, get_docker_client, templates
from book_scraper.dashboard.queries import (
    get_recent_runs,
    get_run_detail,
    get_run_health,
    mark_stale_runs,
)

logger = logging.getLogger(__name__)

router = APIRouter()

PHASE_COMMANDS: dict[str, list[str]] = {
    "discover_sitemap": [
        "scrapy",
        "crawl",
        "discover",
        "-a",
        "shop=vaga",
        "-a",
        "strategy=sitemap",
    ],
    "discover_categories": [
        "scrapy",
        "crawl",
        "discover",
        "-a",
        "shop=vaga",
        "-a",
        "strategy=categories",
    ],
    "scan": ["scrapy", "crawl", "scan", "-a", "shop=vaga"],
    "rescrape": [
        "scrapy",
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


@router.get("/runs/{run_id}")
def run_detail(run_id: int, request: Request, session: Session = Depends(get_db)):
    run, issues = get_run_detail(session, run_id)
    if run is None:
        return HTMLResponse("Run not found", status_code=404)
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "active_page": "runs",
            "run": run,
            "issues": issues,
        },
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

    containers = client.containers.list(
        filters={"label": "com.docker.compose.service=scraper"}
    )
    if not containers:
        return HTMLResponse(
            '<p class="error">Scraper container not found</p>',
            status_code=503,
        )

    container = containers[0]
    container.exec_run(cmd, detach=True)
    return HTMLResponse(
        f'<p class="success">Started {phase}</p>',
        status_code=200,
    )


@router.post("/runs/{run_id}/kill")
def kill_run(run_id: int, session: Session = Depends(get_db)):
    run, _ = get_run_detail(session, run_id)
    if run is None:
        return HTMLResponse("Run not found", status_code=404)
    if run.status != "running":
        return HTMLResponse("Run is not running", status_code=400)
    if run.pid is None:
        return HTMLResponse("No PID recorded for this run", status_code=400)

    try:
        os.kill(run.pid, signal.SIGTERM)
        logger.info("Sent SIGTERM to PID %d (run #%d)", run.pid, run_id)
        return HTMLResponse(
            f'<p class="success">Sent SIGTERM to PID {run.pid}</p>'
        )
    except ProcessLookupError:
        from datetime import UTC, datetime

        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        session.commit()
        return HTMLResponse(
            f'<p>Process {run.pid} already dead. Marked as failed.</p>'
        )
    except PermissionError:
        return HTMLResponse(
            f'<p class="error">No permission to kill PID {run.pid}</p>',
            status_code=403,
        )
