from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_price_changes,
    get_price_history,
    get_shop_by_name,
    search_listings,
)

router = APIRouter()


@router.get("/prices")
def prices_page(
    request: Request,
    q: str = "",
    shop: str = "",
    sort: str = "",
    order: str = "desc",
    session: Session = Depends(get_db),
) -> Response:
    listings = search_listings(session, q) if q else []
    shop_id = None
    if shop:
        shop_obj = get_shop_by_name(session, shop)
        if shop_obj:
            shop_id = shop_obj.id
    changes = get_price_changes(session, days=7, shop_id=shop_id)

    sort_keys = {
        "title": lambda c: (c.get("title") or "").lower(),
        "prev_price": lambda c: float(c.get("prev_price") or 0),
        "new_price": lambda c: float(c.get("new_price") or 0),
        "change": lambda c: abs(float(c.get("change") or 0)),
        "scraped_at": lambda c: c.get("scraped_at") or "",
    }
    if sort in sort_keys:
        reverse = order != "asc"
        changes = sorted(changes, key=sort_keys[sort], reverse=reverse)

    return templates.TemplateResponse(
        request,
        "prices.html",
        {
            "active_page": "prices",
            "query": q,
            "shop_filter": shop,
            "listings": listings,
            "changes": changes,
            "sort": sort,
            "order": order,
        },
    )


@router.get("/api/prices/{listing_id}/chart")
def price_chart_data(
    listing_id: int, session: Session = Depends(get_db)
) -> JSONResponse:
    history = get_price_history(session, listing_id)
    labels = [p.scraped_at.isoformat() for p in history]
    prices = [float(p.price) for p in history]
    original = [float(p.price_original) if p.price_original else None for p in history]
    return JSONResponse(
        {
            "labels": labels,
            "prices": prices,
            "original_prices": original,
        }
    )
