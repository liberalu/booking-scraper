# Cron Chain Jobs + Schedule Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix missing cron jobs in the Schedules UI (broken `_cron_run_phase` for graphql/lupasearch strategies) and implement Option B job chaining — a `chain_to_job_id` FK on `cron_jobs` that auto-spawns the next job when the predecessor finishes.

**Architecture:** Single self-referential FK column on `cron_jobs`. At spider close with `reason="finished"`, a new `CronChainTrigger` extension reads the `cron_job_id` spider arg, looks up `chain_to_job_id` in the DB, and spawns the next scrapy subprocess. The crontab generator passes `cron_job_id` to every scrapy command. Frontend adds a "Chain to" dropdown on New/Edit schedule dialogs and shows a chain badge in the job table.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, FastAPI, Scrapy, React (JSX via CDN Babel), PostgreSQL

---

## File Map

| File | Change |
|------|--------|
| `book_scraper/dashboard/routes/api.py` | Fix `_cron_run_phase`; per-job resilience; expose/accept `chain_to_id` in cron endpoints; `_spawn_scrapy_in_container` + `NewRunRequest` accept `cron_job_id` |
| `book_scraper/db/models.py` | Add `chain_to_job_id` FK column to `CronJob` |
| `alembic/versions/2026_05_06_add_chain_to_cron_jobs.py` | Migration: add column + FK |
| `book_scraper/db/repo.py` | `create_cron_job` + `update_cron_job` support `chain_to_job_id` |
| `scripts/generate_crontab.py` | Add `-a cron_job_id={j.id}` to every scrapy command |
| `book_scraper/extensions.py` | New `CronChainTrigger` extension |
| `book_scraper/settings.py` | Register `CronChainTrigger` in `EXTENSIONS` |
| `book_scraper/dashboard/static/hifi/hf-overlays.jsx` | "Chain to" dropdown in `HFNewScheduleDialog` + `HFEditScheduleDialog` |
| `book_scraper/dashboard/static/hifi/hf-other.jsx` | Chain badge in job row; pass `cron_job_id` in `runJobNow` |
| `tests/integration/test_cron_jobs_repo.py` | Test chain FK CRUD |
| `tests/unit/test_generate_crontab.py` | Test `cron_job_id` in crontab lines |
| `tests/integration/test_dashboard_routes.py` | Test `chain_to_id` in `/api/cron` response |
| `tests/unit/test_cron_chain_trigger.py` | Unit tests for `CronChainTrigger` |

---

### Task 1: Fix `_cron_run_phase` bug + per-job resilience

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py:227-239` (fix), `:1882-1921` (resilience)

- [ ] **Step 1: Write a failing test exposing the bug**

Add to `tests/integration/test_dashboard_routes.py`:

```python
@pytest.mark.integration
def test_api_cron_returns_200_with_graphql_strategy_job(
    client: TestClient, db_session: Session
) -> None:
    """Regression: graphql/lupasearch strategies must not crash /api/cron."""
    from book_scraper.db.repo import create_cron_job, upsert_shop

    shop = upsert_shop(db_session, "pegasas", "https://www.pegasas.lt")
    create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="discover",
        strategy="graphql",
        args="",
        cron_expression="0 1 * * *",
        enabled=True,
    )
    db_session.commit()

    resp = client.get("/api/cron")
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    graphql_jobs = [j for j in data["jobs"] if j["strategy"] == "graphql"]
    assert len(graphql_jobs) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/evaldas/Projects/book-scraper/.claude/worktrees/cranky-benz-e6faaa
uv run pytest tests/integration/test_dashboard_routes.py::test_api_cron_returns_200_with_graphql_strategy_job -v
```

Expected: 500 or assertion error — the job is missing from the response.

- [ ] **Step 3: Fix `_cron_run_phase` in `api.py`**

In `book_scraper/dashboard/routes/api.py`, replace lines 237-238:

```python
    if job_strategy and job_strategy in ("sitemap", "categories", "full_crawl"):
        return f"discover_{job_strategy}"
```

with:

```python
    _DISCOVER_STRATEGIES = frozenset(
        ("sitemap", "categories", "full_crawl", "graphql", "lupasearch")
    )
    if job_strategy and job_strategy in _DISCOVER_STRATEGIES:
        return f"discover_{job_strategy}"
```

Move the constant to module level (just before the function, around line 227) so it isn't recreated on every call:

```python
_DISCOVER_STRATEGIES = frozenset(
    ("sitemap", "categories", "full_crawl", "graphql", "lupasearch")
)


def _cron_run_phase(job_phase: str, job_strategy: str | None) -> str:
    """Compute the scrape_runs.phase value that corresponds to this cron job.

    For discover jobs the DB phase includes the strategy
    (e.g. discover_sitemap). For scan jobs the strategy is UI-only metadata
    (delta/full) and the DB phase is always just 'scan'.
    """
    if job_phase == "scan":
        return "scan"
    if job_strategy and job_strategy in _DISCOVER_STRATEGIES:
        return f"discover_{job_strategy}"
    return job_phase or "scan"
```

- [ ] **Step 4: Add per-job try/except in `api_cron`**

In `api_cron` (around line 1888), wrap the per-job block so one bad job never hides the rest. Replace the `for j in jobs:` loop body:

```python
    for j in jobs:
        run_phase = _cron_run_phase(j.phase, j.strategy)
        # Next fire time via croniter
        next_dt: datetime | None
        next_in_s: int | None
        try:
            cron = croniter(j.cron_expression, now)
            next_dt = cron.get_next(datetime).replace(tzinfo=UTC)
            next_in_s = int((next_dt - now).total_seconds())
        except Exception:
            next_dt = None
            next_in_s = None

        metrics = _cron_job_metrics(session, j.shop_id, run_phase)
        result.append(
            {
                ...
            }
        )
