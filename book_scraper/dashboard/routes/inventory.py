from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import templates
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import get_inventory_stats

router = APIRouter()


@router.get("/inventory")
def inventory_page(request: Request, session: Session = Depends(get_db)):
    stats = get_inventory_stats(session)
    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            "active_page": "inventory",
            "stats": stats,
        },
    )
