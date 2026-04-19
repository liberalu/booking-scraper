from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_all_shops,
    get_discovered_urls_page,
    get_discovered_urls_stats,
    get_shop_by_name,
    get_url_detail,
)

router = APIRouter()


@router.get("/urls")
def discovered_urls_page(
    request: Request,
    page: int = 1,
    q: str = "",
    shop: str = "",
    source: str = "",
    url_type: str = "",
    score_min: str = "",
    is_book: str = "",
    sort: str = "discovered",
    order: str = "desc",
    session: Session = Depends(get_db),
) -> HTMLResponse:
    shop_obj = get_shop_by_name(session, shop) if shop else None
    shop_id = shop_obj.id if shop_obj else None
    stats = get_discovered_urls_stats(session, shop_id=shop_id)
    try:
        score_min_int: int | None = int(score_min)
    except ValueError:
        score_min_int = None
    urls, total = get_discovered_urls_page(
        session,
        page=page,
        shop_id=shop_id,
        source=source,
        url_type=url_type,
        search=q,
        score_min=score_min_int,
        is_book=is_book,
        sort_by=sort,
        sort_order=order,
    )
    shops = get_all_shops(session)
    total_pages = (total + 49) // 50
    return templates.TemplateResponse(
        request,
        "discovered_urls.html",
        {
            "active_page": "urls",
            "urls": urls,
            "stats": stats,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "query": q,
            "shop_filter": shop,
            "source_filter": source,
            "type_filter": url_type,
            "score_min_filter": score_min,
            "is_book_filter": is_book,
            "sort": sort,
            "order": order,
            "shops": shops,
        },
    )


@router.get("/urls/{url_id}")
def url_detail_page(
    request: Request,
    url_id: int,
    session: Session = Depends(get_db),
) -> HTMLResponse:
    result = get_url_detail(session, url_id)
    if result is None:
        raise HTTPException(status_code=404, detail="URL not found")
    discovered_url, classification = result
    return templates.TemplateResponse(
        request,
        "url_detail.html",
        {
            "active_page": "urls",
            "url": discovered_url,
            "classification": classification,
        },
    )