```

with:

```python
    for j in jobs:
        try:
            run_phase = _cron_run_phase(j.phase, j.strategy)
            next_dt: datetime | None
            next_in_s: int | None
            try:
                cron = croniter(j.cron_expression, now)
                next_dt = cron.get_next(datetime).replace(tzinfo=UTC)
                next_in_s = int((next_dt - now).total_seconds())
            except Exception:
                next_dt = None
                next_in_s = None

            metrics = _cron_job_metrics(session, j.shop_id, run_phase)
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
                    "last_status": metrics["last_status"] or "ok",
                    "next": _fmt_next(next_in_s) if j.enabled else "—",
                    "next_run_at": next_dt.isoformat() if next_dt and j.enabled else None,
                    "avg_dur": _fmt_dur(metrics["avg_dur_s"]),
                }
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("api_cron: skipping job %d", j.id)
```

Note: the `import logging` here is a lazy import inside the except block to match the file's style. Move it to the top of the function if there's already a `logger` in scope (check if `logger = logging.getLogger(__name__)` exists at module level in `api.py`).

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run pytest tests/integration/test_dashboard_routes.py::test_api_cron_returns_200_with_graphql_strategy_job -v
```

Expected: PASS

- [ ] **Step 6: Run all cron-related tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py::test_api_cron tests/integration/test_cron_jobs_repo.py tests/integration/test_cron_last_run.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add book_scraper/dashboard/routes/api.py tests/integration/test_dashboard_routes.py
git commit -m "fix(api): _cron_run_phase handles graphql/lupasearch + per-job resilience in /api/cron"
```

---

### Task 2: Add `chain_to_job_id` column to `CronJob` model

**Files:**
- Modify: `book_scraper/db/models.py:679-704`
- Create: `alembic/versions/2026_05_06_add_chain_to_cron_jobs.py`

- [ ] **Step 1: Add column to `CronJob` model**

In `book_scraper/db/models.py`, update the `CronJob` class (after the `last_run_at` column, before `created_at`):

```python
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    chain_to_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("cron_jobs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
```

Verify `ForeignKey` is already imported (it is — used by `shop_id`). No relationship needed; we'll query by ID directly.

- [ ] **Step 2: Write the Alembic migration**

Create `alembic/versions/2026_05_06_add_chain_to_cron_jobs.py`:

```python
"""add_chain_to_cron_jobs

Revision ID: a3f7d92b1c44
Revises: f6a2b3c4d5e7
Create Date: 2026-05-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3f7d92b1c44"
down_revision: str | Sequence[str] | None = "f6a2b3c4d5e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cron_jobs",
        sa.Column("chain_to_job_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_cron_jobs_chain_to_job_id",
        "cron_jobs",
        "cron_jobs",
        ["chain_to_job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_cron_jobs_chain_to_job_id", "cron_jobs", type_="foreignkey")
    op.drop_column("cron_jobs", "chain_to_job_id")
```

- [ ] **Step 3: Run the migration**

```bash
PYTHONPATH=. uv run alembic upgrade head
```

Expected output: `Running upgrade f6a2b3c4d5e7 -> a3f7d92b1c44, add_chain_to_cron_jobs`

- [ ] **Step 4: Verify column exists**

```bash
docker exec book-scraper-postgres-1 psql -U postgres -d book_scraper -c "\d cron_jobs"
```

Expected: `chain_to_job_id | integer | | |` row is present.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/db/models.py alembic/versions/2026_05_06_add_chain_to_cron_jobs.py
git commit -m "feat(db): add chain_to_job_id FK to cron_jobs"
```

---

### Task 3: Update repo functions for `chain_to_job_id`

**Files:**
- Modify: `book_scraper/db/repo.py:1993-2030`
- Modify: `tests/integration/test_cron_jobs_repo.py`

- [ ] **Step 1: Write a failing test for chain FK in repo**

Add to `tests/integration/test_cron_jobs_repo.py`:

```python
def test_chain_to_job_id_create_and_update(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job_a = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="discover",
        strategy="sitemap",
        args="",
        cron_expression="0 2 * * *",
        enabled=True,
        chain_to_job_id=None,
    )
    db_session.commit()

    job_b = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="scan",
        strategy=None,
        args="",
        cron_expression="0 3 * * *",
        enabled=True,
        chain_to_job_id=job_a.id,
    )
    db_session.commit()

    # chain FK is stored
    assert get_cron_job(db_session, job_b.id).chain_to_job_id == job_a.id

    # update clears chain
    update_cron_job(db_session, job_b.id, chain_to_job_id=None)
    db_session.commit()
    assert get_cron_job(db_session, job_b.id).chain_to_job_id is None

    # update sets chain
    update_cron_job(db_session, job_b.id, chain_to_job_id=job_a.id)
    db_session.commit()
    assert get_cron_job(db_session, job_b.id).chain_to_job_id == job_a.id


def test_chain_to_job_id_set_null_on_delete(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job_a = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *", enabled=True,
    )
    job_b = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *", enabled=True,
        chain_to_job_id=job_a.id,
    )
    db_session.commit()

    delete_cron_job(db_session, job_a.id)
    db_session.commit()

    db_session.expire(job_b)
    assert get_cron_job(db_session, job_b.id).chain_to_job_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_cron_jobs_repo.py::test_chain_to_job_id_create_and_update tests/integration/test_cron_jobs_repo.py::test_chain_to_job_id_set_null_on_delete -v
```

Expected: FAIL — `create_cron_job` doesn't accept `chain_to_job_id`.

- [ ] **Step 3: Update `create_cron_job` in `repo.py`**

In `book_scraper/db/repo.py`, update `create_cron_job` (around line 1993):

```python
def create_cron_job(
    session: Session,
    shop_id: int,
    phase: str,
    strategy: str | None,
    args: str,
    cron_expression: str,
    enabled: bool = True,
    chain_to_job_id: int | None = None,
) -> CronJob:
    job = CronJob(
        shop_id=shop_id,
        phase=phase,
        strategy=strategy,
        args=args,
        cron_expression=cron_expression,
        enabled=enabled,
        chain_to_job_id=chain_to_job_id,
    )
    session.add(job)
    session.flush()
    return job
```

- [ ] **Step 4: Update `update_cron_job` to allow `chain_to_job_id`**

In `book_scraper/db/repo.py`, update `update_cron_job` (around line 2015):

```python
def update_cron_job(
    session: Session,
    job_id: int,
    **fields: Any,
) -> None:
    """Update allowed fields: phase, strategy, args, cron_expression, enabled, chain_to_job_id."""
    allowed = {"phase", "strategy", "args", "cron_expression", "enabled", "chain_to_job_id"}
    job = session.get(CronJob, job_id)
    if job is None:
        return
    for k, v in fields.items():
        if k in allowed:
            setattr(job, k, v)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_cron_jobs_repo.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add book_scraper/db/repo.py tests/integration/test_cron_jobs_repo.py
git commit -m "feat(repo): create_cron_job + update_cron_job support chain_to_job_id"
```

---

### Task 4: Update API endpoints to expose and accept chain fields

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py`

- [ ] **Step 1: Write a failing test for chain in GET /api/cron**

Add to `tests/integration/test_dashboard_routes.py`:

```python
@pytest.mark.integration
def test_api_cron_exposes_chain_to_id(client: TestClient, db_session: Session) -> None:
    from book_scraper.db.repo import create_cron_job, upsert_shop

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job_a = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *",
    )
    job_b = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *",
        chain_to_job_id=job_a.id,
    )
    db_session.commit()

    resp = client.get("/api/cron")
    assert resp.status_code == 200
    jobs = {j["id"]: j for j in resp.json()["jobs"]}

    assert jobs[job_a.id]["chain_to_id"] is None
    assert jobs[job_b.id]["chain_to_id"] == job_a.id
    assert jobs[job_b.id]["chain_to_name"] is not None


@pytest.mark.integration
def test_api_cron_create_with_chain(client: TestClient, db_session: Session) -> None:
    from book_scraper.db.repo import create_cron_job, upsert_shop

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job_a = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *",
    )
    db_session.commit()

    resp = client.post(
        "/api/cron",
        json={
            "shop": "vaga",
            "phase": "scan",
            "strategy": "",
            "cron_expression": "0 3 * * *",
            "chain_to_id": job_a.id,
        },
    )
    assert resp.status_code == 200
    new_id = resp.json()["id"]

    from book_scraper.db.repo import get_cron_job
    saved = get_cron_job(db_session, new_id)
    db_session.refresh(saved)
    assert saved.chain_to_job_id == job_a.id
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_dashboard_routes.py::test_api_cron_exposes_chain_to_id tests/integration/test_dashboard_routes.py::test_api_cron_create_with_chain -v
```

Expected: FAIL — `chain_to_id` key missing from response.

- [ ] **Step 3: Update `api_cron` response to include chain fields**

In `book_scraper/dashboard/routes/api.py`, inside the `for j in jobs:` loop in `api_cron` (around line 1903), add `chain_to_id` and `chain_to_name` to the `result.append({...})` dict. The chain job lookup goes right before the `result.append`:

```python
            # Chain: look up the chain target name for display
            chain_job = (
                session.get(CronJob, j.chain_to_job_id)
                if j.chain_to_job_id
                else None
            )
            chain_to_name = (
                f"{chain_job.shop.name}.{chain_job.phase}"
                f".{chain_job.strategy or 'default'}"
                if chain_job
                else None
            )
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
                    "last_status": metrics["last_status"] or "ok",
                    "next": _fmt_next(next_in_s) if j.enabled else "—",
                    "next_run_at": next_dt.isoformat() if next_dt and j.enabled else None,
                    "avg_dur": _fmt_dur(metrics["avg_dur_s"]),
                    "chain_to_id": j.chain_to_job_id,
                    "chain_to_name": chain_to_name,
                }
            )
```

Make sure the `CronJob` import is available at the top of `api.py` where models are imported.

- [ ] **Step 4: Update `_CronJobBody` and `api_cron_create`**

In `book_scraper/dashboard/routes/api.py`, update `_CronJobBody` (around line 2100):

```python
class _CronJobBody(BaseModel):
    shop: str
    phase: str
    strategy: str = ""
    cron_expression: str
    chain_to_id: int | None = None
```

Update `api_cron_create` to pass `chain_to_job_id`:

```python
@router.post("/cron")
def api_cron_create(
    body: _CronJobBody, session: Session = Depends(get_db)
) -> dict[str, Any]:
    shop = get_shop_by_name(session, body.shop)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    if body.phase not in ("discover", "scan"):
        raise HTTPException(
            status_code=422, detail="phase must be 'discover' or 'scan'"
        )
    # Validate chain target exists if provided
    if body.chain_to_id is not None:
        chain_target = get_cron_job(session, body.chain_to_id)
        if chain_target is None:
            raise HTTPException(status_code=404, detail="Chain target job not found")
    strategy = body.strategy.strip() or None
    job = create_cron_job(
        session,
        shop_id=shop.id,
        phase=body.phase,
        strategy=strategy,
        args="",
        cron_expression=body.cron_expression,
        chain_to_job_id=body.chain_to_id,
    )
    session.commit()
    return {
        "id": job.id,
        "name": f"{shop.name}.{job.phase}.{job.strategy or 'default'}",
    }
```

- [ ] **Step 5: Update `_CronJobPatch` and `api_cron_update`**

```python
class _CronJobPatch(BaseModel):
    cron_expression: str | None = None
    phase: str | None = None
    strategy: str | None = None
    chain_to_id: int | None = None
    clear_chain: bool = False  # set True to explicitly clear chain_to_job_id to None
```

Update `api_cron_update`:

```python
@router.patch("/cron/{job_id}")
def api_cron_update(
    job_id: int, body: _CronJobPatch, session: Session = Depends(get_db)
) -> dict[str, Any]:
    job = get_cron_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    fields: dict[str, Any] = {}
    if body.cron_expression is not None:
        fields["cron_expression"] = body.cron_expression
    if body.phase is not None:
        if body.phase not in ("discover", "scan"):
            raise HTTPException(
                status_code=422, detail="phase must be 'discover' or 'scan'"
            )
        fields["phase"] = body.phase
    if body.strategy is not None:
        fields["strategy"] = body.strategy.strip() or None
    if body.chain_to_id is not None:
        chain_target = get_cron_job(session, body.chain_to_id)
        if chain_target is None:
            raise HTTPException(status_code=404, detail="Chain target job not found")
        fields["chain_to_job_id"] = body.chain_to_id
    elif body.clear_chain:
        fields["chain_to_job_id"] = None
    if fields:
        update_cron_job(session, job_id, **fields)
        session.commit()
    return {"id": job_id}
```

- [ ] **Step 6: Update `_spawn_scrapy_in_container` and `NewRunRequest` to accept `cron_job_id`**

Update `NewRunRequest` (line 531):

```python
class NewRunRequest(BaseModel):
    shop: str
    phase: str = "scan"
    strategy: str = ""
    mode: str = "delta"
    urls: str = ""
    cron_job_id: int | None = None  # passed to spider so chain trigger fires
```

Update `_spawn_scrapy_in_container` signature and body (line 584):

```python
def _spawn_scrapy_in_container(
    *,
    phase: str,
    shop: str,
    strategy: str = "",
    mode: str = "delta",
    urls: str = "",
    cron_job_id: int | None = None,
) -> None:
    ...
    cmd = ["/app/.venv/bin/scrapy", "crawl", phase, "-a", f"shop={shop}"]
    if phase == "discover" and strategy:
        cmd.extend(["-a", f"strategy={strategy}"])
    if phase == "scan":
        if urls:
            cmd.extend(["-a", f"urls={urls}"])
        elif mode == "full":
            cmd.extend(["-a", "rescrape=true"])
        elif mode == "sample":
            cmd.extend(["-a", "max_urls=10"])
    if cron_job_id is not None:
        cmd.extend(["-a", f"cron_job_id={cron_job_id}"])
    ...
```

Find the call to `_spawn_scrapy_in_container` inside `api_create_run` (line 660) and pass through:

```python
    _spawn_scrapy_in_container(
        phase=phase,
        shop=req.shop,
        strategy=req.strategy,
        mode=req.mode,
        urls=req.urls,
        cron_job_id=req.cron_job_id,
    )
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_dashboard_routes.py::test_api_cron_exposes_chain_to_id tests/integration/test_dashboard_routes.py::test_api_cron_create_with_chain -v
```

Expected: PASS

- [ ] **Step 8: Run the full dashboard route smoke tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add book_scraper/dashboard/routes/api.py tests/integration/test_dashboard_routes.py
git commit -m "feat(api): cron endpoints expose + accept chain_to_id; spawn passes cron_job_id"
```

---

### Task 5: Update `generate_crontab.py` to pass `cron_job_id`

**Files:**
- Modify: `scripts/generate_crontab.py:27-39`
- Modify: `tests/unit/test_generate_crontab.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_generate_crontab.py`:

```python
def test_build_crontab_lines_includes_cron_job_id():
    from scripts.generate_crontab import build_crontab_lines

    jobs = [
        SimpleNamespace(
            id=42,
            shop=SimpleNamespace(name="vaga"),
            phase="discover",
            strategy="sitemap",
            args="",
            cron_expression="0 2 * * *",
            enabled=True,
        ),
    ]
    lines = build_crontab_lines(jobs)
    assert len(lines) == 1
    assert "-a cron_job_id=42" in lines[0]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_generate_crontab.py::test_build_crontab_lines_includes_cron_job_id -v
```

Expected: FAIL — `cron_job_id` not in output.

- [ ] **Step 3: Update `build_crontab_lines` in `generate_crontab.py`**

```python
def build_crontab_lines(jobs: "list[CronJob]") -> list[str]:
    """Return one crontab line per enabled job."""
    lines: list[str] = []
    for job in jobs:
        if not job.enabled:
            continue
        cmd = f"{_ENV_PREFIX} {job.phase} -a shop={job.shop.name}"
        if job.strategy:
            cmd += f" -a strategy={job.strategy}"
        cmd += f" -a cron_job_id={job.id}"
        if job.args:
            cmd += f" {job.args}"
        line = f"{job.cron_expression} {cmd} >> {_LOG_PATH} 2>&1"
        lines.append(line)
    return lines
```

- [ ] **Step 4: Run all generate_crontab tests**

```bash
uv run pytest tests/unit/test_generate_crontab.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_crontab.py tests/unit/test_generate_crontab.py
git commit -m "feat(crontab): pass -a cron_job_id to scrapy so chain trigger fires"
```

---

### Task 6: Add `CronChainTrigger` extension

**Files:**
- Modify: `book_scraper/extensions.py` (append new class)
- Modify: `book_scraper/settings.py:62-65`
- Create: `tests/unit/test_cron_chain_trigger.py`

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_cron_chain_trigger.py`:

```python
"""Unit tests for CronChainTrigger extension."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from book_scraper.extensions import CronChainTrigger


@pytest.fixture
def crawler() -> MagicMock:
    c = MagicMock()
    c.settings.get.return_value = "postgresql://localhost/test"
    c.spider = MagicMock(_run_id=None)
    return c


def test_no_spawn_when_reason_is_not_finished(crawler: MagicMock) -> None:
    """Chain must NOT fire if spider closes for any reason other than 'finished'."""
    ext = CronChainTrigger(crawler)
    spider = MagicMock()
    spider.cron_job_id = "3"
    ext.spider_opened(spider)

    with patch.object(ext, "_spawn_chain_subprocess") as mock_spawn:
        ext.spider_closed(spider, reason="shutdown")
        mock_spawn.assert_not_called()

    with patch.object(ext, "_spawn_chain_subprocess") as mock_spawn:
        ext.spider_closed(spider, reason="stall_timeout")
        mock_spawn.assert_not_called()


def test_no_spawn_when_no_cron_job_id(crawler: MagicMock) -> None:
    """Chain must NOT fire if cron_job_id was not set (e.g. manually triggered run)."""
    ext = CronChainTrigger(crawler)
    spider = MagicMock(spec=[])  # no cron_job_id attribute
    ext.spider_opened(spider)

    with patch.object(ext, "_spawn_chain_subprocess") as mock_spawn:
        ext.spider_closed(spider, reason="finished")
        mock_spawn.assert_not_called()


def test_no_spawn_when_chain_to_job_id_is_none(crawler: MagicMock) -> None:
    """Chain must NOT fire if the job has no chain configured."""
    ext = CronChainTrigger(crawler)
    spider = MagicMock()
    spider.cron_job_id = "5"
    ext.spider_opened(spider)

    mock_job = MagicMock()
    mock_job.chain_to_job_id = None

    with patch.object(ext, "_get_chain_job", return_value=(mock_job, None)):
        with patch.object(ext, "_spawn_chain_subprocess") as mock_spawn:
            ext.spider_closed(spider, reason="finished")
            mock_spawn.assert_not_called()


def test_spawns_chain_on_finished(crawler: MagicMock) -> None:
    """Chain job subprocess is spawned when reason='finished' and chain exists."""
    ext = CronChainTrigger(crawler)
    spider = MagicMock()
    spider.cron_job_id = "3"
    ext.spider_opened(spider)

    mock_this_job = MagicMock()
    mock_this_job.chain_to_job_id = 7

    mock_chain_job = MagicMock()
    mock_chain_job.id = 7
    mock_chain_job.phase = "scan"
    mock_chain_job.strategy = None
    mock_chain_job.args = ""
    mock_chain_job.shop.name = "vaga"

    with patch.object(ext, "_get_chain_job", return_value=(mock_this_job, mock_chain_job)):
        with patch.object(ext, "_spawn_chain_subprocess") as mock_spawn:
            ext.spider_closed(spider, reason="finished")
            mock_spawn.assert_called_once_with(
                phase="scan",
                shop="vaga",
                strategy=None,
                args="",
                chain_job_id=7,
            )


def test_spawns_chain_with_strategy(crawler: MagicMock) -> None:
    """Discover chain job includes strategy arg."""
    ext = CronChainTrigger(crawler)
    spider = MagicMock()
    spider.cron_job_id = "1"
    ext.spider_opened(spider)

    mock_this_job = MagicMock()
    mock_this_job.chain_to_job_id = 2

    mock_chain_job = MagicMock()
    mock_chain_job.id = 2
    mock_chain_job.phase = "discover"
    mock_chain_job.strategy = "graphql"
    mock_chain_job.args = ""
    mock_chain_job.shop.name = "pegasas"

    with patch.object(ext, "_get_chain_job", return_value=(mock_this_job, mock_chain_job)):
        with patch.object(ext, "_spawn_chain_subprocess") as mock_spawn:
            ext.spider_closed(spider, reason="finished")
            mock_spawn.assert_called_once_with(
                phase="discover",
                shop="pegasas",
                strategy="graphql",
                args="",
                chain_job_id=2,
            )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_cron_chain_trigger.py -v
```

Expected: FAIL — `CronChainTrigger` does not exist.

- [ ] **Step 3: Add `CronChainTrigger` to `extensions.py`**

Append to `book_scraper/extensions.py` (after the `StallDetector` class):

```python
class CronChainTrigger:  # pragma: no cover
    """After a cron-scheduled run finishes successfully, spawn the chained job.

    Reads ``cron_job_id`` from spider args (set by generate_crontab.py).
    On ``spider_closed`` with reason ``finished``, looks up ``chain_to_job_id``
    in the DB and spawns the next scrapy subprocess. Passing the chain job's
    own ``cron_job_id`` enables multi-step chains.
    """

    def __init__(self, crawler: Crawler) -> None:
        self.crawler = crawler
        self._cron_job_id: int | None = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "CronChainTrigger":
        ext = cls(crawler)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_opened(self, spider: Any) -> None:
        raw = getattr(spider, "cron_job_id", None)
        try:
            self._cron_job_id = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            self._cron_job_id = None

    def spider_closed(self, spider: Any, reason: str) -> None:
        if reason != "finished":
            return
        if self._cron_job_id is None:
            return
        this_job, chain_job = self._get_chain_job(self._cron_job_id)
        if chain_job is None:
            return
        self._spawn_chain_subprocess(
            phase=chain_job.phase,
            shop=chain_job.shop.name,
            strategy=chain_job.strategy,
            args=chain_job.args or "",
            chain_job_id=chain_job.id,
        )

    def _get_chain_job(
        self, cron_job_id: int
    ) -> "tuple[Any, Any]":
        """Return (this_job, chain_job) by querying the DB.

        Returns (this_job, None) if no chain is configured or on DB error.
        """
        from book_scraper.db.models import CronJob
        from book_scraper.db.session import get_session_factory

        database_url = self.crawler.settings.get("DATABASE_URL")
        if not database_url:
            return None, None
        try:
            session = get_session_factory(database_url)()
            try:
                this_job = session.get(CronJob, cron_job_id)
                if this_job is None or not this_job.chain_to_job_id:
                    return this_job, None
                chain_job = session.get(CronJob, this_job.chain_to_job_id)
                # Access relationship eagerly while session is open
                if chain_job is not None:
                    _ = chain_job.shop.name  # load shop while session is open
                return this_job, chain_job
            finally:
                session.close()
        except Exception:
            logger.exception(
                "CronChainTrigger: DB lookup failed for cron_job_id=%d", cron_job_id
            )
            return None, None

    def _spawn_chain_subprocess(
        self,
        *,
        phase: str,
        shop: str,
        strategy: str | None,
        args: str,
        chain_job_id: int,
    ) -> None:
        """Detach a scrapy subprocess for the chain job."""
        import os
        import shlex
        import subprocess

        cmd_parts = [
            "/app/.venv/bin/scrapy",
            "crawl",
            phase,
            "-a",
            f"shop={shop}",
        ]
        if phase == "discover" and strategy:
            cmd_parts.extend(["-a", f"strategy={strategy}"])
        cmd_parts.extend(["-a", f"cron_job_id={chain_job_id}"])
        if args:
            # args is a space-separated string like "-a rescrape=true"
            cmd_parts.extend(shlex.split(args))

        env = os.environ.copy()
        env.setdefault("PYTHONPATH", "/app")
        cmd_str = " ".join(shlex.quote(p) for p in cmd_parts)

        try:
            subprocess.Popen(
                cmd_parts,
                cwd="/app",
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            logger.exception("CronChainTrigger: failed to spawn %s", cmd_str)
            return

        logger.info(
            "CronChainTrigger: spawned chain job %d → %s (cron_job_id=%d)",
            self._cron_job_id or -1,
            cmd_str,
            chain_job_id,
        )
```

- [ ] **Step 4: Register the extension in `settings.py`**

In `book_scraper/settings.py`, update `EXTENSIONS`:

```python
EXTENSIONS = {  # pragma: no cover
    "book_scraper.extensions.StallDetector": 500,  # pragma: no cover
    "book_scraper.extensions.HeartbeatExtension": 510,  # pragma: no cover
    "book_scraper.extensions.CronChainTrigger": 520,  # pragma: no cover
}  # pragma: no cover
```

- [ ] **Step 5: Run unit tests to verify they pass**

```bash
uv run pytest tests/unit/test_cron_chain_trigger.py -v
```

Expected: all PASS

- [ ] **Step 6: Run mypy**

```bash
uv run mypy book_scraper/extensions.py
```

Expected: no errors on `CronChainTrigger`.

- [ ] **Step 7: Commit**

```bash
git add book_scraper/extensions.py book_scraper/settings.py tests/unit/test_cron_chain_trigger.py
git commit -m "feat(extensions): CronChainTrigger spawns chained cron job on finished"
```

---

### Task 7: Frontend — "Chain to" dropdown in New/Edit schedule dialogs

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-overlays.jsx`

- [ ] **Step 1: Add "Chain to" field to `HFNewScheduleDialog`**

In `hf-overlays.jsx`, inside `HFNewScheduleDialog` (around line 609):

Add state for `chainToId`:

```jsx
const [chainToId, setChainToId] = React.useState(null);
const [allJobs, setAllJobs] = React.useState([]);
```

Add a `useEffect` to load existing jobs when the dialog opens (after the shops `useEffect`):

```jsx
React.useEffect(() => {
  if (!open) return;
  fetch('/api/cron')
    .then(r => r.json())
    .then(d => setAllJobs(d.jobs || []))
    .catch(() => setAllJobs([]));
}, [open]);
```

Reset `chainToId` when dialog closes:

```jsx
React.useEffect(() => {
  if (!open) { setChainToId(null); }
}, [open]);
```

The jobs available for chaining are those from the same shop (excluding the job being created, which has no id yet):

```jsx
const chainOptions = allJobs.filter(j => j.shop === shop);
```

Pass `chain_to_id` in `handleCreate`:

```jsx
body: JSON.stringify({ shop, phase, strategy, cron_expression: cron, chain_to_id: chainToId || null }),
```

Add the field in the modal body, after the Frequency field:

```jsx
<HFField label="Chain to" hint="Run this job immediately after the selected job finishes">
  <HFSelect
    value={chainToId ? String(chainToId) : ''}
    onChange={v => setChainToId(v ? parseInt(v, 10) : null)}
    options={[
      { value: '', label: 'None — run independently' },
      ...chainOptions.map(j => ({ value: String(j.id), label: j.name })),
    ]}
  />
</HFField>
```

Full updated `HFNewScheduleDialog` function (replace lines 609-719):

```jsx
function HFNewScheduleDialog({ open, onClose }) {
  const HF = getHF();
  const [shop, setShop] = React.useState('');
  const [phase, setPhase] = React.useState('scan');
  const [strategy, setStrategy] = React.useState('');
  const [cron, setCron] = React.useState('0 */2 * * *');
  const [chainToId, setChainToId] = React.useState(null);
  const [shops, setShops] = React.useState([]);
  const [allJobs, setAllJobs] = React.useState([]);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    if (!open) { setChainToId(null); setError(''); return; }
    fetch('/api/shops')
      .then(r => r.json())
      .then(d => {
        const list = d.shops || [];
        setShops(list);
        setShop(prev => prev || (list[0] && list[0].name) || '');
      })
      .catch(() => setError('Could not load shops'));
    fetch('/api/cron')
      .then(r => r.json())
      .then(d => setAllJobs(d.jobs || []))
      .catch(() => setAllJobs([]));
  }, [open]);

  const selShop = shops.find(s => s.name === shop);
  const shopStrategies = selShop?.discover_strategies || [];
  const chainOptions = allJobs.filter(j => j.shop === shop);

  React.useEffect(() => {
    if (phase === 'scan') {
      if (!['delta', 'full'].includes(strategy)) setStrategy('delta');
      return;
    }
    if (!shopStrategies.length) { setStrategy(''); return; }
    if (!shopStrategies.includes(strategy)) setStrategy(shopStrategies[0]);
  }, [phase, shop, shopStrategies.join(',')]);

  const handleCreate = async () => {
    if (!cron.trim()) return;
    setSaving(true); setError('');
    try {
      const resp = await fetch('/api/cron', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, phase, strategy, cron_expression: cron, chain_to_id: chainToId || null }),
      });
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}));
        setError(d.detail || `Error ${resp.status}`);
        return;
      }
      onClose(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const canCreate = cron.trim().length > 0;

  return (
    <HFModal open={open} onClose={() => onClose(false)} width={540}>
      <HFModalHead title="New schedule" sub="Run a shop on a recurring cron" onClose={() => onClose(false)} icon={HF_ICONS.cron}/>
      <HFModalBody>
        <HFField label="Shop" required>
          <HFSelect value={shop} onChange={setShop} options={shops.map(s => ({
            value: s.name,
            label: `${s.name}.lt`,
          }))}/>
        </HFField>
        <HFField label="Phase" required>
          <HFSegmented value={phase} onChange={setPhase} options={[
            { value:'scan',     label:'Scan' },
            { value:'discover', label:'Discover' },
          ]}/>
        </HFField>
        <HFField label="Mode" hint={phase === 'scan' ? {
            delta: 'Resumable scan — only URLs not yet scraped',
            full:  'Re-scrape every known URL',
          }[strategy] : _hfStrategyHint(strategy)}>
          {phase === 'scan' ? (
            <HFSegmented value={strategy} onChange={setStrategy} options={[
              { value:'delta', label:'Delta' },
              { value:'full',  label:'Full' },
            ]}/>
          ) : (
            shopStrategies.length ? (
              <HFSegmented value={strategy} onChange={setStrategy}
                options={_hfStrategyOptions(shopStrategies)}/>
            ) : (
              <div style={{ fontSize:13, color:'var(--hf-ink3)' }}>
                No discover strategies configured for {shop || 'this shop'}.
              </div>
            )
          )}
        </HFField>
        <HFField label="Frequency" required>
          <HFCronFrequencyPicker value={cron} onChange={setCron}/>
        </HFField>
        <HFField label="Chain to" hint="Spawn this job automatically after the selected job finishes">
          <HFSelect
            value={chainToId ? String(chainToId) : ''}
            onChange={v => setChainToId(v ? parseInt(v, 10) : null)}
            options={[
              { value: '', label: 'None — run independently' },
              ...chainOptions.map(j => ({ value: String(j.id), label: j.name })),
            ]}
          />
        </HFField>
        {error && <div style={{color:'var(--hf-err-ink)', fontSize:13, marginTop:4}}>{error}</div>}
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={() => onClose(false)}>Cancel</HFButton>
        <HFButton variant="primary" onClick={handleCreate} disabled={!canCreate || saving}>
          {saving ? 'Creating…' : 'Create schedule'}
        </HFButton>
      </HFModalFoot>
    </HFModal>
  );
}
```

- [ ] **Step 2: Add "Chain to" field to `HFEditScheduleDialog`**

In `hf-overlays.jsx`, update `HFEditScheduleDialog` (around line 722). Add `chainToId` state and load it from `job.chain_to_id` on open:

```jsx
function HFEditScheduleDialog({ open, job, onClose }) {
  const HF = getHF();
  const [phase, setPhase] = React.useState(job?.phase || 'scan');
  const [strategy, setStrategy] = React.useState(job?.strategy || '');
  const [cron, setCron] = React.useState(job?.cron || '');
  const [chainToId, setChainToId] = React.useState(job?.chain_to_id || null);
  const [shopStrategies, setShopStrategies] = React.useState([]);
  const [allJobs, setAllJobs] = React.useState([]);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    if (job) {
      setPhase(job.phase || 'scan');
      setStrategy(job.strategy || '');
      setCron(job.cron || '');
      setChainToId(job.chain_to_id || null);
      setError('');
    }
  }, [job]);

  React.useEffect(() => {
    if (!open || !job?.shop) { setShopStrategies([]); setAllJobs([]); return; }
    fetch(`/api/shops/${encodeURIComponent(job.shop)}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setShopStrategies(d?.discover_strategies || []))
      .catch(() => setShopStrategies([]));
    fetch('/api/cron')
      .then(r => r.json())
      .then(d => setAllJobs(d.jobs || []))
      .catch(() => setAllJobs([]));
  }, [open, job?.shop]);

  React.useEffect(() => {
    if (phase === 'scan') {
      if (!['delta', 'full'].includes(strategy)) setStrategy('delta');
      return;
    }
    if (!shopStrategies.length) return;
    if (!shopStrategies.includes(strategy)) setStrategy(shopStrategies[0]);
  }, [phase, shopStrategies.join(',')]);

  // Jobs available for chaining: same shop, excluding this job itself
  const chainOptions = allJobs.filter(j => j.shop === job?.shop && j.id !== job?.id);

  const handleSave = async () => {
    if (!cron.trim() || !job?.id) return;
    setSaving(true); setError('');
    try {
      const resp = await fetch(`/api/cron/${job.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phase,
          strategy,
          cron_expression: cron,
          chain_to_id: chainToId || null,
          clear_chain: chainToId === null,
        }),
      });
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}));
        setError(d.detail || `Error ${resp.status}`);
        return;
      }
      onClose(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <HFModal open={open} onClose={() => onClose(false)} width={540}>
      <HFModalHead title="Edit schedule" sub={job?.name || ''} onClose={() => onClose(false)} icon={HF_ICONS.settings}/>
      <HFModalBody>
        <HFField label="Phase" required>
          <HFSegmented value={phase} onChange={setPhase} options={[
            { value:'scan',     label:'Scan' },
            { value:'discover', label:'Discover' },
          ]}/>
        </HFField>
        <HFField label="Mode" hint={phase === 'scan' ? {
            delta: 'Resumable scan — only URLs not yet scraped',
            full:  'Re-scrape every known URL',
          }[strategy] : _hfStrategyHint(strategy)}>
          {phase === 'scan' ? (
            <HFSegmented value={strategy} onChange={setStrategy} options={[
              { value:'delta', label:'Delta' },
              { value:'full',  label:'Full' },
            ]}/>
          ) : (
            shopStrategies.length ? (
              <HFSegmented value={strategy} onChange={setStrategy}
                options={_hfStrategyOptions(shopStrategies)}/>
            ) : (
              <div style={{ fontSize:13, color:'var(--hf-ink3)' }}>
                No discover strategies configured for this shop.
              </div>
            )
          )}
        </HFField>
        <HFField label="Frequency" required>
          <HFCronFrequencyPicker value={cron} onChange={setCron}/>
        </HFField>
        <HFField label="Chain to" hint="Spawn this job automatically after the selected job finishes">
          <HFSelect
            value={chainToId ? String(chainToId) : ''}
            onChange={v => setChainToId(v ? parseInt(v, 10) : null)}
            options={[
              { value: '', label: 'None — run independently' },
              ...chainOptions.map(j => ({ value: String(j.id), label: j.name })),
            ]}
          />
        </HFField>
        {error && <div style={{color:'var(--hf-err-ink)', fontSize:13, marginTop:4}}>{error}</div>}
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={() => onClose(false)}>Cancel</HFButton>
        <HFButton variant="primary" onClick={handleSave} disabled={!cron.trim() || saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </HFButton>
      </HFModalFoot>
    </HFModal>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-overlays.jsx
git commit -m "feat(ui): Chain to dropdown in New/Edit schedule dialogs"
```

---

### Task 8: Frontend — chain badge in job list + pass `cron_job_id` from Play button

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-other.jsx`

- [ ] **Step 1: Pass `chain_to_id` through to job list rows**

In `hf-other.jsx`, in `HFCron`, update the `jobs` mapping (around line 37) to include chain fields:

```jsx
const jobs = jobsRaw.map(j => ({
  ...j,
  state: j.enabled ? 'active' : 'disabled',
  lastStatus: j.last_status || 'ok',
  next: j.next || '—',
  avgDur: j.avg_dur || '—',
}));
```

This already spreads `...j`, so `chain_to_id` and `chain_to_name` from the API are included automatically. No change needed here.

- [ ] **Step 2: Add chain badge column to the job table**

In the `HFTable columns` array (around line 82), add a chain column between `avgDur` and the toggle:

```jsx
{ key:'chain_to_name', label:'Chain', w:'1fr', cell:(v) =>
  v ? (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:4,
      fontSize:12, color:'var(--hf-accent-ink)', fontFamily:'var(--hf-mono)',
    }}>
      <span style={{opacity:0.5}}>→</span> {v}
    </span>
  ) : (
    <span style={{color:'var(--hf-ink5)', fontSize:12}}>—</span>
  )
},
```

- [ ] **Step 3: Pass `cron_job_id` in `runJobNow`**

Update `runJobNow` (around line 24):

```jsx
const runJobNow = async (job) => {
  try {
    const body = {
      shop: job.shop,
      phase: job.phase,
      strategy: job.strategy || '',
      mode: 'delta',
      cron_job_id: job.id,
    };
    const resp = await fetch('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (resp.ok) goto('runs');
  } catch (e) { console.error(e); }
};
```

- [ ] **Step 4: Also pass `chain_to_id` and `chain_to_name` in `goto('schedule-detail', ...)` call (line 81)**

Update `onRowClick`:

```jsx
onRowClick={(r) => goto('schedule-detail', {
  id: r.id, name: r.name, cron: r.cron, shop: r.shop, enabled: r.enabled,
  lastStatus: r.lastStatus, chain_to_id: r.chain_to_id, chain_to_name: r.chain_to_name,
})}
```

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-other.jsx
git commit -m "feat(ui): show chain badge in schedule table; pass cron_job_id on manual run"
```

---

### Task 9: Rebuild dashboard + smoke test

- [ ] **Step 1: Rebuild + restart dashboard container**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

- [ ] **Step 2: Run smoke tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all PASS

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all PASS (or pre-existing failures only)

- [ ] **Step 4: Run mypy and lint**

```bash
uv run mypy book_scraper/
uv run ruff check book_scraper/ tests/
```

Expected: no new errors

- [ ] **Step 5: Verify dashboard in browser**

Open `http://localhost:8000` → Schedules. Confirm:
- All jobs are visible (including pegasas graphql/lupasearch jobs if they exist)
- "Chain to" dropdown appears in New/Edit schedule dialogs
- Chain badge shows `→ job_name` for chained jobs

---

## Self-Review Checklist

- [x] **`_cron_run_phase` fix** — Task 1 adds `graphql` + `lupasearch`
- [x] **Per-job resilience** — Task 1 wraps loop body in try/except
- [x] **DB column** — Task 2 adds FK with `ON DELETE SET NULL`
- [x] **Repo** — Task 3 updates `create_cron_job` + `update_cron_job`
- [x] **API GET** — Task 4 exposes `chain_to_id` + `chain_to_name`
- [x] **API POST/PATCH** — Task 4 accepts `chain_to_id` and validates existence
- [x] **PATCH clear chain** — Task 4 uses `clear_chain: bool` to null it out
- [x] **`cron_job_id` in crontab** — Task 5
- [x] **`cron_job_id` in manual run** — Task 4 + 8
- [x] **`CronChainTrigger` extension** — Task 6
- [x] **Extension registered** — Task 6 updates `settings.py`
- [x] **Frontend New dialog** — Task 7
- [x] **Frontend Edit dialog** — Task 7 (excludes self from chain options)
- [x] **Frontend chain badge** — Task 8
- [x] **`HFSelect` component** — used in overlay dialogs; already exists in `hf-ui.jsx` (used by `HFFilter`)
- [x] **No placeholders** — all steps have concrete code
- [x] **Type consistency** — `chain_to_job_id` (DB/repo), `chain_to_id` (API wire format), `chainToId` (JS state) used consistently throughout
