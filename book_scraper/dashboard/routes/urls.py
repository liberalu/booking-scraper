from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_all_shops,
    get_discovered_urls_page,
    get_discovered_urls_stats,
    get_shop_by_name,
)

router = APIRouter()


@router.get("/urls")
def discovered_urls_page(
    request: Request,
    page: int = 1,
    q: str = "",
    shop: str = "",
    source: str = "",
    status: str = "",
    sort: str = "discovered",
    order: str = "desc",
    session: Session = Depends(get_db),
):
    shop_obj = get_shop_by_name(session, shop) if shop else None
    shop_id = shop_obj.id if shop_obj else None
    stats = get_discovered_urls_stats(session, shop_id=shop_id)
    urls, total = get_discovered_urls_page(
        session, page=page, shop_id=shop_id, source=source,
        status=status, search=q, sort_by=sort, sort_order=order,
    )
    shops = get_all_shops(session)
    total_pages = (total + 49) // 50
    return templates.TemplateResponse(
        request, "discovered_urls.html",
        {
            "active_page": "urls", "urls": urls, "stats": stats,
            "total": total, "page": page, "total_pages": total_pages,
            "query": q, "shop_filter": shop, "source_filter": source,
            "status_filter": status, "sort": sort, "order": order, "shops": shops,
        },
    )
