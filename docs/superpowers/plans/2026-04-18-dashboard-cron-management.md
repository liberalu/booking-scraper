# Dashboard Cron Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `cron/scraper-crontab` file with a DB-backed `cron_jobs` table that the scraper entrypoint reads on boot, plus a dashboard UI to view / create / toggle / delete jobs and a "Run now" button that triggers runs via `docker exec`.

**Architecture:** Three layers:
1. **Persistence** — `cron_jobs` table storing (shop, phase, strategy, args, cron_expression, enabled, last_run_at). Seeded with the two current jobs (daily sitemap discover at 2am, daily scan at 3am).
2. **Scheduling** — scraper entrypoint runs a `generate_crontab.py` script on boot that queries `cron_jobs WHERE enabled=true` and writes crontab lines. The legacy static crontab file is removed.
3. **UI** — `/cron` dashboard page with list view, add/edit form, toggle/delete buttons, and a "Run now" button that calls `POST /cron/{id}/run` which executes `docker exec scraper <scrapy command>` in detached mode. Requires mounting the Docker socket into the dashboard container.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, SQLAlchemy 2.0, Alembic, Docker Compose. Tests: pytest with real PostgreSQL (port 5433).

---

## File Structure

**Modified:**
- `alembic/versions/<new>_add_cron_jobs_table.py` — new migration with a seed for the 2 existing jobs
- `book_scraper/db/models.py` — new `CronJob` model
- `book_scraper/db/repo.py` — CRUD helpers: `list_cron_jobs`, `get_cron_job`, `create_cron_job`, `update_cron_job`, `delete_cron_job`, `toggle_cron_job`, `update_cron_job_last_run`
- `scripts/generate_crontab.py` — new script; reads cron_jobs table, writes `/tmp/crontab-generated`, `crontab`s it
- `scripts/entrypoint-scraper.sh` — calls `generate_crontab.py` instead of the static file
- `cron/scraper-crontab` — **deleted** (replaced by DB-driven generation)
- `Dockerfile` — remove the `COPY cron/scraper-crontab` line, ensure `generate_crontab.py` is in the scraper image
- `docker-compose.yml` — mount `/var/run/docker.sock:/var/run/docker.sock` into dashboard service for "Run now"
- `book_scraper/dashboard/routes/cron.py` — new routes for cron CRUD + run now
- `book_scraper/dashboard/templates/cron.html` — new list/form template
- `book_scraper/dashboard/templates/base.html` — add "Cron" nav link
- `book_scraper/dashboard/app.py` — register the new router

**Created tests:**
- `tests/integration/test_cron_jobs_repo.py` — CRUD tests
- `tests/integration/test_cron_routes.py` — HTTP route tests (FastAPI TestClient)
- `tests/unit/test_generate_crontab.py` — unit test of crontab generation from a list of job rows

---

## Task 1: `cron_jobs` table + model + CRUD

**Files:**
- Create: `alembic/versions/<timestamp>_add_cron_jobs_table.py`
- Modify: `book_scraper/db/models.py` (add `CronJob`)
- Modify: `book_scraper/db/repo.py` (CRUD helpers)
- Create: `tests/integration/test_cron_jobs_repo.py`

### Step 1 — Write failing CRUD tests

Create `tests/integration/test_cron_jobs_repo.py`:

```python
"""CRUD helpers for cron_jobs."""

from book_scraper.db.repo import (
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    list_cron_jobs,
    toggle_cron_job,
    update_cron_job,
    update_cron_job_last_run,
    upsert_shop,
)


def test_create_and_list_cron_job(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="discover",
        strategy="sitemap",
        args="",
        cron_expression="0 2 * * *",
        enabled=True,
    )
    db_session.commit()

    jobs = list_cron_jobs(db_session)
    assert len(jobs) == 1
    assert jobs[0].id == job.id
    assert jobs[0].cron_expression == "0 2 * * *"
    assert jobs[0].enabled is True
    assert jobs[0].last_run_at is None


def test_toggle_cron_job(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *", enabled=True,
    )
    db_session.commit()

    toggle_cron_job(db_session, job.id)
    db_session.commit()
    assert get_cron_job(db_session, job.id).enabled is False

    toggle_cron_job(db_session, job.id)
    db_session.commit()
    assert get_cron_job(db_session, job.id).enabled is True


def test_update_cron_job(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *", enabled=True,
    )
    db_session.commit()

    update_cron_job(db_session, job.id, cron_expression="0 4 * * *", args="-a rescrape=true")
    db_session.commit()
    got = get_cron_job(db_session, job.id)
    assert got.cron_expression == "0 4 * * *"
    assert got.args == "-a rescrape=true"


def test_delete_cron_job(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *", enabled=True,
    )
    db_session.commit()

    delete_cron_job(db_session, job.id)
    db_session.commit()
    assert get_cron_job(db_session, job.id) is None
    assert list_cron_jobs(db_session) == []


def test_update_last_run(db_session):
    from datetime import UTC, datetime

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *", enabled=True,
    )
    db_session.commit()

    when = datetime.now(UTC)
    update_cron_job_last_run(db_session, job.id, when)
    db_session.commit()
    assert get_cron_job(db_session, job.id).last_run_at == when
```

