from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, get_docker_client, templates
from book_scraper.dashboard.queries import get_recent_runs, get_run_detail

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
    recent_runs = get_recent_runs(session, limit=20)
    return templates.TemplateResponse(
        request,
        "runs.html",
        {
            "active_page": "runs",
            "runs": recent_runs,
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
