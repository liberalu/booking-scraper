from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse, Response

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    ISSUE_DESCRIPTIONS,
    ISSUE_SEVERITY,
    get_all_shops,
    get_issues_page,
    get_shop_by_name,
    get_validation_lifecycle_counts,
)
from book_scraper.db.repo import (
    acknowledge_validation_issue,
    acknowledge_validation_issues_bulk,
    delete_validation_issues_matching,
)

router = APIRouter()

_VALID_STATES = {"open", "new", "recurring", "already_seen", "all"}
_PER_PAGE = 50


def _normalize_state(state: str | None) -> str:
    return state if state in _VALID_STATES else "open"


def _resolve_shop_id(session: Session, shop: str) -> int | None:
    if not shop:
        return None
    obj = get_shop_by_name(session, shop)
    return obj.id if obj else None


def _filter_params(
    state: str, shop: str, issue_type: str, run_id: str, q: str, order: str
) -> str:
    """Render a query string for paginate/ack/delete links preserving filters."""
    parts: list[str] = []
    if state:
        parts.append(f"state={state}")
    if shop:
        parts.append(f"shop={shop}")
    if issue_type:
        parts.append(f"issue_type={issue_type}")
    if run_id:
        parts.append(f"run_id={run_id}")
    if q:
        parts.append(f"q={q}")
    if order:
        parts.append(f"order={order}")
    return "&".join(parts)


@router.get("/validation")
def validation_list(
    request: Request,
    state: str = "open",
    shop: str = "",
    issue_type: str = "",
    run_id: int | None = None,
    q: str = "",
    order: str = "desc",
    page: int = 1,
    session: Session = Depends(get_db),
) -> Response:
    state = _normalize_state(state)
    lifecycle_state = None if state == "all" else state
    shop_id = _resolve_shop_id(session, shop)

    rows, total = get_issues_page(
        session,
        state=lifecycle_state,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id,
        q=q,
        order=order,
        page=max(page, 1),
        per_page=_PER_PAGE,
    )
    total_pages = max((total + _PER_PAGE - 1) // _PER_PAGE, 1)
    counts = get_validation_lifecycle_counts(
        session,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id,
        q=q,
    )
    shops = get_all_shops(session)

    # All known issue types — feed the filter dropdown grouped by severity.
    critical_types = sorted(k for k, v in ISSUE_SEVERITY.items() if v == "critical")
    warning_types = sorted(k for k, v in ISSUE_SEVERITY.items() if v == "warning")

    return templates.TemplateResponse(
        request,
        "validation.html",
        {
            "active_page": "issues",
            "rows": rows,
            "total": total,
            "page": max(page, 1),
            "per_page": _PER_PAGE,
            "total_pages": total_pages,
            "lifecycle_state": state,
            "lifecycle_counts": counts,
            "shops": shops,
            "selected_shop": shop,
            "selected_issue_type": issue_type,
            "selected_run_id": run_id,
            "q": q,
            "order": order,
            "critical_types": critical_types,
            "warning_types": warning_types,
            "issue_descriptions": ISSUE_DESCRIPTIONS,
            "filter_params": _filter_params(
                state, shop, issue_type, str(run_id) if run_id else "", q, order
            ),
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
    back = request.headers.get("referer") or "/validation"
    return RedirectResponse(url=back, status_code=303)


@router.post("/validation-issues/acknowledge-all")
def acknowledge_all(
    request: Request,
    issue_type: str = Form(""),
    state: str = Form("open"),
    shop: str = Form(""),
    run_id: str = Form(""),
    q: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    state_normalized = _normalize_state(state)
    lifecycle_state = None if state_normalized == "all" else state_normalized
    shop_id = _resolve_shop_id(session, shop)
    run_id_int = int(run_id) if run_id.strip() else None

    acknowledge_validation_issues_bulk(
        session,
        issue_type=issue_type or None,
        state=lifecycle_state,
        shop_id=shop_id,
        run_id=run_id_int,
        q=q,
    )
    session.commit()
    back = request.headers.get("referer") or "/validation"
    return RedirectResponse(url=back, status_code=303)


@router.post("/validation-issues/delete-matching")
def delete_matching(
    request: Request,
    issue_type: str = Form(""),
    state: str = Form("open"),
    shop: str = Form(""),
    run_id: str = Form(""),
    q: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    state_normalized = _normalize_state(state)
    lifecycle_state = None if state_normalized == "all" else state_normalized
    shop_id = _resolve_shop_id(session, shop)
    run_id_int = int(run_id) if run_id.strip() else None

    # Delegate the "at least one filter" guard to the repo (ValueError → 400).
    try:
        delete_validation_issues_matching(
            session,
            issue_type=issue_type or None,
            state=lifecycle_state,
            shop_id=shop_id,
            run_id=run_id_int,
            q=q,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    session.commit()
    back = request.headers.get("referer") or "/validation"
    return RedirectResponse(url=back, status_code=303)
