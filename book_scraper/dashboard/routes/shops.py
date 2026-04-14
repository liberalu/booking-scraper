from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, get_docker_client, templates
from book_scraper.dashboard.queries import (
    get_all_shops,
    get_not_listed_count,
    get_not_listed_urls,
    get_run_health,
    get_shop_by_name,
    get_shop_field_stats,
    get_shop_runs,
    get_shop_stats,
    mark_stale_runs,
)

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
def shops_list(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
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
def shop_detail(
    shop_name: str,
    request: Request,
    sort: str = "",
    order: str = "desc",
    session: Session = Depends(get_db),
) -> HTMLResponse:
    shop = get_shop_by_name(session, shop_name)
    if shop is None:
        return HTMLResponse("Shop not found", status_code=404)
    mark_stale_runs(session)
    stats = get_shop_stats(session, shop.id)
    not_listed_count = get_not_listed_count(session, shop.id)
    field_stats = get_shop_field_stats(session, shop.id)
    runs = get_shop_runs(session, shop.id, sort_by=sort, sort_order=order)
    run_health = {run.id: get_run_health(run) for run in runs}
    return templates.TemplateResponse(
        request,
        "shop_detail.html",
        {
            "active_page": "shops",
            "shop": shop,
            "stats": stats,
            "not_listed_count": not_listed_count,
            "field_stats": field_stats,
            "runs": runs,
            "run_health": run_health,
            "sort": sort,
            "order": order,
        },
    )


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


@router.post("/shops/{shop_name}/run")
def trigger_shop_run(shop_name: str, phase: str = "scan") -> HTMLResponse:
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
        f'<p class="success">Started {phase} for {shop_name}</p>',
        status_code=200,
    )


@router.post("/shops/{shop_name}/scrape-url")
def scrape_single_url(shop_name: str, url: str = "") -> HTMLResponse:
    if not url:
        return HTMLResponse(
            '<p class="error">No URL provided</p>', status_code=400
        )

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
            '<p class="error">Scraper container not found</p>',
            status_code=503,
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
    container.exec_run(
        cmd,
        detach=True,
        workdir="/app",
        environment={
            "PYTHONPATH": "/app",
            "DATABASE_URL": "postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper",
        },
    )
    return HTMLResponse(f'<p class="success">Scraping {url}</p>')
