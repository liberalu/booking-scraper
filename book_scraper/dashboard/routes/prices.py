from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_price_changes,
    get_price_history,
    search_listings,
)

router = APIRouter()


@router.get("/prices")
def prices_page(
    request: Request,
    q: str = "",
    session: Session = Depends(get_db),
):
    listings = search_listings(session, q) if q else []
    changes = get_price_changes(session, days=7)
    return templates.TemplateResponse(
        request,
        "prices.html",
        {
            "active_page": "prices",
            "query": q,
            "listings": listings,
            "changes": changes,
        },
    )


@router.get("/api/prices/{listing_id}/chart")
def price_chart_data(listing_id: int, session: Session = Depends(get_db)):
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