### Step 2 — Run tests, confirm all FAIL with `ImportError`

`uv run pytest tests/integration/test_cron_jobs_repo.py -v`
Expected: 5 failures on `ImportError: cannot import name 'create_cron_job'`.

### Step 3 — Generate migration

`PYTHONPATH=. uv run alembic revision -m "add_cron_jobs_table"`

Replace the generated body with:

```python
"""add_cron_jobs_table

Revision ID: <keep-generated>
Revises: <keep-generated>  # most recent migration at time of generation
Create Date: <keep-generated>
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "<keep-generated>"
down_revision: Union[str, Sequence[str], None] = "<keep-generated-previous>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cron_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=True),
        sa.Column("args", sa.Text(), nullable=False, server_default=""),
        sa.Column("cron_expression", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cron_jobs_shop_enabled", "cron_jobs", ["shop_id", "enabled"])

    # Seed the two existing jobs so parity is preserved.
    conn = op.get_bind()
    shop_row = conn.execute(sa.text("SELECT id FROM shops WHERE name = 'vaga'")).fetchone()
    if shop_row is not None:
        shop_id = shop_row[0]
        conn.execute(
            sa.text(
                "INSERT INTO cron_jobs (shop_id, phase, strategy, args, cron_expression, enabled) "
                "VALUES (:shop_id, 'discover', 'sitemap', '', '0 2 * * *', true), "
                "(:shop_id, 'scan', NULL, '', '0 3 * * *', true)"
            ),
            {"shop_id": shop_id},
        )


def downgrade() -> None:
    op.drop_index("ix_cron_jobs_shop_enabled", table_name="cron_jobs")
    op.drop_table("cron_jobs")
```

Use the actual most-recent migration revision as `down_revision` — check it with `ls alembic/versions/ -t | head -3` before generating.

### Step 4 — Add model

In `book_scraper/db/models.py`, append at the end:

```python
class CronJob(Base):
    """Scheduled scrape job. Read by scripts/generate_crontab.py at scraper boot."""

    __tablename__ = "cron_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    args: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    cron_expression: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa_text("true"))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    shop: Mapped["Shop"] = relationship()

    __table_args__ = (
        Index("ix_cron_jobs_shop_enabled", "shop_id", "enabled"),
    )
```

If `Boolean` or `sa_text` aren't imported, add them. Add `from sqlalchemy import text as sa_text` if needed (the SQLAlchemy text() shadow import). Check existing imports — `Boolean` is likely already imported.

### Step 5 — Add repo CRUD functions

Append to `book_scraper/db/repo.py`:

