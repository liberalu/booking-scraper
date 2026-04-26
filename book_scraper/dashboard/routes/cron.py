"""Dashboard routes for managing cron_jobs."""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, get_docker_client, templates
from book_scraper.db.models import Shop
from book_scraper.db.repo import (
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    list_cron_jobs,
    toggle_cron_job,
    update_cron_job,
)

router = APIRouter()


_ARGS_TOKEN_RE = re.compile(r"^-a [A-Za-z_][A-Za-z0-9_]*=\S+$")


def _validate_args(args: str) -> tuple[bool, str]:
    """Return (ok, error_message). Empty string is allowed."""
    if not args.strip():
        return True, ""
    if any(c in args for c in ";&|`$<>\n\r"):
        return False, "args contains shell metacharacters"
    tokens = args.strip().split()
    if len(tokens) % 2 != 0:
        return False, "args must be an even number of tokens (pairs of '-a key=value')"
    for i in range(0, len(tokens), 2):
        flag, pair = tokens[i], tokens[i + 1]
        if flag != "-a":
            return False, f"expected '-a' at position {i}, got {flag!r}"
        if "=" not in pair:
            return False, f"expected 'key=value', got {pair!r}"
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=\S+$", pair):
            return False, f"invalid key=value token: {pair!r}"
    return True, ""


_CRON_EXPR_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")


def _validate_cron_expression(expr: str) -> tuple[bool, str]:
    """Validate a 5-field cron expression. Very permissive — just checks shape."""
    if not expr.strip():
        return False, "cron expression is empty"
    if not _CRON_EXPR_RE.match(expr):
        return False, "cron expression must have exactly 5 whitespace-separated fields"
    return True, ""


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
) -> Response:
    ok, err = _validate_args(args)
    if not ok:
        return HTMLResponse(
            f'<p class="error">Invalid args: {err}</p>', status_code=400
        )
    ok, err = _validate_cron_expression(cron_expression)
    if not ok:
        return HTMLResponse(
            f'<p class="error">Invalid cron: {err}</p>', status_code=400
        )
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


@router.post("/cron/{job_id}/run")
def cron_run_now(job_id: int, session: Session = Depends(get_db)) -> Response:
    """Trigger an immediate run of a cron job via docker exec.

    Bypasses the enabled flag so admins can rerun disabled jobs.
    Mirrors the /runs/trigger pattern from routes/runs.py.
    """
    job = get_cron_job(session, job_id)
    if job is None:
        return HTMLResponse('<p class="error">Cron job not found</p>', status_code=404)

    # Guard: refuse if a run for this (shop, phase, strategy) is already running.
    # Prevents double-click spawning N concurrent scrapy processes that all
    # race to resume the same scrape_run.
    from book_scraper.db.models import ScrapeRun

    run_phase = (
        f"discover_{job.strategy}"
        if job.phase == "discover" and job.strategy
        else job.phase
    )
    existing = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == job.shop_id,
            ScrapeRun.phase == run_phase,
            ScrapeRun.status == "running",
        )
        .first()
    )
    if existing is not None:
        return HTMLResponse(
            f'<p class="error">A {run_phase} run for {job.shop.name} is already '
            f"running (run #{existing.id}). Wait for it to finish or kill it first.</p>",
            status_code=409,
        )

    client = get_docker_client()
    if client is None:
        return HTMLResponse(
            '<p class="error">Docker not available</p>', status_code=503
        )

    project = os.environ.get("COMPOSE_PROJECT_NAME", "book-scraper")
    containers = client.containers.list(
        filters={
            "label": [
                "com.docker.compose.service=scraper",
                f"com.docker.compose.project={project}",
            ]
        }
    )
    if not containers:
        return HTMLResponse(
            '<p class="error">Scraper container not found</p>', status_code=503
        )

    cmd = [
        "/app/.venv/bin/scrapy",
        "crawl",
        job.phase,
        "-a",
        f"shop={job.shop.name}",
    ]
    if job.strategy:
        cmd.extend(["-a", f"strategy={job.strategy}"])
    if job.args:
        cmd.extend(job.args.split())

    containers[0].exec_run(
        cmd,
        detach=True,
        workdir="/app",
        environment={
            "PYTHONPATH": "/app",
            "DATABASE_URL": "postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper",
        },
    )
    return RedirectResponse(url="/cron", status_code=303)


@router.post("/cron/{job_id}/update")
def cron_update(
    job_id: int,
    phase: str = Form(...),
    strategy: str = Form(""),
    args: str = Form(""),
    cron_expression: str = Form(...),
    session: Session = Depends(get_db),
) -> Response:
    ok, err = _validate_args(args)
    if not ok:
        return HTMLResponse(
            f'<p class="error">Invalid args: {err}</p>', status_code=400
        )
    ok, err = _validate_cron_expression(cron_expression)
    if not ok:
        return HTMLResponse(
            f'<p class="error">Invalid cron: {err}</p>', status_code=400
        )
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
