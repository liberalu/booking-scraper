from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import templates
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import (
    get_overview_stats,
    get_recent_runs,
    get_validation_summary,
)

router = APIRouter()


@router.get("/")
def overview(request: Request, session: Session = Depends(get_db)):
    stats = get_overview_stats(session)
    recent_runs = get_recent_runs(session, limit=5)
    validation = get_validation_summary(session)
    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "active_page": "overview",
            "stats": stats,
            "recent_runs": recent_runs,
            "validation": validation,
        },
    )
