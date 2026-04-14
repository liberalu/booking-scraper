from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.responses import Response

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_overview_stats,
    get_recent_runs,
    get_validation_summary,
)

router = APIRouter()


@router.get("/")
def overview(request: Request, session: Session = Depends(get_db)) -> Response:
    stats = get_overview_stats(session)
    recent_runs = get_recent_runs(session, limit=5)
    validation = get_validation_summary(session)
    return templates.TemplateResponse(
        request,
        "overview.html",
        {
            "active_page": "overview",
            "stats": stats,
            "recent_runs": recent_runs,
            "validation": validation,
        },
    )
