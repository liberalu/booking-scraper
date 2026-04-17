from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import get_price_history

router = APIRouter()


@router.get("/prices")
def prices_page() -> RedirectResponse:
    """Legacy route — the Prices page was merged into /validation (Issues)."""
    return RedirectResponse(url="/validation", status_code=301)


@router.get("/api/prices/{shop_book_id}/chart")
def price_chart_data(
    shop_book_id: int, session: Session = Depends(get_db)
) -> JSONResponse:
    history = get_price_history(session, shop_book_id)
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
