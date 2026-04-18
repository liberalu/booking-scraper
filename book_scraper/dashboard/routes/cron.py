"""Dashboard routes for managing cron_jobs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.db.models import Shop
from book_scraper.db.repo import (
    create_cron_job,
    delete_cron_job,
    list_cron_jobs,
    toggle_cron_job,
    update_cron_job,
)

router = APIRouter()


@router.get("/cron")
def cron_index(request: Request, session: Session = Depends(get_db)) -> Response:
    jobs = list_cron_jobs(session)
    jobs_ctx = [
        {
            "id": j.id,
            "shop_name": j.shop.name,
            "shop_id": j.shop_id,
            "phase": j.phase,
            "strategy": j.strategy or "",
            "args": j.args,
            "cron_expression": j.cron_expression,
            "enabled": j.enabled,
            "last_run_at": j.last_run_at,
        }
        for j in jobs
    ]
    shops = list(session.execute(select(Shop).order_by(Shop.name)).scalars().all())
    shop_options = [{"id": s.id, "name": s.name} for s in shops]

    return templates.TemplateResponse(
        request,
        "cron.html",
        {"jobs": jobs_ctx, "shops": shop_options, "active_page": "cron"},
    )


@router.post("/cron")
def cron_create(
    shop_id: int = Form(...),
    phase: str = Form(...),
    strategy: str = Form(""),
    args: str = Form(""),
    cron_expression: str = Form(...),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    create_cron_job(
        session,
        shop_id=shop_id,
        phase=phase,
        strategy=strategy or None,
        args=args,
        cron_expression=cron_expression,
        enabled=True,
    )
    session.commit()
    return RedirectResponse(url="/cron", status_code=303)


@router.post("/cron/{job_id}/toggle")
def cron_toggle(job_id: int, session: Session = Depends(get_db)) -> RedirectResponse:
    toggle_cron_job(session, job_id)
    session.commit()
    return RedirectResponse(url="/cron", status_code=303)


@router.post("/cron/{job_id}/delete")
def cron_delete(job_id: int, session: Session = Depends(get_db)) -> RedirectResponse:
    delete_cron_job(session, job_id)
    session.commit()
    return RedirectResponse(url="/cron", status_code=303)


@router.post("/cron/{job_id}/update")
def cron_update(
    job_id: int,
    phase: str = Form(...),
    strategy: str = Form(""),
    args: str = Form(""),
    cron_expression: str = Form(...),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    update_cron_job(
        session,
        job_id,
        phase=phase,
        strategy=strategy or None,
        args=args,
        cron_expression=cron_expression,
    )
    session.commit()
    return RedirectResponse(url="/cron", status_code=303)