```python
# --- CronJob CRUD ---


def list_cron_jobs(session: Session) -> list["CronJob"]:
    """Return all cron jobs, ordered by id."""
    from book_scraper.db.models import CronJob

    return list(session.execute(select(CronJob).order_by(CronJob.id)).scalars().all())


def get_cron_job(session: Session, job_id: int) -> "CronJob | None":
    from book_scraper.db.models import CronJob

    return session.get(CronJob, job_id)


def create_cron_job(
    session: Session,
    shop_id: int,
    phase: str,
    strategy: str | None,
    args: str,
    cron_expression: str,
    enabled: bool = True,
) -> "CronJob":
    from book_scraper.db.models import CronJob

    job = CronJob(
        shop_id=shop_id,
        phase=phase,
        strategy=strategy,
        args=args,
        cron_expression=cron_expression,
        enabled=enabled,
    )
    session.add(job)
    session.flush()
    return job


def update_cron_job(
    session: Session,
    job_id: int,
    **fields: Any,
) -> None:
    """Update allowed fields: phase, strategy, args, cron_expression, enabled."""
    from book_scraper.db.models import CronJob

    allowed = {"phase", "strategy", "args", "cron_expression", "enabled"}
    job = session.get(CronJob, job_id)
    if job is None:
        return
    for k, v in fields.items():
        if k in allowed:
            setattr(job, k, v)
    session.flush()


def toggle_cron_job(session: Session, job_id: int) -> None:
    from book_scraper.db.models import CronJob

    job = session.get(CronJob, job_id)
    if job is None:
        return
    job.enabled = not job.enabled
    session.flush()


def delete_cron_job(session: Session, job_id: int) -> None:
    from book_scraper.db.models import CronJob

    job = session.get(CronJob, job_id)
    if job is not None:
        session.delete(job)
        session.flush()


def update_cron_job_last_run(
    session: Session,
    job_id: int,
    when: "datetime",
) -> None:
    from book_scraper.db.models import CronJob

    job = session.get(CronJob, job_id)
    if job is None:
        return
    job.last_run_at = when
    session.flush()
```

### Step 6 — Apply migration, run tests

```bash
PYTHONPATH=. uv run alembic upgrade head
uv run pytest tests/integration/test_cron_jobs_repo.py -v
```

Expected: 5 PASS.

### Step 7 — Run full suite

`uv run pytest tests/ -v` — all 334+ pass.

### Step 8 — Commit

```bash
git add alembic/versions/ book_scraper/db/models.py book_scraper/db/repo.py tests/integration/test_cron_jobs_repo.py
git commit -m "feat(cron): add cron_jobs table + CRUD helpers"
```

---

## Task 2: DB-driven crontab generation

**Files:**
- Create: `scripts/generate_crontab.py`
- Modify: `scripts/entrypoint-scraper.sh` (call the new script)
- Delete: `cron/scraper-crontab` (replaced by DB generation)
- Modify: `Dockerfile` (stop copying the static file, include the script)
- Create: `tests/unit/test_generate_crontab.py`

### Step 1 — Write the unit test for `build_crontab_lines`

Create `tests/unit/test_generate_crontab.py`:

```python
"""Unit test for crontab line generation from cron_jobs rows."""

from types import SimpleNamespace


def test_build_crontab_lines_skips_disabled():
    from scripts.generate_crontab import build_crontab_lines

    jobs = [
        SimpleNamespace(
            id=1, shop=SimpleNamespace(name="vaga"),
            phase="discover", strategy="sitemap", args="",
            cron_expression="0 2 * * *", enabled=True,
        ),
        SimpleNamespace(
            id=2, shop=SimpleNamespace(name="vaga"),
            phase="scan", strategy=None, args="",
            cron_expression="0 3 * * *", enabled=False,
        ),
    ]
    lines = build_crontab_lines(jobs)
    assert len(lines) == 1
    assert "scrapy crawl discover" in lines[0]
    assert "-a shop=vaga" in lines[0]
    assert "-a strategy=sitemap" in lines[0]
    assert "0 2 * * *" in lines[0]
    assert ">> /var/log/scraper.log 2>&1" in lines[0]


def test_build_crontab_lines_scan_without_strategy():
    from scripts.generate_crontab import build_crontab_lines

    jobs = [
        SimpleNamespace(
            id=1, shop=SimpleNamespace(name="vaga"),
            phase="scan", strategy=None, args="-a rescrape=true",
            cron_expression="0 4 * * *", enabled=True,
        ),
    ]
    lines = build_crontab_lines(jobs)
    assert len(lines) == 1
    line = lines[0]
    assert "scrapy crawl scan" in line
    assert "-a shop=vaga" in line
    assert "-a strategy" not in line  # no strategy for scan
    assert "-a rescrape=true" in line


def test_build_crontab_lines_empty_list_returns_no_lines():
    from scripts.generate_crontab import build_crontab_lines

    assert build_crontab_lines([]) == []
```

Run: `uv run pytest tests/unit/test_generate_crontab.py -v`
Expected: 3 FAIL with ModuleNotFoundError.

### Step 2 — Create the generator script

Create `scripts/generate_crontab.py`:

