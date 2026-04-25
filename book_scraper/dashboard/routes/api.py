# book_scraper/dashboard/routes/api.py
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from book_scraper.dashboard.deps import get_db, get_docker_client
from book_scraper.dashboard.queries import (
    ISSUE_DESCRIPTIONS,
    get_all_shops,
    get_data_completeness,
    get_discovered_urls_page,
    get_discovered_urls_stats,
    get_issues_page,
    get_overview_stats,
    get_price_changes,
    get_price_history,
    get_recent_runs,
    get_run_issue_summary,
    get_scrape_activity_by_day,
    get_shop_book_changes,
    get_shop_book_issues,
    get_shop_books_page,
    get_shop_by_name,
    get_shop_field_stats,
    get_shop_runs,
    get_shop_stats,
    get_url_detail,
    get_validation_lifecycle_counts,
    get_validation_summary,
)
from book_scraper.db.models import ScrapeRun, Shop, ShopBook
from book_scraper.db.repo import get_cron_job, list_cron_jobs, toggle_cron_job

router = APIRouter()


# ─── Helpers ────────────────────────────────────────────────────────────────


def _rel(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - dt
    s = max(0, int(delta.total_seconds()))
    if s < 60:
        return "just now"
    m = s // 60
    if m < 60:
        return f"{m}m ago"
    h = m // 60
    if h < 24:
        return f"{h}h ago"
    d = h // 24
    if d < 7:
        return f"{d}d ago"
    w = d // 7
    if w < 5:
        return f"{w}w ago"
    mo = d // 30
    if mo < 12:
        return f"{mo}mo ago"
    return f"{d // 365}y ago"


def _elapsed(run: ScrapeRun) -> str:
    start = run.started_at
    end = run.finished_at or datetime.now(UTC)
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if not start:
        return "—"
    secs = max(0, int((end - start).total_seconds()))
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m" if m else f"{h}h"
    if m:
        return f"{m}m {s}s" if s else f"{m}m"
    return f"{s}s"


def _progress(run: ScrapeRun) -> int:
    if run.status == "completed":
        return 100
    if run.urls_total and run.urls_total > 0:
        return min(99, int(run.urls_processed / run.urls_total * 100))
    return 0


def _run_dict(run: ScrapeRun) -> dict[str, Any]:
    started_h = 0.0
    if run.started_at:
        start = run.started_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        started_h = (datetime.now(UTC) - start).total_seconds() / 3600
    return {
        "id": run.id,
        "shop": run.shop.name,
        "phase": run.phase,
        "status": run.status,
        "progress": _progress(run),
        "items": run.items_added + run.items_updated,
        "items_added": run.items_added,
        "items_updated": run.items_updated,
        "errors": run.error_count,
        "errors_4xx": run.errors_4xx,
        "errors_5xx": run.errors_5xx,
        "elapsed": _elapsed(run),
        "started_ago": _rel(run.started_at),
        "started": _rel(run.started_at),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "urls_total": run.urls_total,
        "urls_processed": run.urls_processed,
        "type": "full",
        "by": "—",
        "startedH": round(started_h, 2),
    }


def _book_dict(sb: ShopBook) -> dict[str, Any]:
    price_str = f"€{sb.price:.2f}" if sb.price is not None else "—"
    if sb.is_active:
        status = "active"
    elif sb.inactive_since:
        status = "out"
    else:
        status = "delisted"
    return {
        "id": sb.id,
        "title": sb.title,
        "author": sb.author or "—",
        "shop": sb.shop.name if sb.shop else "—",
        "isbn": sb.isbn,
        "price": price_str,
        "price_raw": float(sb.price) if sb.price is not None else None,
        "status": status,
        "issues": 0,
        "updated": _rel(sb.last_seen_at),
        "url": sb.url,
        "publisher": sb.publisher,
        "year": sb.year,
        "format": sb.format,
        "type": sb.type,
        "in_stock": sb.in_stock,
        "is_active": sb.is_active,
        "first_seen_at": sb.first_seen_at.isoformat() if sb.first_seen_at else None,
        "last_seen_at": sb.last_seen_at.isoformat() if sb.last_seen_at else None,
    }


def _url_dict(u: Any) -> dict[str, Any]:
    cls = getattr(u, "classification", None)
    book = getattr(u, "shop_book", None)
    return {
        "id": u.id,
        "url": u.url,
        "shop": u.shop.name if u.shop else "—",
        "url_type": u.url_type or "unknown",
        "source": u.source or "—",
        "fail_count": u.fail_count,
        "status": "error" if u.fail_count >= 3 else "ok",
        "first_seen_at": u.first_seen_at.isoformat() if u.first_seen_at else None,
        "last_seen_ago": _rel(u.last_seen_at),
        "last_scraped_ago": _rel(u.last_seen_at),
        "discovered_ago": _rel(u.first_seen_at),
        "book_title": book.title if book else "—",
        "book_id": book.id if book else None,
        "book_score": cls.book_score if cls else None,
        "is_book": cls.is_book_product if cls else None,
    }


# ─── Overview ───────────────────────────────────────────────────────────────


@router.get("/overview")
def api_overview(session: Session = Depends(get_db)) -> dict[str, Any]:
    stats = get_overview_stats(session)
    completeness = get_data_completeness(session)
    recent_runs = get_recent_runs(session, limit=10)
    issue_clusters = get_validation_summary(session, state="open")
    shops = get_all_shops(session)
    activity = get_scrape_activity_by_day(session, days=14)

    open_issues = sum(c["count"] for c in issue_clusters)

    shop_cards = []
    for s in shops:
        s_stats = get_shop_stats(session, s.id)
        last = get_shop_runs(session, s.id, limit=1)
        last_run = last[0] if last else None
        shop_cards.append(
            {
                "name": s.name,
                "books": s_stats["shop_books"],
                "active": s_stats["active"],
                "issues": 0,
                "last_run_ago": _rel(last_run.started_at if last_run else None),
                "last_run_status": last_run.status if last_run else "—",
            }
        )

    return {
        "stats": {**stats, "open_issues": open_issues},
        "completeness": [{"field": c["field"], "pct": c["pct"]} for c in completeness],
        "recent_runs": [_run_dict(r) for r in recent_runs],
        "issue_clusters": issue_clusters[:6],
        "shops": shop_cards,
        "activity": activity,
    }


# ─── Runs ────────────────────────────────────────────────────────────────────


_WHEN_BOUNDS_HOURS = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}


