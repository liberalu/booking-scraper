from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.responses import Response

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_price_changes,
    get_validation_by_type,
    get_validation_summary,
)

router = APIRouter()


@router.get("/validation")
def validation_list(request: Request, session: Session = Depends(get_db)) -> Response:
    summary = get_validation_summary(session)
    price_changes = get_price_changes(session, days=7)
    return templates.TemplateResponse(
        request,
        "validation.html",
        {
            "active_page": "issues",
            "summary": summary,
            "price_changes": price_changes,
        },
    )


@router.get("/validation/{issue_type}")
def validation_detail(
    issue_type: str,
    request: Request,
    session: Session = Depends(get_db),
) -> Response:
    issues = get_validation_by_type(session, issue_type, limit=100)
    return templates.TemplateResponse(
        request,
        "validation_detail.html",
        {
            "active_page": "issues",
            "issue_type": issue_type,
            "issues": issues,
        },
    )
