from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.responses import Response

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import get_inventory_stats

router = APIRouter()


@router.get("/inventory")
def inventory_page(request: Request, session: Session = Depends(get_db)) -> Response:
    stats = get_inventory_stats(session)
    return templates.TemplateResponse(
        request,
        "inventory.html",
        {
            "active_page": "inventory",
            "stats": stats,
        },
    )
