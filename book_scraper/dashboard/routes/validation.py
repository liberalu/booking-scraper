from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse, Response

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_price_changes,
    get_validation_by_type,
    get_validation_issues_flat,
    get_validation_lifecycle_counts,
    get_validation_summary,
)
from book_scraper.db.repo import acknowledge_validation_issue

router = APIRouter()

_VALID_STATES = {"open", "new", "recurring", "already_seen", "all"}


def _normalize_state(state: str | None) -> str:
    if state in _VALID_STATES:
        return state
    return "open"


@router.get("/validation")
def validation_list(
    request: Request,
    state: str = "open",
    page: int = 1,
    session: Session = Depends(get_db),
) -> Response:
    state = _normalize_state(state)
    summary_state = None if state == "all" else state
    summary = get_validation_summary(session, state=summary_state)
    price_changes = get_price_changes(session, days=7)
    counts = get_validation_lifecycle_counts(session)
    # For the lifecycle-specific tabs the user expects to see the
    # actual issues, not just a grouped type count. Load a flat list
    # for new/recurring/already_seen; keep the grouped view as the
    # default "Open" and "All" overviews.
    flat_issues: list[dict] = []
    flat_total = 0
    per_page = 100
    if state in {"new", "recurring", "already_seen"}:
        flat_issues, flat_total = get_validation_issues_flat(
            session, state=state, page=page, per_page=per_page
        )
    total_pages = (flat_total + per_page - 1) // per_page
    return templates.TemplateResponse(
        request,
        "validation.html",
        {
            "active_page": "issues",
            "summary": summary,
            "price_changes": price_changes,
            "lifecycle_state": state,
            "lifecycle_counts": counts,
            "flat_issues": flat_issues,
            "flat_total": flat_total,
            "flat_page": page,
            "flat_total_pages": total_pages,
        },
    )


@router.get("/validation/{issue_type}")
def validation_detail(
    issue_type: str,
    request: Request,
    state: str = "open",
    session: Session = Depends(get_db),
) -> Response:
    state = _normalize_state(state)
    detail_state = None if state == "all" else state
    issues = get_validation_by_type(
        session, issue_type, limit=100, state=detail_state
    )
    counts = get_validation_lifecycle_counts(session)
    return templates.TemplateResponse(
        request,
        "validation_detail.html",
        {
            "active_page": "issues",
            "issue_type": issue_type,
            "issues": issues,
            "lifecycle_state": state,
            "lifecycle_counts": counts,
        },
    )


@router.post("/validation-issues/{issue_id}/acknowledge")
def acknowledge_issue(
    issue_id: int,
    request: Request,
    session: Session = Depends(get_db),
) -> Response:
    if not acknowledge_validation_issue(session, issue_id):
        raise HTTPException(status_code=404, detail="Issue not found")
    session.commit()
    # Send them back to the issue-type list (Referer works; falls back
    # to the main /validation summary).
    back = request.headers.get("referer") or "/validation"
    return RedirectResponse(url=back, status_code=303)