```python
"""Generate and install the scraper container's crontab from cron_jobs.

Run by the entrypoint at boot time. Replaces the legacy static crontab
file at cron/scraper-crontab.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from book_scraper.db.models import CronJob


_LOG_PATH = "/var/log/scraper.log"
_ENV_PREFIX = (
    "cd /app && "
    "DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper "
    "PYTHONPATH=. /app/.venv/bin/python -m scrapy crawl"
)


def build_crontab_lines(jobs: "list[CronJob]") -> list[str]:
    """Return one crontab line per enabled job. Format:

    <cron_expression> cd /app && DATABASE_URL=... PYTHONPATH=. python -m scrapy crawl <phase> -a shop=<name> [-a strategy=<strategy>] [<args>] >> /var/log/scraper.log 2>&1
    """
    lines: list[str] = []
    for job in jobs:
        if not job.enabled:
            continue
        cmd = f"{_ENV_PREFIX} {job.phase} -a shop={job.shop.name}"
        if job.strategy:
            cmd += f" -a strategy={job.strategy}"
        if job.args:
            cmd += f" {job.args}"
        line = f"{job.cron_expression} {cmd} >> {_LOG_PATH} 2>&1"
        lines.append(line)
    return lines


def main() -> int:
    # Import lazily so the unit test can import build_crontab_lines
    # without opening a DB connection.
    from book_scraper.db.repo import list_cron_jobs
    from book_scraper.db.session import get_session_factory

    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    session = session_factory()
    try:
        jobs = list_cron_jobs(session)
    finally:
        session.close()

    lines = build_crontab_lines(jobs)
    content = "\n".join(lines) + ("\n" if lines else "")

    out_path = Path("/tmp/crontab-generated")
    out_path.write_text(content)

    result = subprocess.run(
        ["crontab", str(out_path)], check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"crontab install failed: {result.stderr}", file=sys.stderr)
        return result.returncode

    print(f"Installed {len(lines)} cron line(s) from cron_jobs table")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run unit tests: `uv run pytest tests/unit/test_generate_crontab.py -v`
Expected: 3 PASS.

### Step 3 — Update entrypoint

Replace `scripts/entrypoint-scraper.sh` with:

```bash
#!/bin/bash
set -e

echo "Running database migrations..."
cd /app
PYTHONPATH=. .venv/bin/python -m alembic upgrade head

echo "Reconciling orphan scrape runs..."
PYTHONPATH=. .venv/bin/python -m book_scraper.scripts.reconcile_runs

echo "Generating crontab from cron_jobs table..."
PYTHONPATH=. .venv/bin/python /app/scripts/generate_crontab.py

echo "Starting cron..."
touch /var/log/scraper.log
exec cron -f
```

### Step 4 — Update Dockerfile

Open `Dockerfile`. In the scraper stage, **remove** the line `COPY cron/scraper-crontab /app/cron/scraper-crontab`. **Add** a line to copy the scripts directory into the image (or ensure the existing `COPY` captures it). Check the current Dockerfile structure and adapt.

If `scripts/` isn't already copied into the base image, add `COPY scripts/ scripts/` after the `COPY book_scraper/` line in the base stage.

### Step 5 — Delete the static crontab file

```bash
git rm cron/scraper-crontab
# If the cron/ directory is now empty, remove it too:
rmdir cron 2>/dev/null || true
```

### Step 6 — Run full test suite

`uv run pytest tests/ -v` — all pass.

### Step 7 — Rebuild + restart scraper container

```bash
docker compose build scraper
docker compose up -d scraper
docker compose exec scraper crontab -l
```

Expected: 2 cron lines matching the seeded jobs (discover sitemap at 2am, scan at 3am).

If the `crontab -l` shows the expected lines, the DB-driven crontab is working.

### Step 8 — Commit

```bash
git add scripts/generate_crontab.py scripts/entrypoint-scraper.sh Dockerfile tests/unit/test_generate_crontab.py
git add -u  # picks up the deletion of cron/scraper-crontab
git commit -m "feat(cron): replace static crontab with cron_jobs-driven generation"
```

---

## Task 3: Dashboard routes + UI for cron CRUD

**Files:**
- Create: `book_scraper/dashboard/routes/cron.py`
- Create: `book_scraper/dashboard/templates/cron.html`
- Modify: `book_scraper/dashboard/templates/base.html` (add "Cron" nav link)
- Modify: `book_scraper/dashboard/app.py` (register router)
- Create: `tests/integration/test_cron_routes.py`

### Step 1 — Write failing route tests

Create `tests/integration/test_cron_routes.py`:

```python
"""Dashboard /cron routes."""

