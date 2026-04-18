from urllib.parse import urlencode, urlparse

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


def _safe_back(request: Request) -> str:
    """Return the Referer only if it points at the same host; fall back to /validation.

    Prevents an attacker-controlled Referer header from redirecting the user
    off-site after a form POST.
    """
    ref = request.headers.get("referer") or ""
    if not ref:
        return "/validation"
    parsed = urlparse(ref)
    if parsed.netloc and parsed.netloc != request.url.netloc:
        return "/validation"
    # Reconstruct path + query only (drop scheme/netloc/fragment).
    path = parsed.path or "/validation"
    return f"{path}?{parsed.query}" if parsed.query else path


def _filter_params(
    state: str,
    shop: str,
    issue_type: str,
    run_id: str,
    q: str,
    order: str,
    severity: str = "",
) -> str:
    """Render a query string for paginate/ack/delete links preserving filters.

    Values are URL-encoded so `q` / `shop` / `issue_type` with special chars
    (spaces, `&`, `=`, `#`) don't break pagination links.
    """
    params: dict[str, str] = {}
    if state:
        params["state"] = state
    if shop:
        params["shop"] = shop
    if issue_type:
        params["issue_type"] = issue_type
    if run_id:
        params["run_id"] = run_id
    if q:
        params["q"] = q
    if order:
        params["order"] = order
    if severity:
        params["severity"] = severity
    return urlencode(params)


@router.get("/validation")
def validation_list(
    request: Request,
    state: str = "open",
    shop: str = "",
    issue_type: str = "",
    run_id: str = "",
    q: str = "",
    order: str = "desc",
    severity: str = "",
    page: int = 1,
    session: Session = Depends(get_db),
) -> Response:
    state = _normalize_state(state)
    lifecycle_state = None if state == "all" else state
    shop_id = _resolve_shop_id(session, shop)
    run_id_int: int | None = int(run_id) if run_id.strip().isdigit() else None

    rows, total = get_issues_page(
        session,
        state=lifecycle_state,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id_int,
        q=q,
        severity=severity,
        order=order,
        page=max(page, 1),
        per_page=_PER_PAGE,
    )
    total_pages = max((total + _PER_PAGE - 1) // _PER_PAGE, 1)
    counts = get_validation_lifecycle_counts(
        session,
        shop_id=shop_id,
        issue_type=issue_type,
        run_id=run_id_int,
        q=q,
        severity=severity,
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
            "selected_run_id": run_id_int,
            "q": q,
            "order": order,
            "critical_types": critical_types,
            "warning_types": warning_types,
            "issue_descriptions": ISSUE_DESCRIPTIONS,
            "selected_severity": severity,
            "filter_params": _filter_params(
                state,
                shop,
                issue_type,
                str(run_id_int) if run_id_int else "",
                q,
                order,
                severity,
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
    return RedirectResponse(url=_safe_back(request), status_code=303)


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
    return RedirectResponse(url=_safe_back(request), status_code=303)


@router.post("/validation-issues/acknowledge-selected")
def acknowledge_selected(
    request: Request,
    ids: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    id_list = [int(i) for i in ids.split(",") if i.strip().isdigit()]
    if id_list:
        from book_scraper.db.repo import acknowledge_validation_issue

        for issue_id in id_list:
            acknowledge_validation_issue(session, issue_id)
        session.commit()
    return RedirectResponse(url=_safe_back(request), status_code=303)


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
    return RedirectResponse(url=_safe_back(request), status_code=303)
