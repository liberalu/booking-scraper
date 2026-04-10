from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import templates
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import (
    get_validation_by_type,
    get_validation_summary,
)

router = APIRouter()


@router.get("/validation")
def validation_list(request: Request, session: Session = Depends(get_db)):
    summary = get_validation_summary(session)
    return templates.TemplateResponse(
        "validation.html",
        {
            "request": request,
            "active_page": "validation",
            "summary": summary,
        },
    )


@router.get("/validation/{issue_type}")
def validation_detail(
    issue_type: str,
    request: Request,
    session: Session = Depends(get_db),
):
    issues = get_validation_by_type(session, issue_type, limit=100)
    return templates.TemplateResponse(
        "validation_detail.html",
        {
            "request": request,
            "active_page": "validation",
            "issue_type": issue_type,
            "issues": issues,
        },
    )
