import logging
import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, get_docker_client, templates
from book_scraper.dashboard.queries import (
    get_recent_runs,
    get_run_health,
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
