import logging
import threading
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, get_docker_client, templates
from book_scraper.dashboard.queries import (
    get_all_shops,
    get_not_listed_urls,
    get_run_health,
    get_shop_by_name,
    get_shop_field_stats,
    get_shop_runs,
    get_shop_stats,
    mark_stale_runs,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_SCRAPY = "/app/.venv/bin/scrapy"

SHOP_COMMANDS = {
    "discover_sitemap": [
        _SCRAPY,
        "crawl",
        "discover",
        "-a",
        "shop={shop}",
        "-a",
        "strategy=sitemap",
    ],
    "discover_categories": [
        _SCRAPY,
        "crawl",
        "discover",
        "-a",
        "shop={shop}",
        "-a",
        "strategy=categories",
    ],
    "scan": [
        _SCRAPY,
        "crawl",
        "scan",
        "-a",
        "shop={shop}",
    ],
    "rescrape": [
        _SCRAPY,
        "crawl",
        "scan",
        "-a",
        "shop={shop}",
        "-a",
        "rescrape=true",
    ],
}


@router.get("/shops")
def shops_list(request: Request, session: Session = Depends(get_db)):
    shops = get_all_shops(session)
    shop_data = []
    for shop in shops:
        stats = get_shop_stats(session, shop.id)
        shop_data.append({"shop": shop, "stats": stats})
    return templates.TemplateResponse(
        request,
        "shops.html",
        {"active_page": "shops", "shop_data": shop_data},
    )


@router.get("/shops/{shop_name}")
def shop_detail(shop_name: str, request: Request, session: Session = Depends(get_db)):
    shop = get_shop_by_name(session, shop_name)
    if shop is None:
        return HTMLResponse("Shop not found", status_code=404)
    mark_stale_runs(session)
    stats = get_shop_stats(session, shop.id)
    field_stats = get_shop_field_stats(session, shop.id)
    runs = get_shop_runs(session, shop.id)
    run_health = {run.id: get_run_health(run) for run in runs}
    return templates.TemplateResponse(
        request,
        "shop_detail.html",
        {
            "active_page": "shops",
            "shop": shop,
            "stats": stats,
            "field_stats": field_stats,
            "runs": runs,
            "run_health": run_health,
        },
    )


def _run_exec_in_thread(container: Any, cmd: list[str], label: str) -> None:
    """Run a container exec to completion in a worker thread.

    We can't use `detach=True` on `container.exec_run` — the docker SDK
    starts the exec but the process silently dies almost immediately,
    leaving no trace (no scrape_run row, no logs). Running the exec in
    the foreground from a worker thread keeps the HTTP request snappy
    while actually letting scrapy finish.
    """
    logger.info("exec %s starting: %s", label, " ".join(cmd))
    try:
        result = container.exec_run(
            cmd,
            workdir="/app",
            environment={
                "PYTHONPATH": "/app",
                "DATABASE_URL": "postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper",
            },
        )
        logger.info(
            "exec %s finished: exit=%s tail=%r",
            label,
            result.exit_code,
            (result.output or b"").decode(errors="replace")[-500:],
        )
    except Exception:
        logger.exception("exec %s crashed", label)


@router.post("/shops/{shop_name}/run")
def trigger_shop_run(
    shop_name: str,
    phase: str = "scan",
) -> HTMLResponse:
    cmd_template = SHOP_COMMANDS.get(phase)
    if not cmd_template:
        return HTMLResponse(
            f'<p class="error">Unknown phase: {phase}</p>',
            status_code=400,
        )

    cmd = [arg.replace("{shop}", shop_name) for arg in cmd_template]

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
    # Kick the scrapy exec into a daemon thread so the HTTP request
    # returns immediately but the process actually runs. `detach=True`
    # on exec_run is broken (SDK quirk: the process silently dies);
    # BackgroundTasks would block the next request on the same worker
    # because exec_run is synchronous; a thread sidesteps both.
    t = threading.Thread(
        target=_run_exec_in_thread,
        args=(container, cmd, f"{phase}:{shop_name}"),
        daemon=True,
    )
    t.start()
    return HTMLResponse(
        f'<p class="success">Started {phase} for {shop_name} '
        '(watch progress on <a href="/runs">/runs</a>)</p>',
        status_code=200,
    )


@router.post("/shops/{shop_name}/scrape-url")
def scrape_single_url(shop_name: str, url: str = "") -> HTMLResponse:
    if not url:
        return HTMLResponse('<p class="error">No URL provided</p>', status_code=400)

    client = get_docker_client()
    if client is None:
        return HTMLResponse(
            '<p class="error">Docker not available</p>', status_code=503
        )

    containers = client.containers.list(
        filters={"label": "com.docker.compose.service=scraper"}
    )
    if not containers:
        return HTMLResponse(
            '<p class="error">Scraper container not found</p>', status_code=503
        )

    cmd = [
        _SCRAPY,
        "crawl",
        "scan",
        "-a",
        f"shop={shop_name}",
        "-a",
        f"urls={url}",
    ]
    container = containers[0]
    t = threading.Thread(
        target=_run_exec_in_thread,
        args=(container, cmd, f"scrape-url:{shop_name}"),
        daemon=True,
    )
    t.start()
    return HTMLResponse(f'<p class="success">Scraping {url}</p>')


@router.get("/shops/{shop_name}/not-listed")
def not_listed_page(
    shop_name: str,
    request: Request,
    page: int = 1,
    sort: str = "",
    order: str = "desc",
    session: Session = Depends(get_db),
) -> HTMLResponse:
    shop = get_shop_by_name(session, shop_name)
    if shop is None:
        return HTMLResponse("Shop not found", status_code=404)
    urls, total = get_not_listed_urls(
        session, shop.id, page=page, sort_by=sort, sort_order=order
    )
    total_pages = (total + 49) // 50
    return templates.TemplateResponse(
        request,
        "not_listed.html",
        {
            "active_page": "shops",
            "shop": shop,
            "urls": urls,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "sort": sort,
            "order": order,
        },
    )