from fastapi.testclient import TestClient

from book_scraper.dashboard.app import app
from book_scraper.db.repo import create_cron_job, list_cron_jobs, upsert_shop


def test_get_cron_page_returns_200(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *", enabled=True,
    )
    db_session.commit()

    client = TestClient(app)
    r = client.get("/cron")
    assert r.status_code == 200
    assert "0 2 * * *" in r.text
    assert "discover" in r.text


def test_post_cron_creates_job(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    client = TestClient(app)
    r = client.post(
        "/cron",
        data={
            "shop_id": shop.id,
            "phase": "scan",
            "strategy": "",
            "args": "-a rescrape=true",
            "cron_expression": "0 4 * * *",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303  # redirect back to list

    jobs = list_cron_jobs(db_session)
    assert any(j.cron_expression == "0 4 * * *" for j in jobs)


def test_post_toggle_flips_enabled(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *", enabled=True,
    )
    db_session.commit()

    client = TestClient(app)
    r = client.post(f"/cron/{job.id}/toggle", follow_redirects=False)
    assert r.status_code == 303

    from book_scraper.db.repo import get_cron_job

    db_session.expire_all()
    assert get_cron_job(db_session, job.id).enabled is False


def test_post_delete_removes_job(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *", enabled=True,
    )
    db_session.commit()

    client = TestClient(app)
    r = client.post(f"/cron/{job.id}/delete", follow_redirects=False)
    assert r.status_code == 303

    from book_scraper.db.repo import get_cron_job

    db_session.expire_all()
    assert get_cron_job(db_session, job.id) is None
```

Run: `uv run pytest tests/integration/test_cron_routes.py -v`
Expected: FAIL (404s since /cron not registered).

### Step 2 — Create the cron routes

Create `book_scraper/dashboard/routes/cron.py`:

```python
"""Dashboard routes for managing cron_jobs."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from book_scraper.db.repo import (
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    list_cron_jobs,
    toggle_cron_job,
    update_cron_job,
)
from book_scraper.dashboard.deps import get_session, templates

router = APIRouter()


@router.get("/cron")
def cron_index(request: Request):  # type: ignore[no-untyped-def]
    with get_session() as session:
        jobs = list_cron_jobs(session)
        # Eager-load shop names
        jobs_with_shops = [
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
        # List of shops for the create form
        from book_scraper.db.models import Shop
        from sqlalchemy import select

        shops = list(session.execute(select(Shop).order_by(Shop.name)).scalars().all())
        shop_options = [{"id": s.id, "name": s.name} for s in shops]

    return templates.TemplateResponse(
        request,
        "cron.html",
        {"jobs": jobs_with_shops, "shops": shop_options, "active_page": "cron"},
    )


@router.post("/cron")
def cron_create(
    shop_id: int = Form(...),
    phase: str = Form(...),
    strategy: str = Form(""),
    args: str = Form(""),
    cron_expression: str = Form(...),
):  # type: ignore[no-untyped-def]
    with get_session() as session:
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
def cron_toggle(job_id: int):  # type: ignore[no-untyped-def]
    with get_session() as session:
        toggle_cron_job(session, job_id)
        session.commit()
    return RedirectResponse(url="/cron", status_code=303)


@router.post("/cron/{job_id}/delete")
def cron_delete(job_id: int):  # type: ignore[no-untyped-def]
    with get_session() as session:
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
):  # type: ignore[no-untyped-def]
    with get_session() as session:
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
```

**Note:** `get_session` and `templates` are assumed to exist in `book_scraper/dashboard/deps.py` (or wherever the project puts FastAPI dependencies — check by reading one existing route file like `routes/runs.py`). If the project uses a different pattern (e.g., module-level `templates = Jinja2Templates(...)` defined in `app.py`), adapt the imports accordingly.

### Step 3 — Create the template

Create `book_scraper/dashboard/templates/cron.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>Cron Jobs</h1>

<section class="card">
  <h2>Schedules</h2>
  <table>
    <thead>
      <tr>
        <th>Shop</th>
        <th>Phase</th>
        <th>Strategy</th>
        <th>Args</th>
        <th>Schedule (cron)</th>
        <th>Enabled</th>
        <th>Last run</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {% for job in jobs %}
      <tr>
        <td>{{ job.shop_name }}</td>
        <td>{{ job.phase }}</td>
        <td>{{ job.strategy }}</td>
        <td><code>{{ job.args }}</code></td>
        <td><code>{{ job.cron_expression }}</code></td>
        <td>{{ "yes" if job.enabled else "no" }}</td>
        <td>{{ job.last_run_at or "—" }}</td>
        <td>
          <form method="post" action="/cron/{{ job.id }}/toggle" style="display:inline">
            <button type="submit">{{ "Disable" if job.enabled else "Enable" }}</button>
          </form>
          <form method="post" action="/cron/{{ job.id }}/delete" style="display:inline"
                onsubmit="return confirm('Delete this cron job?');">
            <button type="submit">Delete</button>
          </form>
        </td>
      </tr>
      {% endfor %}
      {% if not jobs %}
      <tr><td colspan="8">No cron jobs configured.</td></tr>
      {% endif %}
    </tbody>
  </table>
</section>

<section class="card">
  <h2>Add job</h2>
  <form method="post" action="/cron">
    <label>
      Shop:
      <select name="shop_id" required>
        {% for s in shops %}
        <option value="{{ s.id }}">{{ s.name }}</option>
        {% endfor %}
      </select>
    </label>
    <label>
      Phase:
      <select name="phase" required>
        <option value="discover">discover</option>
        <option value="scan">scan</option>
      </select>
    </label>
    <label>
      Strategy (for discover):
      <input type="text" name="strategy" placeholder="sitemap, categories, full_crawl" />
    </label>
    <label>
      Extra args:
      <input type="text" name="args" placeholder="-a rescrape=true" />
    </label>
    <label>
      Cron expression:
      <input type="text" name="cron_expression" required placeholder="0 2 * * *" />
    </label>
    <p style="font-size:0.85em;color:#666">
      Changes take effect after the scraper container restarts. Run <code>docker compose restart scraper</code> after editing.
    </p>
    <button type="submit">Create</button>
  </form>
</section>
{% endblock %}
```

### Step 4 — Register the router

In `book_scraper/dashboard/app.py`, find where other routers are `include_router`'d (e.g. `app.include_router(runs.router)`). Add:

```python
from book_scraper.dashboard.routes import cron as cron_routes
app.include_router(cron_routes.router)
```

### Step 5 — Add "Cron" to nav

In `book_scraper/dashboard/templates/base.html`, find the `<ul class="nav-links">` and add after the Runs link:

```html
<li><a href="/cron" class="{{ 'active' if active_page == 'cron' else '' }}">Cron</a></li>
```

### Step 6 — Run route tests

`uv run pytest tests/integration/test_cron_routes.py -v`
Expected: all 4 PASS.

If any test fails due to `get_session` pattern mismatch, inspect `book_scraper/dashboard/deps.py` or equivalent and adapt the import.

### Step 7 — Run full suite + smoke dashboard

```bash
uv run pytest tests/ -v
docker compose build dashboard
docker compose up -d dashboard
curl -sf http://localhost:8000/cron > /dev/null && echo OK
```

### Step 8 — Commit

```bash
git add book_scraper/dashboard/routes/cron.py book_scraper/dashboard/templates/cron.html book_scraper/dashboard/templates/base.html book_scraper/dashboard/app.py tests/integration/test_cron_routes.py
git commit -m "feat(dashboard): cron jobs CRUD UI"
```

---

## Task 4: "Run now" button via docker exec

**Files:**
- Modify: `docker-compose.yml` (mount docker socket into dashboard)
- Modify: `book_scraper/dashboard/routes/cron.py` (add `/cron/{id}/run` endpoint)
- Modify: `book_scraper/dashboard/templates/cron.html` (add "Run now" button)
- Create: `tests/integration/test_cron_run_now.py`

### Step 1 — Write the failing run-now test

Create `tests/integration/test_cron_run_now.py`:

```python
"""Dashboard 'Run now' endpoint."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from book_scraper.dashboard.app import app
from book_scraper.db.repo import create_cron_job, upsert_shop


def test_post_run_now_invokes_docker_exec(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *", enabled=True,
    )
    db_session.commit()

    client = TestClient(app)
    with patch("book_scraper.dashboard.routes.cron.subprocess.Popen") as popen:
        r = client.post(f"/cron/{job.id}/run", follow_redirects=False)
        assert r.status_code == 303

    popen.assert_called_once()
    args = popen.call_args[0][0]  # first positional arg = command list
    assert args[0] == "docker"
    assert "exec" in args
    assert "scraper" in args
    # scrapy command is built with shop=vaga and strategy=sitemap
    joined = " ".join(args)
    assert "scrapy crawl discover" in joined
    assert "-a shop=vaga" in joined
    assert "-a strategy=sitemap" in joined


def test_post_run_now_disabled_job_still_runs(db_session):
    """Run now bypasses the enabled flag — admin override."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *", enabled=False,
    )
    db_session.commit()

    client = TestClient(app)
    with patch("book_scraper.dashboard.routes.cron.subprocess.Popen") as popen:
        r = client.post(f"/cron/{job.id}/run", follow_redirects=False)
        assert r.status_code == 303
    popen.assert_called_once()
```

Run: `uv run pytest tests/integration/test_cron_run_now.py -v`
Expected: FAIL — endpoint not found.

### Step 2 — Add `/cron/{id}/run` route

In `book_scraper/dashboard/routes/cron.py`, add at the top:

```python
import subprocess
```

Append to the file:

```python
@router.post("/cron/{job_id}/run")
def cron_run_now(job_id: int):  # type: ignore[no-untyped-def]
    """Trigger an immediate run of a cron job via docker exec on the scraper container.

    Bypasses the enabled flag so an admin can re-run disabled jobs.
    The scraper container name must be reachable from the dashboard
    container — the compose default name is 'book-scraper-scraper-1'.
    """
    with get_session() as session:
        job = get_cron_job(session, job_id)
        if job is None:
            return RedirectResponse(url="/cron", status_code=303)
        cmd = [
            "docker", "exec", "-d",  # detached: don't block dashboard request
            "book-scraper-scraper-1",
            "sh", "-c",
            _build_scrapy_cmd(
                job.shop.name, job.phase, job.strategy, job.args
            ),
        ]
    subprocess.Popen(cmd)  # fire and forget
    return RedirectResponse(url="/cron", status_code=303)


def _build_scrapy_cmd(
    shop_name: str, phase: str, strategy: str | None, args: str
) -> str:
    """Build the 'scrapy crawl ...' command string that runs inside the scraper."""
    cmd = (
        "cd /app && "
        "DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper "
        "PYTHONPATH=. /app/.venv/bin/python -m scrapy crawl "
        f"{phase} -a shop={shop_name}"
    )
    if strategy:
        cmd += f" -a strategy={strategy}"
    if args:
        cmd += f" {args}"
    cmd += " >> /var/log/scraper.log 2>&1"
    return cmd
```

### Step 3 — Add "Run now" button to the template

In `book_scraper/dashboard/templates/cron.html`, inside the `<td>` with action buttons, add:

```html
<form method="post" action="/cron/{{ job.id }}/run" style="display:inline">
  <button type="submit">Run now</button>
</form>
```

Place it BEFORE the Disable/Delete buttons so it's the leftmost action.

### Step 4 — Run route tests

`uv run pytest tests/integration/test_cron_run_now.py -v`
Expected: both PASS.

### Step 5 — Mount Docker socket into dashboard container

In `docker-compose.yml`, find the `dashboard:` service block. Add under its `volumes:` key (or create if missing):

```yaml
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

**Security note**: this gives the dashboard container root-equivalent access to the Docker daemon. For a personal-project self-hosted setup, acceptable; for any multi-tenant deployment, do NOT ship this.

### Step 6 — Ensure `docker` CLI is available in dashboard image

In `Dockerfile`, in the dashboard stage, add before the `EXPOSE 8000` line:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends docker.io && rm -rf /var/lib/apt/lists/*
```

(Pin a specific version if you like; `docker.io` from Debian repos is fine for issuing `docker exec` commands.)

### Step 7 — Rebuild and smoke test the full chain

```bash
docker compose build dashboard scraper
docker compose up -d
# Visit http://localhost:8000/cron in browser, click "Run now" for the sitemap job.
# Watch:
docker compose exec scraper tail -f /var/log/scraper.log
```

Expected: a `scrapy crawl discover -a shop=vaga -a strategy=sitemap` run starts within a second and logs progress to `/var/log/scraper.log`.

If the Docker exec fails with "permission denied", the socket isn't properly mounted or the container needs its user in the docker group — check `ls -la /var/run/docker.sock` inside the dashboard container.

### Step 8 — Run full suite

`uv run pytest tests/ -v`

### Step 9 — Commit

```bash
git add book_scraper/dashboard/routes/cron.py book_scraper/dashboard/templates/cron.html docker-compose.yml Dockerfile tests/integration/test_cron_run_now.py
git commit -m "feat(dashboard): 'Run now' button triggers scraper via docker exec"
```

---

## Task 5: Track `last_run_at` when a cron-triggered job finishes

**Files:**
- Modify: `book_scraper/services/scan.py` (update `last_run_at` in `finish_scan` when applicable)
- Modify: `book_scraper/spiders/discover.py` (same for discover's `closed` method)
- Create: `tests/integration/test_cron_last_run.py`

The "right" linkage between a cron job and a scrape_run would be an FK `scrape_runs.cron_job_id`. That's a schema change. For MVP, match by `(shop_id, phase, strategy)`:

### Step 1 — Write the failing test

Create `tests/integration/test_cron_last_run.py`:

```python
"""When a scan or discover run completes, its matching cron_job.last_run_at updates."""

from book_scraper.db.models import DiscoveredUrl, ScrapeRun
from book_scraper.db.repo import (
    create_cron_job,
    get_cron_job,
    upsert_shop,
)
from book_scraper.services.scan import ScanService


def test_scan_finish_updates_matching_cron_job_last_run(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id, url="https://vaga.lt/a", normalized_url="https://vaga.lt/a",
            source="sitemap", url_type="product", fail_count=0,
        )
    )
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *", enabled=True,
    )
    db_session.commit()

    assert get_cron_job(db_session, job.id).last_run_at is None

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)
    service.finish_scan(plan.run_id, urls_processed=1, url_status_updates=[], reason="finished")

    db_session.expire_all()
    updated = get_cron_job(db_session, job.id).last_run_at
    assert updated is not None
```

Run: `uv run pytest tests/integration/test_cron_last_run.py -v`
Expected: FAIL — `last_run_at` still None.

### Step 2 — Add a repo helper for matching

Append to `book_scraper/db/repo.py`:

```python
def mark_cron_job_ran_if_matches(
    session: Session,
    shop_id: int,
    phase: str,
    strategy: str | None = None,
) -> None:
    """Update last_run_at on the cron_job that matches (shop_id, phase, strategy).

    No-op if no cron_job matches. Used at the end of scrape runs to keep
    the dashboard's 'last run' column current.
    """
    from book_scraper.db.models import CronJob

    stmt = select(CronJob).where(
        CronJob.shop_id == shop_id,
        CronJob.phase == phase,
        CronJob.strategy == strategy,
    )
    job = session.execute(stmt).scalar_one_or_none()
    if job is not None:
        job.last_run_at = datetime.now(UTC)
        session.flush()
```

### Step 3 — Wire up in `finish_scan`

In `book_scraper/services/scan.py`, update imports to include `mark_cron_job_ran_if_matches`. In `finish_scan`, after the existing `finish_scrape_run(...)` call and before `cleanup_scrape_url_items(...)`:

```python
# Find the ScrapeRun to pick up shop_id.
from book_scraper.db.models import ScrapeRun

run = self.session.get(ScrapeRun, run_id)
if run is not None:
    mark_cron_job_ran_if_matches(
        self.session, run.shop_id, phase="scan", strategy=None
    )
```

### Step 4 — Wire up in discover spider

In `book_scraper/spiders/discover.py`, find the `closed` method (around line 334). After the run is marked completed/failed, add:

```python
from book_scraper.db.repo import mark_cron_job_ran_if_matches

mark_cron_job_ran_if_matches(
    self._run_session, shop.id, phase="discover", strategy=self.strategy
)
self._run_session.commit()
```

Read the method first — `shop` may be named differently in scope, and the session variable name varies. Adapt.

### Step 5 — Run all tests

```bash
uv run pytest tests/integration/test_cron_last_run.py -v
uv run pytest tests/ -v
```

### Step 6 — Commit

```bash
git add book_scraper/db/repo.py book_scraper/services/scan.py book_scraper/spiders/discover.py tests/integration/test_cron_last_run.py
git commit -m "feat(cron): update cron_job.last_run_at when a matching run finishes"
```

---

## Deferred (separate plan)

- **Live crontab reload** when dashboard changes a job (currently requires `docker compose restart scraper`)
- **Execution history view** — show recent runs per cron job in the dashboard
- **Block concurrent runs per (shop, phase)** — currently Run-now will happily launch even if a scan is already in-flight
- **Per-shop shop_config validation** for cron job args before saving