@router.get("/runs")
def api_runs(
    shop: str = "all",
    phase: str = "all",
    status: str = "all",
    when: str = "any",
    q: str = "",
    limit: int = 50,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from datetime import timedelta

    from sqlalchemy import or_

    query = (
        session.query(ScrapeRun)
        .join(Shop, ScrapeRun.shop_id == Shop.id)
        .options(joinedload(ScrapeRun.shop))
        .order_by(ScrapeRun.started_at.desc())
    )
    if shop and shop != "all":
        query = query.filter(Shop.name == shop)
    if phase and phase != "all":
        if phase == "discover":
            # 'discover' matches discover_sitemap / _categories / _full_crawl too.
            query = query.filter(
                or_(
                    ScrapeRun.phase == "discover",
                    ScrapeRun.phase.like("discover\\_%"),
                )
            )
        else:
            query = query.filter(ScrapeRun.phase == phase)
    if status and status != "all":
        query = query.filter(ScrapeRun.status == status)
    if when in _WHEN_BOUNDS_HOURS:
        cutoff = datetime.now(UTC) - timedelta(hours=_WHEN_BOUNDS_HOURS[when])
        query = query.filter(ScrapeRun.started_at >= cutoff)
    if q.strip():
        token = q.strip()
        like = f"%{token}%"
        clauses = [Shop.name.ilike(like), ScrapeRun.phase.ilike(like)]
        if token.isdigit():
            clauses.append(ScrapeRun.id == int(token))
        query = query.filter(or_(*clauses))

    total = query.count()
    runs = query.limit(limit).all()

    running_now = (
        session.query(func.count(ScrapeRun.id))
        .filter(ScrapeRun.status == "running")
        .scalar()
        or 0
    )
    today_cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today_total = (
        session.query(func.count(ScrapeRun.id))
        .filter(ScrapeRun.started_at >= today_cutoff)
        .scalar()
        or 0
    )
    today_ok = (
        session.query(func.count(ScrapeRun.id))
        .filter(ScrapeRun.started_at >= today_cutoff, ScrapeRun.status == "completed")
        .scalar()
        or 0
    )
    today_failed = (
        session.query(func.count(ScrapeRun.id))
        .filter(ScrapeRun.started_at >= today_cutoff, ScrapeRun.status == "failed")
        .scalar()
        or 0
    )

    return {
        "runs": [_run_dict(r) for r in runs],
        "total": total,
        "limit": limit,
        "kpis": {
            "running_now": running_now,
            "today_total": today_total,
            "today_ok": today_ok,
            "today_failed": today_failed,
            "all_time": total,
        },
    }


class NewRunRequest(BaseModel):
    shop: str
    phase: str = "scan"  # "scan" | "discover"
    strategy: str = ""  # for discover: "sitemap" | "categories" | "full_crawl"
    mode: str = "delta"  # for scan: "full" | "delta" | "sample"


@router.post("/runs")
def api_create_run(
    req: NewRunRequest, session: Session = Depends(get_db)
) -> dict[str, Any]:
    """Trigger a scrape via docker exec into the scraper container."""
    shop = get_shop_by_name(session, req.shop)
    if not shop:
        raise HTTPException(status_code=404, detail=f"Unknown shop: {req.shop}")

    if req.phase not in ("scan", "discover"):
        raise HTTPException(status_code=400, detail=f"Unknown phase: {req.phase}")

    run_phase = (
        f"discover_{req.strategy}"
        if req.phase == "discover" and req.strategy
        else req.phase
    )
    existing = (
        session.query(ScrapeRun)
        .filter(
            ScrapeRun.shop_id == shop.id,
            ScrapeRun.phase == run_phase,
            ScrapeRun.status == "running",
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A {run_phase} run for {shop.name} is already running "
                f"(run #{existing.id})."
            ),
        )

    client = get_docker_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Docker not available")

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
        raise HTTPException(status_code=503, detail="Scraper container not found")

    cmd = [
        "/app/.venv/bin/scrapy",
        "crawl",
        req.phase,
        "-a",
        f"shop={req.shop}",
    ]
    if req.phase == "discover" and req.strategy:
        cmd.extend(["-a", f"strategy={req.strategy}"])
    if req.phase == "scan":
        if req.mode == "full":
            cmd.extend(["-a", "rescrape=true"])
        elif req.mode == "sample":
            cmd.extend(["-a", "max_urls=10"])

    containers[0].exec_run(
        cmd,
        detach=True,
        workdir="/app",
        environment={
            "PYTHONPATH": "/app",
            "DATABASE_URL": "postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper",
        },
    )
    return {
        "status": "started",
        "shop": req.shop,
        "phase": req.phase,
        "strategy": req.strategy,
        "mode": req.mode,
    }


@router.get("/runs/{run_id}")
def api_run_detail(run_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    run = (
        session.query(ScrapeRun)
        .options(joinedload(ScrapeRun.shop))
        .filter(ScrapeRun.id == run_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    issues = get_run_issue_summary(session, run_id)
    return {**_run_dict(run), "issues": issues}


# ─── Shop Books ──────────────────────────────────────────────────────────────


@router.get("/shop-books")
def api_shop_books(
    page: int = 1,
    per_page: int = 50,
    search: str = "",
    shop: str = "",
    active: str = "",
    missing_field: str = "",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    shop_id = None
    if shop:
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else None

    books, total = get_shop_books_page(
        session,
        page=page,
        per_page=per_page,
        search=search,
        shop_id=shop_id,
        active_filter=active,
        missing_field=missing_field,
    )

    total_books = session.query(func.count(ShopBook.id)).scalar() or 0
    active_books = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.is_active.is_(True))
        .scalar()
        or 0
    )
    missing_isbn = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.isbn.is_(None))
        .scalar()
        or 0
    )
    missing_price = (
        session.query(func.count(ShopBook.id))
        .filter(ShopBook.price.is_(None))
        .scalar()
        or 0
    )

    return {
        "books": [_book_dict(b) for b in books],
        "total": total,
        "page": page,
        "per_page": per_page,
        "kpis": {
            "total": total_books,
            "active": active_books,
            "missing_isbn": missing_isbn,
            "missing_price": missing_price,
        },
    }


@router.get("/shop-books/{book_id}")
def api_shop_book_detail(
    book_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
    sb = (
        session.query(ShopBook)
        .options(joinedload(ShopBook.shop))
        .filter(ShopBook.id == book_id)
        .first()
    )
    if not sb:
        raise HTTPException(status_code=404, detail="Book not found")

    issues = get_shop_book_issues(session, book_id)
    prices = get_price_history(session, book_id)
    changes = get_shop_book_changes(session, book_id, limit=20)

    price_history = [
        {
            "scraped_at": p.scraped_at.isoformat(),
            "price": float(p.price) if p.price is not None else None,
            "in_stock": p.in_stock,
        }
        for p in prices
    ]
    change_list = [
        {
            "field": c.field,
            "old_value": c.old_value,
            "new_value": c.new_value,
            "changed_at": c.changed_at.isoformat() if c.changed_at else None,
        }
        for c in changes
    ]

    d = _book_dict(sb)
    d["issues"] = len(issues)
    d["issues_list"] = issues
    d["price_history"] = price_history
    d["changes"] = change_list
    d["description"] = sb.description
    d["image_url"] = sb.image_url
    d["categories"] = sb.categories or []
    return d


# ─── URLs ────────────────────────────────────────────────────────────────────


@router.get("/urls")
def api_urls(
    page: int = 1,
    per_page: int = 50,
    shop: str = "",
    url_type: str = "",
    search: str = "",
    is_book: str = "",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    shop_id = None
    if shop:
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else None

    urls, total = get_discovered_urls_page(
        session,
        page=page,
        per_page=per_page,
        shop_id=shop_id,
        url_type=url_type,
        search=search,
        is_book=is_book,
    )
    stats = get_discovered_urls_stats(session, shop_id=shop_id)

    return {
        "urls": [_url_dict(u) for u in urls],
        "total": total,
        "page": page,
        "per_page": per_page,
        "stats": stats,
    }


@router.get("/urls/{url_id}")
def api_url_detail(url_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    result = get_url_detail(session, url_id)
    if result is None:
        raise HTTPException(status_code=404, detail="URL not found")
    url, cls = result
    d = _url_dict(url)
    if cls:
        d["classification"] = {
            "book_score": cls.book_score,
            "is_book_product": cls.is_book_product,
            "reasons": cls.reasons if hasattr(cls, "reasons") else [],
        }
    return d


# ─── Shops ───────────────────────────────────────────────────────────────────


@router.get("/shops")
def api_shops(session: Session = Depends(get_db)) -> dict[str, Any]:
    shops = get_all_shops(session)
    result = []
    for s in shops:
        stats = get_shop_stats(session, s.id)
        runs = get_shop_runs(session, s.id, limit=1)
        last = runs[0] if runs else None
        result.append(
            {
                "id": s.id,
                "name": s.name,
                "base_url": s.base_url,
                "books": stats["shop_books"],
                "active": stats["active"],
                "discovered_urls": stats["discovered_urls"],
                "prices": stats["prices"],
                "last_run_ago": _rel(last.started_at if last else None),
                "last_run_status": last.status if last else "—",
            }
        )
    return {"shops": result}


@router.get("/shops/{shop_name}")
def api_shop_detail(
    shop_name: str, session: Session = Depends(get_db)
) -> dict[str, Any]:
    shop = get_shop_by_name(session, shop_name)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    stats = get_shop_stats(session, shop.id)
    field_stats = get_shop_field_stats(session, shop.id)
    runs = get_shop_runs(session, shop.id, limit=20)
    last_run = runs[0] if runs else None
    return {
        "id": shop.id,
        "name": shop.name,
        "base_url": shop.base_url,
        **stats,
        "books": stats["shop_books"],
        "last_run_ago": _rel(last_run.started_at if last_run else None),
        "last_run_status": last_run.status if last_run else "—",
        "field_stats": field_stats,
        "recent_runs": [_run_dict(r) for r in runs],
    }


# ─── Cron ────────────────────────────────────────────────────────────────────


@router.get("/cron")
def api_cron(session: Session = Depends(get_db)) -> dict[str, Any]:
    jobs = list_cron_jobs(session)
    result = []
    for j in jobs:
        result.append(
            {
                "id": j.id,
                "name": f"{j.shop.name}.{j.phase}.{j.strategy or 'default'}",
                "shop": j.shop.name,
                "phase": j.phase,
                "strategy": j.strategy or "",
                "args": j.args or "",
                "cron": j.cron_expression,
                "enabled": j.enabled,
                "last": _rel(j.last_run_at),
                "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
                "last_status": "ok",
            }
        )
    return {"jobs": result}


@router.post("/cron/{job_id}/toggle")
def api_cron_toggle(
    job_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
    job = get_cron_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    new_enabled = not job.enabled
    toggle_cron_job(session, job_id)
    session.commit()
    return {"id": job_id, "enabled": new_enabled}


# ─── Issues ──────────────────────────────────────────────────────────────────


@router.get("/issues")
def api_issues(
    state: str = "open",
    shop: str = "",
    issue_type: str = "",
    severity: str = "",
    q: str = "",
    page: int = 1,
    per_page: int = 50,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    shop_id = None
    if shop:
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else None

    rows, total = get_issues_page(
        session,
        state=state,
        shop_id=shop_id,
        issue_type=issue_type,
        severity=severity,
        q=q,
        page=page,
        per_page=per_page,
    )
    counts = get_validation_lifecycle_counts(
        session, shop_id=shop_id, issue_type=issue_type, severity=severity, q=q
    )

    issues = [
        {
            "id": r["id"],
            "url": r["url"],
            "field": r["field"],
            "issue": r["issue"],
            "raw_value": r["raw_value"],
            "scrape_run_id": r["scrape_run_id"],
            "shop_book_id": r["shop_book_id"],
            "shop_book_title": r["shop_book_title"],
            "lifecycle_state": r["lifecycle_state"],
            "severity": r["severity"],
            "added_at": r["added_at"].isoformat() if r["added_at"] else None,
            "added_ago": _rel(r["added_at"]),
            "description": ISSUE_DESCRIPTIONS.get(r["issue"], ""),
        }
        for r in rows
    ]

    return {
        "issues": issues,
        "total": total,
        "page": page,
        "per_page": per_page,
        "counts": counts,
    }


# ─── Prices ──────────────────────────────────────────────────────────────────


@router.get("/prices")
def api_prices(
    days: int = 7,
    shop: str = "",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    shop_id = None
    if shop:
        s = get_shop_by_name(session, shop)
        shop_id = s.id if s else None

    changes = get_price_changes(session, days=days, shop_id=shop_id)
    return {
        "changes": [
            {
                "shop_book_id": c["shop_book_id"],
                "title": c["title"],
                "prev_price": float(c["prev_price"])
                if c["prev_price"] is not None
                else None,
                "new_price": float(c["new_price"])
                if c["new_price"] is not None
                else None,
                "change": float(c["change"]) if c["change"] is not None else None,
                "scraped_at": c["scraped_at"].isoformat() if c["scraped_at"] else None,
                "scraped_ago": _rel(c["scraped_at"]),
            }
            for c in changes
        ],
        "days": days,
    }
