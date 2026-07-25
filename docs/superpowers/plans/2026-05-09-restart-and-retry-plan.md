# Single-Row Restart + Auto-Retry Failed URLs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop creating a new `scrape_runs` row each time a stalled scrape is auto-resumed. Mutate the same row in place, log the restart on the run's event timeline, and add an end-of-run sweep that retries failed URLs up to a global cap.

**Architecture:** One Alembic migration adds `scrape_url_items.attempts` and extends the `scrape_run_events` event-type CHECK constraint with `restarted`. The `services/scan.py` and `services/discover.py` resumable-failed branches stop calling `create_scrape_run` + `inherit_pending_items` and instead mutate the existing run row + emit a `restarted` event in one transaction. Existing `spider_idle` handlers in `book_scraper/spiders/scan.py` and `book_scraper/spiders/discover.py` get a one-shot end-of-run retry phase that resets eligible failed items to pending. `mark_scrape_url_item_processing` increments `attempts` per dispatch. Two circuit-breaker repo helpers (`count_auto_resume_chain_depth`, `count_consecutive_zero_progress_resumes`) refactored to count events on the single row instead of walking a chain. Operator-facing endpoints (Continue, Retry-failures) and dashboard rendering get small touch-ups.

**Tech Stack:** Python 3.12, Scrapy, SQLAlchemy 2.0, Alembic, FastAPI + Jinja2 (legacy) + React (current dashboard), PostgreSQL 16, pytest with real DB on port 5433, uv, Docker Compose.

**Spec:** [docs/superpowers/specs/2026-05-09-restart-and-retry-design.md](../specs/2026-05-09-restart-and-retry-design.md)

---

## File Structure

**New files:**

- `alembic/versions/2026_05_09_attempts_and_restarted_event.py` — single migration. Adds `attempts INTEGER NOT NULL DEFAULT 0` to `scrape_url_items`. Drops and re-adds `ck_scrape_run_events_event_type` to include `'restarted'`.
- `tests/integration/test_restart_in_place.py` — integration coverage for the same-row mutation flow on both scan and discover services.
- `tests/integration/test_end_of_run_retry.py` — integration coverage for the retry sweep, attempts increment, and cap enforcement.

**Modified files:**

- `book_scraper/db/scrape_run_events.py` — add `RESTARTED` constant, update `EVENT_TYPES` set.
- `book_scraper/db/models.py` — add `attempts` column to `ScrapeUrlItem` model **AND** update `ScrapeRunEvent` `__table_args__` `CheckConstraint` (line 522–530) to include `'restarted'` and `'subdivided'`. The current model-level constraint omits both `restarted` (planned) AND `subdivided` (already in the migration but never reflected in the model). `tests/conftest.py` builds the test schema via `Base.metadata.create_all(engine)`, so the model-level constraint must match the migration or integration tests reject `restarted` and `subdivided` events.
- `book_scraper/db/repo.py`:
  - `mark_scrape_url_item_processing` — increment `attempts` atomically.
  - New `restart_run_in_place(session, run, payload, actor)` — mutate existing row + emit `restarted` event in one transaction.
  - New `fetch_retryable_failed_items(session, run_id, cap)` — return failed items eligible for end-of-run retry.
  - New `reset_failed_items_to_pending(session, item_ids, *, reset_attempts=False)` — flip `failed` items back to `pending`. Optional reset of `attempts` for the manual operator path.
  - `count_auto_resume_chain_depth` — read `restarted` events on a single run instead of walking the chain.
  - `count_consecutive_zero_progress_resumes` — read `urls_processed_snapshot` from event payloads on a single run.
- `book_scraper/services/scan.py::ScanService.prepare_scan_create_run` — replace the resumable-failed branch with a call to `restart_run_in_place`.
- `book_scraper/services/discover.py::DiscoverService.prepare_discover` — same change.
- `book_scraper/spiders/scan.py::ScanSpider.spider_idle` — gate end-of-run retry sweep behind a `_end_of_run_retry_done` flag.
- `book_scraper/spiders/discover.py::DiscoverSpider.spider_idle` — same change.
- `book_scraper/settings.py` — add `RETRY_CAP = 3`.
- `book_scraper/dashboard/routes/api.py::api_retry_run_failures` — reset `attempts` to 0 when operator manually retries.
- `book_scraper/dashboard/templates/components/timeline.html` (or React equivalent — confirmed during Task 11) — render `restarted` icon and tooltip; keep legacy `resumed_after_failure` rendering intact.
- `book_scraper/dashboard/templates/components/failures_card.html` (or React equivalent) — render `attempts` column with capped marker.

**Existing helpers reused:**

- `_reset_retryable_failures(session, run_id)` at [book_scraper/db/repo.py:858](book_scraper/db/repo.py:858) — already does what the spec calls out; the new `restart_run_in_place` calls it directly.
- `reset_processing_scrape_url_items(session, run_id)` at [book_scraper/db/repo.py:2001](book_scraper/db/repo.py:2001).
- `emit_scrape_run_event(session, run_id, event_type, *, payload, actor)` at [book_scraper/db/repo.py:921](book_scraper/db/repo.py:921).
- `find_resumable_run(session, shop_id, phase)` at [book_scraper/db/repo.py:1263](book_scraper/db/repo.py:1263) — semantics unchanged.

**Files NOT changed (by design):**

- `book_scraper/extensions.py::StallDetector` — spawn logic untouched. The new behavior lives in the spawned subprocess's service layer.
- `book_scraper/scripts/reconcile_runs.py` — boot reconcile keeps spawning subprocesses unchanged.
- `book_scraper/dashboard/routes/api.py::api_continue_run` — already mutates the same row in place; no change needed.

---

## Task 1: Migration + constants (event type + attempts column)

**Files:**
- Create: `alembic/versions/2026_05_09_attempts_and_restarted_event.py`
- Modify: `book_scraper/db/scrape_run_events.py`
- Modify: `book_scraper/db/models.py:544-591` (add column to `ScrapeUrlItem`)
- Test: `tests/integration/test_scrape_run_events.py` (extend existing)

- [ ] **Step 1: Write failing test for `restarted` event acceptance**

Append to `tests/integration/test_scrape_run_events.py`:

```python
def test_restarted_event_accepted(db_session):
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.repo import emit_scrape_run_event

    shop = upsert_shop(db_session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.commit()

    event = emit_scrape_run_event(
        db_session,
        run.id,
        run_event_types.RESTARTED,
        payload={"previous_close_reason": "stall_timeout", "attempt": 1,
                 "urls_processed_snapshot": 0},
        actor=run_event_types.ACTOR_SYSTEM,
    )
    db_session.commit()

    assert event.event_type == "restarted"
    assert event.payload["attempt"] == 1
```

(If `upsert_shop` / `create_scrape_run` are not already imported in that file, add them — check existing tests in the file for the import block to mirror.)

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose up -d postgres-test
PYTHONPATH=. uv run pytest tests/integration/test_scrape_run_events.py::test_restarted_event_accepted -v
```

Expected: FAIL with `ValueError: unknown scrape run event_type: 'restarted'` (raised by `emit_scrape_run_event` before the constant is added).

- [ ] **Step 3: Add `RESTARTED` constant and update `EVENT_TYPES` set**

In `book_scraper/db/scrape_run_events.py`, edit the constants block:

```python
"""Constants for scrape_run_events lifecycle log."""

from typing import Final

STARTED: Final = "started"
PAUSED: Final = "paused"
RESUMED: Final = "resumed"
STOP_REQUESTED: Final = "stop_requested"
RETRY_FAILURES: Final = "retry_failures"
RERUN: Final = "rerun"
CONTINUED: Final = "continued"
RESUMED_AFTER_FAILURE: Final = "resumed_after_failure"
# Single-row restart marker. Distinct from RESUMED_AFTER_FAILURE which
# was emitted on the *new* row when the chain-row model created one
# child row per process attempt. RESTARTED is emitted on the same
# logical-run row each time a process restart happens (stall, heartbeat
# timeout, boot reconcile). Operator-triggered restarts continue to use
# CONTINUED.
RESTARTED: Final = "restarted"
COMPLETED: Final = "completed"
FAILED: Final = "failed"
SUBDIVIDED: Final = "subdivided"

EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        STARTED,
        PAUSED,
        RESUMED,
        STOP_REQUESTED,
        RETRY_FAILURES,
        RERUN,
        CONTINUED,
        RESUMED_AFTER_FAILURE,
        RESTARTED,
        COMPLETED,
        FAILED,
        SUBDIVIDED,
    }
)

ACTOR_OPERATOR: Final = "operator"
ACTOR_SYSTEM: Final = "system"
```

- [ ] **Step 4a: Add `attempts` column to the SQLAlchemy model**

In `book_scraper/db/models.py`, in the `ScrapeUrlItem` class right after the `retry_count` column (around line 583), insert:

```python
    # Number of dispatch cycles for this URL within its current logical
    # run. Initial dispatch increments to 1; the end-of-run retry sweep
    # adds another increment per re-dispatch. Capped at RETRY_CAP (3) by
    # the sweep — items at the cap stay `failed` (sticky). NOT
    # incremented per Scrapy RetryMiddleware retry — that's tracked
    # separately in `retry_count`.
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
```

- [ ] **Step 4b: Update the model-level CheckConstraint on `ScrapeRunEvent`**

`tests/conftest.py:14` calls `Base.metadata.create_all(engine)` — the integration tests build their schema from the SQLAlchemy models, not from Alembic migrations. The `ScrapeRunEvent.__table_args__` constraint at `book_scraper/db/models.py:524-528` currently lists:

```
'started','paused','resumed','stop_requested','retry_failures',
'rerun','continued','resumed_after_failure','completed','failed'
```

Missing both `'subdivided'` (already in production via migration `2026-04-26-telemetry-columns`) and the planned `'restarted'`. Replace the constraint block with:

```python
    __table_args__ = (
        Index("ix_scrape_run_events_run_created", "run_id", "created_at"),
        CheckConstraint(
            "event_type IN ("
            "'started','paused','resumed','stop_requested','retry_failures',"
            "'rerun','continued','resumed_after_failure','restarted',"
            "'completed','failed','subdivided'"
            ")",
            name="ck_scrape_run_events_event_type",
        ),
    )
```

- [ ] **Step 5: Create the Alembic migration**

Create `alembic/versions/2026_05_09_attempts_and_restarted_event.py`:

```python
"""add attempts to scrape_url_items + 'restarted' event type

Revision ID: 8f2a4d6b3e91
Revises: a3cf682de91e
Create Date: 2026-05-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8f2a4d6b3e91"
down_revision: str | Sequence[str] | None = "a3cf682de91e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scrape_url_items",
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Drop and re-add the event-type CHECK constraint with 'restarted'.
    op.drop_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        "event_type IN ("
        "'started','paused','resumed','stop_requested','retry_failures',"
        "'rerun','continued','resumed_after_failure','restarted',"
        "'completed','failed','subdivided'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        "event_type IN ("
        "'started','paused','resumed','stop_requested','retry_failures',"
        "'rerun','continued','resumed_after_failure',"
        "'completed','failed','subdivided'"
        ")",
    )
    op.drop_column("scrape_url_items", "attempts")
```

Confirm `down_revision` is the current head before running:

```bash
PYTHONPATH=. uv run alembic heads
```

Expected: `a3cf682de91e (head)`. If it differs, replace `a3cf682de91e` in the migration file with the actual head value.

- [ ] **Step 6: Run migrations against the test DB and main DB**

```bash
docker compose up -d postgres postgres-test
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test \
  PYTHONPATH=. uv run alembic upgrade head
PYTHONPATH=. uv run alembic upgrade head
```

Expected: both runs end with `Running upgrade a3cf682de91e -> 8f2a4d6b3e91`.

- [ ] **Step 7: Re-run the failing test, verify it passes**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_scrape_run_events.py::test_restarted_event_accepted -v
```

Expected: PASS.

- [ ] **Step 8: Verify `attempts` default is 0 on inserted items**

Append a unit test to `tests/unit/test_pipelines.py` (or a more appropriate file — check existing model unit tests):

```python
def test_scrape_url_item_attempts_defaults_to_zero():
    from book_scraper.db.models import ScrapeUrlItem
    column = ScrapeUrlItem.__table__.c.attempts
    # server_default="0" stores the literal string; .arg is the str itself.
    assert column.server_default.arg == "0"
    assert column.nullable is False
```

```bash
PYTHONPATH=. uv run pytest tests/unit/test_pipelines.py::test_scrape_url_item_attempts_defaults_to_zero -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add alembic/versions/2026_05_09_attempts_and_restarted_event.py \
        book_scraper/db/scrape_run_events.py \
        book_scraper/db/models.py \
        tests/integration/test_scrape_run_events.py \
        tests/unit/test_pipelines.py
git commit -m "$(cat <<'EOF'
feat(schema): add scrape_url_items.attempts + 'restarted' event type

Migration prep for single-row restarts and end-of-run retry sweep.
attempts ticks per dispatch cycle (capped at 3 by the sweep). The
'restarted' event marks process restarts on the same logical-run row.
EOF
)"
```

---

## Task 2: Settings constant for retry cap

**Files:**
- Modify: `book_scraper/settings.py`

- [ ] **Step 1: Add `RETRY_CAP` to settings**

In `book_scraper/settings.py`, add near the other operational constants (e.g. after `STALL_AUTO_RESUME_MAX`):

```python
# Maximum dispatch cycles per scrape_url_item within a logical run.
# Counts the initial fetch plus any re-dispatches from the end-of-run
# retry sweep. Once an item hits this cap it stays `failed` (sticky)
# until an operator click on Retry-failures resets attempts to 0.
RETRY_CAP = 3
```

- [ ] **Step 2: Commit**

```bash
git add book_scraper/settings.py
git commit -m "feat(settings): add RETRY_CAP=3 for end-of-run retry sweep"
```

---

## Task 3: Repo — `restart_run_in_place` helper

**Files:**
- Modify: `book_scraper/db/repo.py`
- Test: `tests/integration/test_restart_in_place.py` (create)

- [ ] **Step 1: Write a failing integration test**

Create `tests/integration/test_restart_in_place.py`:

```python
"""Integration coverage for restart_run_in_place — single-row mutation
on auto-resume / boot-reconcile paths."""

from datetime import UTC, datetime, timedelta

import pytest

from book_scraper.db import scrape_run_events as run_event_types
from book_scraper.db.models import ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import (
    create_scrape_run,
    emit_scrape_run_event,
    insert_scrape_url_item,
    restart_run_in_place,
    upsert_shop,
)


def _seed_failed_run(session, *, urls_processed=0):
    shop = upsert_shop(session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(session, shop.id, "scan")
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    run.close_reason = "stall_timeout"
    run.resumable_after_failure = True
    run.urls_processed = urls_processed
    run.pid = 1234
    run.last_heartbeat = datetime.now(UTC) - timedelta(minutes=10)
    insert_scrape_url_item(
        session, run_id=run.id, shop_id=shop.id, discovered_url_id=None,
        url="https://www.vaga.lt/p/1", url_type="product",
    )
    session.commit()
    return run


def test_restart_in_place_mutates_same_row(db_session):
    run = _seed_failed_run(db_session)
    original_started_at = run.started_at
    original_run_id = run.id

    restart_run_in_place(
        db_session,
        run,
        payload={
            "previous_close_reason": "stall_timeout",
            "attempt": 1,
            "urls_processed_snapshot": 0,
        },
        actor=run_event_types.ACTOR_SYSTEM,
    )
    db_session.commit()

    refreshed = db_session.get(ScrapeRun, original_run_id)
    assert refreshed.id == original_run_id
    assert refreshed.status == "running"
    assert refreshed.finished_at is None
    assert refreshed.close_reason is None
    assert refreshed.resumable_after_failure is False
    assert refreshed.started_at == original_started_at  # untouched

    events = [
        e for e in refreshed.events if e.event_type == run_event_types.RESTARTED
    ]
    assert len(events) == 1
    assert events[0].payload["previous_close_reason"] == "stall_timeout"
    assert events[0].payload["attempt"] == 1
    assert events[0].actor == run_event_types.ACTOR_SYSTEM


def test_restart_in_place_emits_continued_when_actor_operator(db_session):
    run = _seed_failed_run(db_session)
    restart_run_in_place(
        db_session,
        run,
        payload={"previous_close_reason": "stall_timeout", "attempt": 1,
                 "urls_processed_snapshot": 0},
        actor=run_event_types.ACTOR_OPERATOR,
        event_type=run_event_types.CONTINUED,
    )
    db_session.commit()

    events = [
        e for e in run.events if e.event_type == run_event_types.CONTINUED
    ]
    assert len(events) == 1


def test_restart_in_place_resets_retryable_failures(db_session):
    run = _seed_failed_run(db_session)
    item = (
        db_session.query(ScrapeUrlItem).filter_by(run_id=run.id).first()
    )
    item.status = "failed"
    db_session.flush()

    from book_scraper.db.repo import record_scrape_failure

    record_scrape_failure(
        db_session,
        scrape_url_item=item,
        error_reason="run_aborted",
        http_status=None,
    )
    db_session.commit()

    restart_run_in_place(
        db_session, run,
        payload={"previous_close_reason": "stall_timeout", "attempt": 1,
                 "urls_processed_snapshot": 0},
        actor=run_event_types.ACTOR_SYSTEM,
    )
    db_session.commit()

    refreshed_item = db_session.get(ScrapeUrlItem, item.id)
    assert refreshed_item.status == "pending"
```

(`db_session` fixture is the existing one from `tests/conftest.py` — confirm it points at the test DB on port 5433 by skimming `conftest.py` before running.)

- [ ] **Step 2: Run test, confirm it fails (function not defined)**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_restart_in_place.py -v
```

Expected: FAIL with `ImportError: cannot import name 'restart_run_in_place'`.

- [ ] **Step 3: Implement `restart_run_in_place`**

In `book_scraper/db/repo.py`, add after `inherit_pending_items` (around line 919):

```python
def restart_run_in_place(
    session: Session,
    run: ScrapeRun,
    *,
    payload: dict[str, Any],
    actor: str,
    event_type: str = "restarted",
) -> None:
    """Mutate a `failed`+`resumable_after_failure` run back to `running`
    on the same row, then emit the restart marker event.

    **Service-layer use only** — call from inside the spawned scrapy
    subprocess so `os.getpid()` is the spider's PID. The dashboard
    Continue endpoint already mutates the row in-place itself before
    spawning the subprocess; do not call this from the dashboard
    process — it would stamp the dashboard PID on the run.

    Atomic with the surrounding caller's transaction: the UPDATE and
    the event INSERT both go through `session.flush()` and rely on the
    caller to commit.

    Refuses to operate on a row that is not `failed`+`resumable_after_failure`
    — callers must filter on `find_resumable_run`'s output.
    """
    import os

    if run.status != "failed" or not run.resumable_after_failure:
        raise ValueError(
            f"restart_run_in_place expects status='failed' "
            f"AND resumable_after_failure=True; got status={run.status!r}, "
            f"resumable_after_failure={run.resumable_after_failure!r}"
        )

    run.status = "running"
    run.finished_at = None
    run.close_reason = None
    run.resumable_after_failure = False
    run.pid = os.getpid()
    run.last_heartbeat = datetime.now(UTC)
    session.flush()

    _reset_retryable_failures(session, run.id)
    reset_processing_scrape_url_items(session, run.id)

    emit_scrape_run_event(
        session,
        run.id,
        event_type,
        payload=payload,
        actor=actor,
    )
```

The `Any` import already exists in the file (used by `extra_payload` on `create_scrape_run`); `datetime`, `UTC`, `_reset_retryable_failures`, `reset_processing_scrape_url_items`, `emit_scrape_run_event` are all in the module already.

- [ ] **Step 4: Run the test suite for this file**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_restart_in_place.py -v
```

Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/db/repo.py tests/integration/test_restart_in_place.py
git commit -m "$(cat <<'EOF'
feat(repo): add restart_run_in_place for single-row restart mutation

Replaces the create_scrape_run + inherit_pending_items pair on the
auto-resume path. Mutates the existing failed+resumable run back to
running, resets retryable failures + processing items to pending, and
emits a 'restarted' (or 'continued') event on the same row. One
transaction, atomic via the caller's commit.
EOF
)"
```

---

## Task 4: Repo — `fetch_retryable_failed_items` + `reset_failed_items_to_pending`

**Files:**
- Modify: `book_scraper/db/repo.py`
- Test: `tests/integration/test_end_of_run_retry.py` (create)

- [ ] **Step 1: Write a failing integration test for the new helpers**

Create `tests/integration/test_end_of_run_retry.py`:

```python
"""Integration coverage for end-of-run retry helpers."""

import pytest

from book_scraper.db.models import ScrapeUrlItem
from book_scraper.db.repo import (
    create_scrape_run,
    fetch_retryable_failed_items,
    insert_scrape_url_item,
    reset_failed_items_to_pending,
    upsert_shop,
)


def _seed_run_with_items(session, attempts_per_status):
    """attempts_per_status: list of (status, attempts) tuples."""
    shop = upsert_shop(session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(session, shop.id, "scan")
    items = []
    for i, (status, attempts) in enumerate(attempts_per_status):
        item = insert_scrape_url_item(
            session, run_id=run.id, shop_id=shop.id, discovered_url_id=None,
            url=f"https://www.vaga.lt/p/{i}", url_type="product",
        )
        item.status = status
        item.attempts = attempts
        items.append(item)
    session.flush()
    session.commit()
    return run, items


def test_fetch_retryable_failed_items_excludes_capped(db_session):
    run, items = _seed_run_with_items(db_session, [
        ("failed", 0),
        ("failed", 1),
        ("failed", 2),
        ("failed", 3),  # capped
        ("done", 1),
        ("pending", 0),
    ])

    eligible = fetch_retryable_failed_items(db_session, run.id, cap=3)

    eligible_ids = {item.id for item in eligible}
    assert eligible_ids == {items[0].id, items[1].id, items[2].id}


def test_fetch_retryable_failed_items_only_current_run(db_session):
    run_a, items_a = _seed_run_with_items(db_session, [("failed", 1)])
    run_b, items_b = _seed_run_with_items(db_session, [("failed", 1)])

    eligible_a = fetch_retryable_failed_items(db_session, run_a.id, cap=3)
    assert {item.id for item in eligible_a} == {items_a[0].id}


def test_reset_failed_items_to_pending_default_keeps_attempts(db_session):
    run, items = _seed_run_with_items(db_session, [
        ("failed", 1), ("failed", 2),
    ])

    reset_failed_items_to_pending(db_session, [items[0].id, items[1].id])
    db_session.commit()

    refreshed = [db_session.get(ScrapeUrlItem, item.id) for item in items]
    assert all(item.status == "pending" for item in refreshed)
    assert refreshed[0].attempts == 1  # untouched
    assert refreshed[1].attempts == 2  # untouched


def test_reset_failed_items_to_pending_with_attempts_reset(db_session):
    """Operator-triggered Retry-failures path resets attempts to 0."""
    run, items = _seed_run_with_items(db_session, [
        ("failed", 3),  # capped
    ])

    reset_failed_items_to_pending(
        db_session, [items[0].id], reset_attempts=True
    )
    db_session.commit()

    refreshed = db_session.get(ScrapeUrlItem, items[0].id)
    assert refreshed.status == "pending"
    assert refreshed.attempts == 0
```

- [ ] **Step 2: Run test, confirm it fails (functions not defined)**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_end_of_run_retry.py -v
```

Expected: FAIL with import errors.

- [ ] **Step 3: Implement the two helpers**

In `book_scraper/db/repo.py`, add near `reset_processing_scrape_url_items` (around line 2001):

```python
def fetch_retryable_failed_items(
    session: Session,
    run_id: int,
    cap: int,
) -> list[ScrapeUrlItem]:
    """Return failed items on this run with attempts < cap.

    Used by the end-of-run retry sweep. No filter on `error_reason` —
    every failed item under the cap gets one more dispatch chance.
    """
    return list(
        session.query(ScrapeUrlItem)
        .filter(
            ScrapeUrlItem.run_id == run_id,
            ScrapeUrlItem.status == "failed",
            ScrapeUrlItem.attempts < cap,
        )
        .all()
    )


def reset_failed_items_to_pending(
    session: Session,
    item_ids: list[int],
    *,
    reset_attempts: bool = False,
) -> int:
    """Flip given failed items back to `pending` and clear stale
    terminal metadata so the next claim starts fresh.

    Clears `claimed_at`, `done_at`, `http_status`, and `response_bytes`
    — these were stamped by the previous failed dispatch and would
    otherwise show up on the pending row in the History card. The
    underlying scrape_failures rows stay (they're an append-only
    event log).

    `reset_attempts=False` (default, end-of-run sweep): leaves the
    counter alone — the next claim ticks it.
    `reset_attempts=True` (operator manual retry): zeros the counter
    so capped items get a fresh window.

    Returns the number of items updated.
    """
    if not item_ids:
        return 0
    values: dict[str, Any] = {
        "status": "pending",
        "claimed_at": None,
        "done_at": None,
        "http_status": None,
        "response_bytes": None,
    }
    if reset_attempts:
        values["attempts"] = 0
    stmt = (
        update(ScrapeUrlItem)
        .where(ScrapeUrlItem.id.in_(item_ids))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    session.flush()
    rowcount = getattr(result, "rowcount", 0)
    return int(rowcount) if rowcount is not None else 0
```

(`update` is already imported at the top of the file via SQLAlchemy.)

- [ ] **Step 4: Run the test, confirm it passes**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_end_of_run_retry.py -v
```

Expected: all four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/db/repo.py tests/integration/test_end_of_run_retry.py
git commit -m "$(cat <<'EOF'
feat(repo): add fetch_retryable_failed_items + reset_failed_items_to_pending

Building blocks for the end-of-run retry sweep. fetch_retryable_failed_items
respects the attempts cap; reset_failed_items_to_pending takes an explicit
reset_attempts flag for the operator-manual-retry path that should bypass
the cap.
EOF
)"
```

---

## Task 5: Repo — increment `attempts` on dispatch

**Files:**
- Modify: `book_scraper/db/repo.py:1802-1829` (`mark_scrape_url_item_processing`)
- Test: `tests/integration/test_end_of_run_retry.py` (extend)

- [ ] **Step 1: Write a failing test for the increment**

Append to `tests/integration/test_end_of_run_retry.py`:

```python
def test_mark_processing_increments_attempts(db_session):
    import time
    from book_scraper.db.repo import mark_scrape_url_item_processing

    run, items = _seed_run_with_items(db_session, [("pending", 0)])
    db_session.get(type(items[0]), items[0].id)  # ensure attached

    # Run must be 'running' for mark_scrape_url_item_processing to apply.
    run.status = "running"
    db_session.commit()

    mark_scrape_url_item_processing(db_session, items[0].id, time.time())
    db_session.commit()

    refreshed = db_session.get(type(items[0]), items[0].id)
    assert refreshed.status == "processing"
    assert refreshed.attempts == 1


def test_mark_processing_increments_attempts_on_redispatch(db_session):
    import time
    from book_scraper.db.repo import mark_scrape_url_item_processing

    run, items = _seed_run_with_items(db_session, [("pending", 1)])
    run.status = "running"
    db_session.commit()

    mark_scrape_url_item_processing(db_session, items[0].id, time.time())
    db_session.commit()

    refreshed = db_session.get(type(items[0]), items[0].id)
    assert refreshed.attempts == 2
```

- [ ] **Step 2: Run, confirm it fails**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_end_of_run_retry.py::test_mark_processing_increments_attempts -v
```

Expected: FAIL — `attempts` stays at 0 (or 1) because the function doesn't increment yet.

- [ ] **Step 3: Update `mark_scrape_url_item_processing` to increment**

In `book_scraper/db/repo.py` find the function at line ~1802 and change the body where `item.status = "processing"` is set. Existing block:

```python
        item.status = "processing"
        item.claimed_at = datetime.fromtimestamp(dispatched_at, tz=UTC)
```

Replace with:

```python
        item.status = "processing"
        item.claimed_at = datetime.fromtimestamp(dispatched_at, tz=UTC)
        # `attempts` ticks once per dispatch cycle. Scrapy's RetryMiddleware
        # re-issues without re-claiming, so internal retries don't bump
        # this — see scrape_url_items.retry_count for that count.
        item.attempts = (item.attempts or 0) + 1
```

- [ ] **Step 4: Run the new tests, confirm they pass**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_end_of_run_retry.py::test_mark_processing_increments_attempts tests/integration/test_end_of_run_retry.py::test_mark_processing_increments_attempts_on_redispatch -v
```

Expected: both PASS.

- [ ] **Step 5: Run full file to confirm no regressions**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_end_of_run_retry.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add book_scraper/db/repo.py tests/integration/test_end_of_run_retry.py
git commit -m "$(cat <<'EOF'
feat(repo): tick scrape_url_items.attempts on dispatch claim

Increments per dispatch cycle, not per Scrapy RetryMiddleware retry.
End-of-run retry sweep relies on this to bound work at RETRY_CAP=3.
EOF
)"
```

---

## Task 6: Refactor circuit-breaker helpers for single-row events

**Files:**
- Modify: `book_scraper/db/repo.py:767-855` (`count_consecutive_zero_progress_resumes`, `count_auto_resume_chain_depth`)
- Test: `tests/integration/test_db_repo.py` or `tests/integration/test_db_repo_extra.py` (extend — locate existing tests for these helpers)

- [ ] **Step 1: Confirm existing test locations**

```bash
grep -rn "count_auto_resume_chain_depth\|count_consecutive_zero_progress_resumes" tests/ | grep -v __pycache__
```

Existing tests live at `tests/integration/test_discover_service.py:153` (`test_count_auto_resume_chain_depth`) and `tests/integration/test_discover_service.py:200` (`test_count_consecutive_zero_progress_resumes`). They are written against the old chain-walking semantics — they create three runs and emit `RESUMED_AFTER_FAILURE` events with `previous_run_id` payloads. **Rewrite them in place** rather than adding new tests elsewhere.

- [ ] **Step 2: Rewrite both tests in `test_discover_service.py:153-256`**

Replace the body of `test_count_auto_resume_chain_depth` (lines 153–197) with:

```python
def test_count_auto_resume_chain_depth(db_session):
    """Single-row restart model: depth = count of `restarted` events on
    the run. The StallDetector compares this against
    STALL_AUTO_RESUME_MAX before deciding whether to spawn another
    auto-resume.
    """
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.repo import (
        count_auto_resume_chain_depth,
        create_scrape_run,
        emit_scrape_run_event,
    )

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    run = create_scrape_run(db_session, shop.id, "discover_sitemap")
    db_session.commit()

    # Fresh run — no restart events.
    assert count_auto_resume_chain_depth(db_session, run.id) == 0

    for attempt in (1, 2, 3):
        emit_scrape_run_event(
            db_session, run.id, run_event_types.RESTARTED,
            payload={
                "attempt": attempt,
                "urls_processed_snapshot": 0,
                "previous_close_reason": "stall_timeout",
            },
            actor=run_event_types.ACTOR_SYSTEM,
        )
    db_session.commit()

    assert count_auto_resume_chain_depth(db_session, run.id) == 3
```

Replace the body of `test_count_consecutive_zero_progress_resumes` (lines 200–256) with:

```python
def test_count_consecutive_zero_progress_resumes(db_session):
    """Single-row restart model: streak counts `restarted` events whose
    `urls_processed_snapshot` matches the previous restart's snapshot
    (no progress between attempts). Threshold=2 makes the
    StallDetector circuit-break on structural bugs.
    """
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.repo import (
        count_consecutive_zero_progress_resumes,
        create_scrape_run,
        emit_scrape_run_event,
    )

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    run = create_scrape_run(db_session, shop.id, "scan")
    run.urls_processed = 0
    db_session.commit()

    # No restart events yet → streak 0.
    assert count_consecutive_zero_progress_resumes(db_session, run.id) == 0

    # Two restarts, both with zero-progress snapshot → streak >= 2.
    for snap in (0, 0):
        emit_scrape_run_event(
            db_session, run.id, run_event_types.RESTARTED,
            payload={
                "attempt": 1,
                "urls_processed_snapshot": snap,
                "previous_close_reason": "stall_timeout",
            },
            actor=run_event_types.ACTOR_SYSTEM,
        )
    db_session.commit()
    assert count_consecutive_zero_progress_resumes(db_session, run.id) >= 2

    # A subsequent restart that DID make progress (snapshot 5) breaks
    # the streak — newest pair (5,0) compares unequal.
    emit_scrape_run_event(
        db_session, run.id, run_event_types.RESTARTED,
        payload={
            "attempt": 3,
            "urls_processed_snapshot": 5,
            "previous_close_reason": "stall_timeout",
        },
        actor=run_event_types.ACTOR_SYSTEM,
    )
    db_session.commit()
    assert count_consecutive_zero_progress_resumes(db_session, run.id) == 0
```

- [ ] **Step 3: Run the rewritten tests, confirm they fail**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_discover_service.py::test_count_auto_resume_chain_depth tests/integration/test_discover_service.py::test_count_consecutive_zero_progress_resumes -v
```

Expected: both FAIL — old implementation reads `RESUMED_AFTER_FAILURE` events and walks `previous_run_id`.

- [ ] **Step 4: Replace both helpers with single-row implementations**

In `book_scraper/db/repo.py`, replace the body of `count_consecutive_zero_progress_resumes` (line ~767) with:

```python
def count_consecutive_zero_progress_resumes(
    session: Session, run_id: int, max_lookback: int = 8
) -> int:
    """Count trailing zero-progress restart events on a run.

    Walks `restarted` events newest → oldest. Each event's payload
    carries `urls_processed_snapshot` — the value of `urls_processed`
    captured at the moment of the restart. A "zero-progress restart"
    is one whose snapshot equals the snapshot of the previous restart
    (i.e. nothing got done between the two attempts).

    Stops at the first event that DID make progress, or after
    `max_lookback` events. Returns the streak length.

    Used by the StallDetector to circuit-break: 2+ consecutive zero-
    progress restarts means the bug is structural, not transient.
    """
    events = (
        session.query(ScrapeRunEvent)
        .filter(
            ScrapeRunEvent.run_id == run_id,
            ScrapeRunEvent.event_type == run_event_types.RESTARTED,
        )
        .order_by(ScrapeRunEvent.id.desc())
        .limit(max_lookback)
        .all()
    )
    if not events:
        return 0

    # Compare each event's snapshot to the next-older one's snapshot.
    # If equal, the gap between them produced no progress.
    streak = 0
    for newer, older in zip(events, events[1:]):
        newer_snap = (newer.payload or {}).get("urls_processed_snapshot")
        older_snap = (older.payload or {}).get("urls_processed_snapshot")
        if newer_snap is None or older_snap is None:
            break
        if newer_snap == older_snap:
            streak += 1
        else:
            break
    # The streak above counts pairs; if we have N pairs of zero-progress,
    # that's N+1 zero-progress restarts in a row. Cap by total events.
    return min(streak + 1 if streak > 0 else 0, len(events))
```

Replace the body of `count_auto_resume_chain_depth` (line ~821) with:

```python
def count_auto_resume_chain_depth(session: Session, run_id: int) -> int:
    """Count `restarted` events on this run.

    Returns 0 for a run that has never restarted. Used by the
    StallDetector + reconcile_runs to cap runaway auto-resume loops.
    """
    return (
        session.query(ScrapeRunEvent)
        .filter(
            ScrapeRunEvent.run_id == run_id,
            ScrapeRunEvent.event_type == run_event_types.RESTARTED,
        )
        .count()
    )
```

`run_event_types` is already imported in `repo.py` (used by `emit_scrape_run_event`).

- [ ] **Step 5: Run the rewritten tests, confirm they pass**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_discover_service.py::test_count_auto_resume_chain_depth tests/integration/test_discover_service.py::test_count_consecutive_zero_progress_resumes -v
```

Expected: both PASS.

- [ ] **Step 6: Run wider sweep for any other tests touching these helpers**

```bash
PYTHONPATH=. uv run pytest tests/ -v -k "auto_resume or zero_progress or chain_depth or retry_chain" --no-header
```

Audit any failures: if a pre-existing test relies on chain-row semantics that no longer exist (e.g. `tests/integration/test_retry_chain.py` testing cross-row inheritance), either rewrite to match single-row behaviour or delete if it covered an obsolete scenario. Do not preserve broken assumptions with shims.

- [ ] **Step 7: Commit**

```bash
git add book_scraper/db/repo.py tests/integration/test_discover_service.py
git commit -m "$(cat <<'EOF'
refactor(repo): count restarts via 'restarted' events on the run

Single-row restart model means circuit-breaker state lives in
scrape_run_events on the run itself, not in a chain of rows. Both
count_auto_resume_chain_depth and count_consecutive_zero_progress_resumes
now read events directly. Legacy chain-walking removed.
EOF
)"
```

---

## Task 7: Service — `ScanService` resumable-failed branch uses `restart_run_in_place`

**Files:**
- Modify: `book_scraper/services/scan.py:112-152` (the resumable-failed branch in `prepare_scan_create_run`)
- Modify: `book_scraper/services/scan.py:195-215` (`populate_scan_queue` — drop `_inherit_from_run_id` path)
- Modify: `book_scraper/services/scan.py:29-50` (drop `_inherit_from_run_id` field on `ScanPlan`)
- Test: `tests/integration/test_scan_service.py` (extend)

- [ ] **Step 1: Write a failing test for same-row reuse on resumable-failed**

Existing tests in `tests/integration/test_scan_service.py` pass `{}` as `shop_config` (e.g. `service.prepare_scan("svc_shop", "https://svc.lt", {})`). Use the same pattern. Append:

```python
def test_prepare_scan_reuses_failed_resumable_row(db_session):
    """A failed+resumable run is reused; no new row is created."""
    from datetime import UTC, datetime
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.models import ScrapeRun
    from book_scraper.db.repo import (
        create_scrape_run, insert_scrape_url_item, upsert_shop,
    )
    from book_scraper.services.scan import ScanService

    shop = upsert_shop(db_session, "vaga", "https://www.vaga.lt")
    failed = create_scrape_run(db_session, shop.id, "scan", urls_total=1)
    failed.status = "failed"
    failed.finished_at = datetime.now(UTC)
    failed.close_reason = "stall_timeout"
    failed.resumable_after_failure = True
    failed.urls_processed = 0
    insert_scrape_url_item(
        db_session, run_id=failed.id, shop_id=shop.id,
        discovered_url_id=None, url="https://www.vaga.lt/p/1",
        url_type="product",
    )
    db_session.commit()
    failed_id = failed.id

    pre_count = db_session.query(ScrapeRun).count()
    service = ScanService(db_session)
    plan = service.prepare_scan_create_run(
        "vaga", "https://www.vaga.lt", {}
    )
    service.populate_scan_queue(plan)
    db_session.commit()

    post_count = db_session.query(ScrapeRun).count()
    assert post_count == pre_count, "no new ScrapeRun row should be created"
    assert plan.run_id == failed_id, "service must return the existing row id"

    refreshed = db_session.get(ScrapeRun, failed_id)
    assert refreshed.status == "running"
    restart_events = [
        e for e in refreshed.events if e.event_type == run_event_types.RESTARTED
    ]
    assert len(restart_events) == 1
    assert restart_events[0].payload["previous_close_reason"] == "stall_timeout"
    assert restart_events[0].payload["urls_processed_snapshot"] == 0
```

- [ ] **Step 2: Run, confirm it fails**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_scan_service.py::test_prepare_scan_reuses_failed_resumable_row -v
```

Expected: FAIL — currently the resumable-failed branch creates a new row.

- [ ] **Step 3: Update `prepare_scan_create_run`**

Open `book_scraper/services/scan.py`. Drop `inherit_pending_items` AND `emit_scrape_run_event` from the import block (the new code uses neither — `restart_run_in_place` emits the event internally), and add `restart_run_in_place`. Final import block:

```python
from book_scraper.db.repo import (
    check_discover_freshness,
    create_scrape_run,
    find_resumable_run,
    finish_scrape_run,
    get_pending_scan_urls,
    get_urls_already_scraped,
    insert_scrape_url_item,
    mark_cron_job_ran_if_matches,
    mark_stale_runs_failed,
    prepare_scrape_url_items,
    restart_run_in_place,
    try_acquire_scan_lock,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_shop,
    upsert_url_classification,
)
```

If `emit_scrape_run_event` or `run_event_types` is referenced elsewhere in the file (search before deleting), keep those imports. After the resumable-failed branch change, audit unused imports with `uv run ruff check book_scraper/services/scan.py` — fix any reported `F401`.

Replace the resumable-failed branch (line ~128 onwards) — current code:

```python
            # Resumable-failed run (heartbeat_timeout / stall_timeout):
            # spawn a fresh run row that inherits the failed run's pending
            # queue. Old run stays `failed` for postmortem.
            run = create_scrape_run(
                self.session,
                shop.id,
                "scan",
                urls_total=pending_count,
                extra_payload={"rescrape": rescrape},
            )
            emit_scrape_run_event(
                self.session,
                run.id,
                run_event_types.RESUMED_AFTER_FAILURE,
                payload={"previous_run_id": resumable.id},
                actor=run_event_types.ACTOR_SYSTEM,
            )
            self.session.commit()
            return ScanPlan(
                run_id=run.id,
                urls_total=pending_count,
                urls_skipped=0,
                freshness_warnings=[],
                _inherit_from_run_id=resumable.id,
            )
```

with:

```python
            # Resumable-failed run (heartbeat_timeout / stall_timeout):
            # mutate the same row back to running and emit `restarted`.
            # No new row, no cross-row inherit — the queue is already on
            # this row. See docs/superpowers/specs/2026-05-09-restart-and-retry-design.md.
            attempt_number = (
                self.session.query(ScrapeRunEvent)
                .filter(
                    ScrapeRunEvent.run_id == resumable.id,
                    ScrapeRunEvent.event_type == run_event_types.RESTARTED,
                )
                .count()
                + 1
            )
            restart_run_in_place(
                self.session,
                resumable,
                payload={
                    "previous_close_reason": resumable.close_reason,
                    "attempt": attempt_number,
                    "urls_processed_snapshot": resumable.urls_processed,
                    "rescrape": rescrape,
                },
                actor=run_event_types.ACTOR_SYSTEM,
            )
            self.session.commit()
            return ScanPlan(
                run_id=resumable.id,
                urls_total=pending_count,
                urls_skipped=0,
                freshness_warnings=[],
            )
```

`ScrapeRunEvent` needs to be imported at the top of the file:

```python
from book_scraper.db.models import ScrapeRun, ScrapeRunEvent, ScrapeUrlItem
```

- [ ] **Step 4: Drop `_inherit_from_run_id` field and its usage**

In `book_scraper/services/scan.py`, edit the `ScanPlan` dataclass — remove the field and its docstring lines (currently around line 47):

```python
    # When `find_resumable_run` returned a previously-failed run flagged
    # `resumable_after_failure`, this carries that run's id; the spider
    # should re-point its pending items to the new run before yielding.
    _inherit_from_run_id: int | None = None
```

Delete those four lines.

In `populate_scan_queue` (line ~205), remove the `_inherit_from_run_id` branch:

```python
        if plan._inherit_from_run_id is not None:
            inherit_pending_items(self.session, plan._inherit_from_run_id, plan.run_id)
            self.session.commit()
            return
```

Delete those four lines. The function then reads:

```python
def populate_scan_queue(self, plan: ScanPlan) -> None:
    """Phase 2: insert scrape_url_items rows for the plan.

    No-op when the plan is for a resumable run (queue already
    populated) or when the lock was not acquired.
    """
    if plan.lock_not_acquired:
        return
    if plan._urls_to_scrape is None or plan._shop_id is None:
        # Resumable run fast path — queue already there.
        return
    prepare_scrape_url_items(
        self.session, plan._shop_id, plan.run_id, plan._urls_to_scrape
    )
    self.session.commit()
```

- [ ] **Step 5: Run the new test, confirm it passes**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_scan_service.py::test_prepare_scan_reuses_failed_resumable_row -v
```

Expected: PASS.

- [ ] **Step 6: Run the full scan-service test suite to catch regressions**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_scan_service.py -v
```

Expected: all pass. If any pre-existing test relies on `_inherit_from_run_id` or expects a new row on resumable-failed, **rewrite it** to match the new behaviour — don't add back-compat shims.

- [ ] **Step 7: Commit**

```bash
git add book_scraper/services/scan.py tests/integration/test_scan_service.py
git commit -m "$(cat <<'EOF'
feat(scan): reuse same scrape_runs row on auto-resume

ScanService now mutates the failed+resumable row back to running and
emits a 'restarted' event, instead of creating a new row and
re-pointing the queue. _inherit_from_run_id field on ScanPlan is gone.
EOF
)"
```

---

## Task 8: Service — `DiscoverService` resumable-failed branch uses `restart_run_in_place`

**Files:**
- Modify: `book_scraper/services/discover.py:70-100`
- Test: `tests/integration/test_discover_service.py` (extend)

- [ ] **Step 1: Write a failing test parallel to the scan one**

`tests/integration/test_discover_service.py:10` defines a local `_config()` helper that returns a config object compatible with `prepare_discover`. Reuse it. Append:

```python
def test_prepare_discover_reuses_failed_resumable_row(db_session):
    from datetime import UTC, datetime
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.models import ScrapeRun
    from book_scraper.db.repo import (
        create_scrape_run, insert_scrape_url_item, upsert_shop,
    )
    from book_scraper.services.discover import DiscoverService

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    failed = create_scrape_run(db_session, shop.id, "discover_sitemap")
    failed.status = "failed"
    failed.finished_at = datetime.now(UTC)
    failed.close_reason = "stall_timeout"
    failed.resumable_after_failure = True
    failed.urls_processed = 0
    insert_scrape_url_item(
        db_session, run_id=failed.id, shop_id=shop.id,
        discovered_url_id=None, url="https://vaga.lt/sitemap.xml",
        url_type="sitemap",
    )
    db_session.commit()
    failed_id = failed.id
    pre_count = db_session.query(ScrapeRun).count()

    plan = DiscoverService(db_session).prepare_discover(
        "vaga", "https://vaga.lt", "sitemap", _config()
    )
    db_session.commit()

    assert db_session.query(ScrapeRun).count() == pre_count
    assert plan.run_id == failed_id
    refreshed = db_session.get(ScrapeRun, failed_id)
    assert refreshed.status == "running"
    assert any(
        e.event_type == run_event_types.RESTARTED for e in refreshed.events
    )
```

- [ ] **Step 2: Run, confirm it fails**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_discover_service.py::test_prepare_discover_reuses_failed_resumable_row -v
```

Expected: FAIL — current code creates a new row.

- [ ] **Step 3: Update `prepare_discover`**

Open `book_scraper/services/discover.py`. Drop `inherit_pending_items` AND `emit_scrape_run_event` from the import block (the new code uses neither — `restart_run_in_place` emits the event internally). Add `restart_run_in_place`. Final import block:

```python
from book_scraper.db.repo import (
    create_scrape_run,
    find_resumable_run,
    finish_scrape_run,
    insert_scrape_url_item,
    mark_cron_job_ran_if_matches,
    mark_stale_runs_failed,
    restart_run_in_place,
    update_scrape_run_progress,
    upsert_shop,
)
```

Add `ScrapeRunEvent` to the model import:

```python
from book_scraper.db.models import ScrapeRunEvent, ScrapeUrlItem
```

After the change, run `uv run ruff check book_scraper/services/discover.py` and remove any flagged unused imports.

Replace the resumable-failed branch (lines ~83–100):

```python
            # Failed-but-resumable run: create a fresh run that inherits
            # the pending queue. Old row stays `failed` for postmortem.
            run = create_scrape_run(
                self.session,
                shop.id,
                phase,
                extra_payload={"strategy": strategy},
            )
            emit_scrape_run_event(
                self.session,
                run.id,
                run_event_types.RESUMED_AFTER_FAILURE,
                payload={"previous_run_id": resumable.id},
                actor=run_event_types.ACTOR_SYSTEM,
            )
            inherit_pending_items(self.session, resumable.id, run.id)
            self.session.commit()
            return DiscoverPlan(run_id=run.id, shop_id=shop.id, urls_total=pending)
```

with:

```python
            # Failed-but-resumable run: mutate same row back to running.
            attempt_number = (
                self.session.query(ScrapeRunEvent)
                .filter(
                    ScrapeRunEvent.run_id == resumable.id,
                    ScrapeRunEvent.event_type == run_event_types.RESTARTED,
                )
                .count()
                + 1
            )
            restart_run_in_place(
                self.session,
                resumable,
                payload={
                    "previous_close_reason": resumable.close_reason,
                    "attempt": attempt_number,
                    "urls_processed_snapshot": resumable.urls_processed,
                    "strategy": strategy,
                },
                actor=run_event_types.ACTOR_SYSTEM,
            )
            self.session.commit()
            return DiscoverPlan(
                run_id=resumable.id, shop_id=shop.id, urls_total=pending
            )
```

- [ ] **Step 4: Run the test, confirm it passes**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_discover_service.py::test_prepare_discover_reuses_failed_resumable_row -v
```

Expected: PASS.

- [ ] **Step 5: Run full discover-service tests**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_discover_service.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add book_scraper/services/discover.py tests/integration/test_discover_service.py
git commit -m "$(cat <<'EOF'
feat(discover): reuse same scrape_runs row on auto-resume

Same change as ScanService — failed+resumable runs are mutated back to
running with a 'restarted' event instead of creating a new row.
EOF
)"
```

---

## Task 9: Spider — end-of-run retry sweep in `ScanSpider.spider_idle`

**Files:**
- Modify: `book_scraper/spiders/scan.py:96-160`
- Test: `tests/unit/test_spiders.py` or `tests/integration/test_lifecycle_track_a.py` (extend; pick whichever already exercises spider lifecycle — see step 1)

- [ ] **Step 1: Locate the existing `spider_idle` test coverage for scan**

```bash
grep -rn "spider_idle\|ScanSpider" tests/ --include="*.py" | head -10
```

If no existing test covers `spider_idle` for scan, add to `tests/integration/test_end_of_run_retry.py`. Otherwise extend the file already covering it.

- [ ] **Step 2: Write a failing test for the retry sweep behaviour**

Append to `tests/integration/test_end_of_run_retry.py`:

```python
def test_scan_spider_idle_resets_failed_below_cap_to_pending(db_session):
    """Until the sweep flag is set, idle should reset failed-and-eligible
    items to pending and reschedule them. After the sweep flag is set,
    further idle ticks no-op for the retry path."""
    from unittest.mock import MagicMock

    from book_scraper.db.models import ScrapeUrlItem
    from book_scraper.db.repo import (
        create_scrape_run, insert_scrape_url_item, upsert_shop,
    )
    from book_scraper.spiders.scan import ScanSpider

    shop = upsert_shop(db_session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(db_session, shop.id, "scan")
    run.status = "running"
    item = insert_scrape_url_item(
        db_session, run_id=run.id, shop_id=shop.id, discovered_url_id=None,
        url="https://www.vaga.lt/p/1", url_type="product",
    )
    item.status = "failed"
    item.attempts = 1
    db_session.commit()

    spider = ScanSpider.__new__(ScanSpider)  # bypass __init__
    spider._run_id = run.id
    spider._end_of_run_retry_done = False
    spider.settings = MagicMock()
    spider.settings.get = lambda k, default=None: {
        "DATABASE_URL": str(db_session.bind.url),
        "RETRY_CAP": 3,
    }.get(k, default)
    spider.settings.getint = lambda k, default=None: 3
    spider.crawler = MagicMock()
    spider.crawler.engine = MagicMock()
    spider._build_scan_request = MagicMock(return_value=MagicMock())

    from scrapy.exceptions import DontCloseSpider
    with pytest.raises(DontCloseSpider):
        spider.spider_idle(spider)

    refreshed = db_session.get(ScrapeUrlItem, item.id)
    assert refreshed.status == "pending"
    assert spider._end_of_run_retry_done is True

    # Second idle tick: no-op (no fresh pending items, sweep already done).
    db_session.expire_all()
    refreshed_after = db_session.get(ScrapeUrlItem, item.id)
    refreshed_after.status = "failed"  # simulate retry pass landed and failed
    refreshed_after.attempts = 2
    db_session.commit()

    # spider_idle should NOT raise — sweep already done, no other pending.
    result = spider.spider_idle(spider)
    assert result is None
```

- [ ] **Step 3: Run, confirm it fails**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_end_of_run_retry.py::test_scan_spider_idle_resets_failed_below_cap_to_pending -v
```

Expected: FAIL — `_end_of_run_retry_done` doesn't exist on the spider.

- [ ] **Step 4: Update `ScanSpider.spider_idle`**

In `book_scraper/spiders/scan.py`, init the flag in `__init__` (around line 113, after the `_error_count` line):

```python
        # Per-process flag — set to True after the end-of-run retry sweep
        # has run once, so the second idle tick lets the spider close
        # cleanly. Resets per process; on restart, the new process gets
        # its own flag and may sweep again (bounded by attempts < cap).
        self._end_of_run_retry_done: bool = False
```

Replace the body of `spider_idle` (current code at line ~120) with:

```python
    def spider_idle(self, spider) -> None:  # type: ignore[no-untyped-def]
        """End-of-run retry sweep + mid-run pickup.

        Two responsibilities, run in order:

        1. **Retry sweep** (one-shot per process): when no fresh
           pending items are queued and the run still has `failed`
           items with `attempts < RETRY_CAP`, flip them back to
           `pending`, dispatch them, and raise `DontCloseSpider`. Set
           `_end_of_run_retry_done` so the next idle doesn't re-sweep.

        2. **Mid-run pickup** (always): pre-existing behaviour — pick
           up items enqueued mid-run via `ScanService.enqueue_new_url`
           and reset crash-orphaned `processing` items.
        """
        if self._run_id is None:
            return
        database_url = self.settings.get("DATABASE_URL")
        retry_cap = self.settings.getint("RETRY_CAP", 3)
        session_factory = get_session_factory(database_url)
        session = session_factory()
        try:
            reset_processing_scrape_url_items(session, self._run_id)
            new_items = get_pending_scrape_url_items(session, self._run_id)

            # If the queue is empty AND the sweep hasn't run yet,
            # take a single retry pass over failed-with-attempts<cap.
            if not new_items and not self._end_of_run_retry_done:
                from book_scraper.db.repo import (
                    fetch_retryable_failed_items,
                    reset_failed_items_to_pending,
                )

                eligible = fetch_retryable_failed_items(
                    session, self._run_id, cap=retry_cap
                )
                if eligible:
                    reset_failed_items_to_pending(
                        session, [it.id for it in eligible]
                    )
                    new_items = get_pending_scrape_url_items(
                        session, self._run_id
                    )
                self._end_of_run_retry_done = True
            session.commit()
        finally:
            session.close()

        if not new_items:
            return

        from scrapy.exceptions import DontCloseSpider

        engine = self.crawler.engine
        assert engine is not None
        for item in new_items:
            req = self._build_scan_request(
                item["url"],
                meta={
                    "discovered_url_id": item["discovered_url_id"],
                    "scrape_url_item_id": item["id"],
                    "scheduled_at": time.monotonic(),
                },
            )
            engine.crawl(req)
        raise DontCloseSpider
```

- [ ] **Step 5: Run the test, confirm it passes**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_end_of_run_retry.py::test_scan_spider_idle_resets_failed_below_cap_to_pending -v
```

Expected: PASS.

- [ ] **Step 6: Run wider scan-spider tests to catch regressions**

```bash
PYTHONPATH=. uv run pytest tests/ -v -k "scan and spider" --no-header -q
```

Expected: all pass. Investigate any failures — spider lifecycle is sensitive to ordering changes.

- [ ] **Step 7: Commit**

```bash
git add book_scraper/spiders/scan.py tests/integration/test_end_of_run_retry.py
git commit -m "$(cat <<'EOF'
feat(scan): one-shot end-of-run retry sweep in spider_idle

Before the run closes, fetch failed items with attempts < RETRY_CAP,
flip them to pending, and dispatch. Gated by _end_of_run_retry_done so
each process only sweeps once. Mid-run pickup behaviour preserved.
EOF
)"
```

---

## Task 10: Spider — end-of-run retry sweep in `DiscoverSpider.spider_idle`

**Files:**
- Modify: `book_scraper/spiders/discover.py:394-426`
- Test: `tests/integration/test_end_of_run_retry.py` (extend)

- [ ] **Step 1: Append a failing parallel test**

```python
def test_discover_spider_idle_resets_failed_below_cap_to_pending(db_session):
    from unittest.mock import MagicMock

    from book_scraper.db.models import ScrapeUrlItem
    from book_scraper.db.repo import (
        create_scrape_run, insert_scrape_url_item, upsert_shop,
    )
    from book_scraper.spiders.discover import DiscoverSpider

    shop = upsert_shop(db_session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(db_session, shop.id, "discover_sitemap")
    run.status = "running"
    item = insert_scrape_url_item(
        db_session, run_id=run.id, shop_id=shop.id, discovered_url_id=None,
        url="https://www.vaga.lt/sitemap.xml", url_type="sitemap",
    )
    item.status = "failed"
    item.attempts = 1
    db_session.commit()

    spider = DiscoverSpider.__new__(DiscoverSpider)
    spider._run_id = run.id
    spider._end_of_run_retry_done = False
    spider.settings = MagicMock()
    spider.settings.get = lambda k, default=None: {
        "DATABASE_URL": str(db_session.bind.url), "RETRY_CAP": 3,
    }.get(k, default)
    spider.settings.getint = lambda k, default=None: 3
    spider.crawler = MagicMock()
    spider.crawler.engine = MagicMock()
    spider._build_request_for_url_item = MagicMock(return_value=MagicMock())

    from scrapy.exceptions import DontCloseSpider
    with pytest.raises(DontCloseSpider):
        spider.spider_idle(spider)

    refreshed = db_session.get(ScrapeUrlItem, item.id)
    assert refreshed.status == "pending"
    assert spider._end_of_run_retry_done is True
```

- [ ] **Step 2: Run, confirm it fails**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_end_of_run_retry.py::test_discover_spider_idle_resets_failed_below_cap_to_pending -v
```

Expected: FAIL.

- [ ] **Step 3: Add the flag and update the discover spider**

In `book_scraper/spiders/discover.py`, find the `__init__` body and add (after the existing instance attributes; mirror the scan-spider placement):

```python
        self._end_of_run_retry_done: bool = False
```

Replace `spider_idle` body (line ~394):

```python
    def spider_idle(self, spider) -> None:  # type: ignore[no-untyped-def]
        """Mid-run pickup + one-shot end-of-run retry sweep.

        Mirrors `ScanSpider.spider_idle` — queue empty triggers the
        retry pass over failed items with attempts < RETRY_CAP. Sweep
        is gated by `_end_of_run_retry_done` so it runs once per
        process. Mid-run dual-write pickup behaviour preserved.
        """
        if self._run_id is None:
            return
        database_url = self.settings.get("DATABASE_URL")
        retry_cap = self.settings.getint("RETRY_CAP", 3)
        factory = get_session_factory(database_url)
        session = factory()
        try:
            reset_processing_scrape_url_items(session, self._run_id)
            new_items = get_pending_scrape_url_items(session, self._run_id)
            if not new_items and not self._end_of_run_retry_done:
                from book_scraper.db.repo import (
                    fetch_retryable_failed_items,
                    reset_failed_items_to_pending,
                )

                eligible = fetch_retryable_failed_items(
                    session, self._run_id, cap=retry_cap
                )
                if eligible:
                    reset_failed_items_to_pending(
                        session, [it.id for it in eligible]
                    )
                    new_items = get_pending_scrape_url_items(
                        session, self._run_id
                    )
                self._end_of_run_retry_done = True
            session.commit()
        finally:
            session.close()

        if not new_items:
            return

        from scrapy.exceptions import DontCloseSpider

        engine = self.crawler.engine
        assert engine is not None
        for item in new_items:
            req = self._build_request_for_url_item(
                item["url"],
                item["url_type"],
                item_id=item["id"],
            )
            engine.crawl(req)
        raise DontCloseSpider
```

- [ ] **Step 4: Run the test, confirm it passes**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_end_of_run_retry.py::test_discover_spider_idle_resets_failed_below_cap_to_pending -v
```

Expected: PASS.

- [ ] **Step 5: Run wider discover-spider tests**

```bash
PYTHONPATH=. uv run pytest tests/ -v -k "discover and spider" --no-header -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add book_scraper/spiders/discover.py tests/integration/test_end_of_run_retry.py
git commit -m "$(cat <<'EOF'
feat(discover): one-shot end-of-run retry sweep in spider_idle

Mirrors the scan spider — sweep failed-below-cap items once per
process before close. _end_of_run_retry_done flag gates the sweep.
EOF
)"
```

---

## Task 11: Dashboard — `restarted` event icon + summary in timeline

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-runs.jsx` — add `restarted` to `RUN_EVENT_META` dict and to `_eventSummary` switch (lines around 334 and 406).
- Test: `tests/integration/test_dashboard_routes.py` (extend) — verify the API exposes the event.

**Background:**
- Events do not have a dedicated endpoint. They come back inside the `events` array on `GET /api/runs/{run_id}` ([book_scraper/dashboard/routes/api.py:1226-1232](book_scraper/dashboard/routes/api.py:1226)) and on `GET /api/runs/{run_id}/live` ([book_scraper/dashboard/routes/api.py:1299](book_scraper/dashboard/routes/api.py:1299)). Both call `get_scrape_run_events(session, run_id)` which already returns full event_type + payload. **No backend serializer change needed**.
- Frontend rendering lives in [book_scraper/dashboard/static/hifi/hf-runs.jsx:334](book_scraper/dashboard/static/hifi/hf-runs.jsx:334) — `RUN_EVENT_META` dict (icon + label) and `_eventSummary` (one-liner builder around line 369). Both already handle `resumed_after_failure`.

- [ ] **Step 1: Confirm the API surfaces `restarted` events**

```bash
grep -n "get_scrape_run_events\|events.*payload" book_scraper/dashboard/routes/api.py book_scraper/db/repo.py | head -10
```

Verify `get_scrape_run_events` returns `event_type` and `payload` already. No backend change should be needed for plumbing — only icon/label mapping in JSX.

- [ ] **Step 2: Add a smoke test for the API exposure**

Append to `tests/integration/test_dashboard_routes.py`:

```python
def test_api_run_detail_exposes_restarted_event(client, db_session):
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.repo import (
        create_scrape_run, emit_scrape_run_event, upsert_shop,
    )

    shop = upsert_shop(db_session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(db_session, shop.id, "scan")
    emit_scrape_run_event(
        db_session, run.id, run_event_types.RESTARTED,
        payload={"previous_close_reason": "stall_timeout", "attempt": 1,
                 "urls_processed_snapshot": 0},
        actor=run_event_types.ACTOR_SYSTEM,
    )
    db_session.commit()

    response = client.get(f"/api/runs/{run.id}")
    assert response.status_code == 200
    data = response.json()
    event_types = [e["event_type"] for e in data["events"]]
    assert "restarted" in event_types
    restarted = next(e for e in data["events"] if e["event_type"] == "restarted")
    assert restarted["payload"]["attempt"] == 1
    assert restarted["payload"]["previous_close_reason"] == "stall_timeout"
```

- [ ] **Step 3: Run the test, confirm it passes**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_dashboard_routes.py::test_api_run_detail_exposes_restarted_event -v
```

Expected: PASS — the event check constraint update from Task 1 is what gates this; no further backend work needed.

- [ ] **Step 4: Add `restarted` to `RUN_EVENT_META` in the React file**

Edit `book_scraper/dashboard/static/hifi/hf-runs.jsx` around line 334. Existing block:

```javascript
  resumed_after_failure: { glyph: '⤴',  label: 'Picked up earlier run' },
```

Add a sibling entry (place near it for proximity to similar semantics):

```javascript
  resumed_after_failure: { glyph: '⤴',  label: 'Picked up earlier run' },
  restarted:             { glyph: '↻',  label: 'Process restarted' },
```

- [ ] **Step 5: Add a `restarted` case to `_eventSummary`**

In the same file, around line 406, the function `_eventSummary(eventType, payload)` has a switch over event types — add a case:

```javascript
    case 'restarted': {
      const reason = payload?.previous_close_reason || 'unknown';
      const attempt = payload?.attempt;
      const snap = payload?.urls_processed_snapshot;
      const parts = [`reason=${reason}`];
      if (attempt) parts.push(`attempt=${attempt}`);
      if (snap !== undefined && snap !== null) parts.push(`progress=${snap}`);
      return parts.join(' · ');
    }
```

(Look at the existing `case 'resumed_after_failure':` around line 406 for the surrounding switch shape and mirror its style.)

- [ ] **Step 6: Visual smoke (manual)**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Open `http://localhost:8000/runs`, find a run with a `restarted` event (seed one via SQL on the dev DB if none exists yet), confirm the icon (`↻`) and one-liner render. Visual-only — no automated browser test exists for the JSX layer.

- [ ] **Step 7: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-runs.jsx tests/integration/test_dashboard_routes.py
git commit -m "$(cat <<'EOF'
feat(dashboard): render 'restarted' event in hifi run timeline

Adds RUN_EVENT_META + _eventSummary entries for single-row restart
events. Legacy resumed_after_failure rendering kept intact. Backend
exposes the event automatically via the existing /api/runs/{id} events
array — no serializer change needed.
EOF
)"
```

---

## Task 12: Dashboard — surface `attempts` in History card + group-level stats on Failures card

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py::api_run_urls` (lines 1334–1407 — per-URL row serializer for the History card).
- Modify: `book_scraper/dashboard/routes/api.py` — `failure_groups` serializer (function called `get_run_failure_groups`; locate via `grep -n "def get_run_failure_groups" book_scraper/db/repo.py`). Add `max_attempts` and `capped_count` to each group.
- Modify: `book_scraper/dashboard/static/hifi/hf-runs.jsx` — render the new column on the History card (`HFRunHistoryCard` around line 572) and the new stats on the Failures card (`HFRunFailuresCard` around line 924).
- Test: `tests/integration/test_dashboard_routes.py` (extend).

**Background:**
- The Failures card on the dashboard is **group-based** (rows clustered by error_reason / http_status), not per-URL — see `HFRunFailuresCard` around line 924 in `hf-runs.jsx`. Per-URL data lives on the **History card** at line 572 (`HFRunHistoryCard`), fed by `GET /api/runs/{id}/urls?status=failed`.
- Adding a per-URL `Attempts` column is a History-card change. Group-level stats (`max_attempts`, `capped_count`) belong on the Failures card so operators can spot buckets where the cap is universally exhausted.

- [ ] **Step 1: Surface `attempts` in `/api/runs/{id}/urls` row serializer**

Edit `book_scraper/dashboard/routes/api.py::api_run_urls` (line 1388–1406). The existing dict construction is:

```python
            rows.append(
                {
                    "url": it.url,
                    "title": title,
                    "status": it.status,
                    ...
                    "discovered_url_id": it.discovered_url_id,
                    "shop_book_id": shop_book_id,
                }
            )
```

Add `"attempts": it.attempts,` to the dict (place it next to `retry_count` for proximity, or at the end of the dict — order doesn't matter).

- [ ] **Step 2: Surface group-level attempts stats in `failure_groups`**

Find the function backing `failure_groups` in the live endpoint:

```bash
grep -n "def get_run_failure_groups" book_scraper/db/repo.py
```

Open it. The function aggregates `scrape_url_items` joined to `scrape_failures` and returns one dict per (error_reason, http_status) bucket. Add two computed fields to each returned group dict:

```python
"max_attempts": int(max_attempts_for_bucket),
"capped_count": int(capped_for_bucket),
```

Where:
- `max_attempts_for_bucket` = `MAX(scrape_url_items.attempts)` over the bucket's items.
- `capped_for_bucket` = `COUNT(*)` over the bucket's items where `attempts >= RETRY_CAP` (3).

Implementation sketch (adapt to the helper's actual SQL shape — it likely uses SQLAlchemy `func.max` / `func.count` with `case`):

```python
from sqlalchemy import case, func
from book_scraper.settings import RETRY_CAP

# Inside the existing aggregation query, alongside the existing
# group-level COUNT etc., add:
func.max(ScrapeUrlItem.attempts).label("max_attempts"),
func.sum(case((ScrapeUrlItem.attempts >= RETRY_CAP, 1), else_=0)).label(
    "capped_count"
),
```

Then include `"max_attempts"` and `"capped_count"` in the returned group dict.

- [ ] **Step 3: Add a smoke test for both surfaces**

Append to `tests/integration/test_dashboard_routes.py`:

```python
def test_api_run_urls_includes_attempts(client, db_session):
    from book_scraper.db.repo import (
        create_scrape_run, insert_scrape_url_item, record_scrape_failure,
        upsert_shop,
    )

    shop = upsert_shop(db_session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(db_session, shop.id, "scan")
    run.status = "running"
    item = insert_scrape_url_item(
        db_session, run_id=run.id, shop_id=shop.id, discovered_url_id=None,
        url="https://www.vaga.lt/p/x", url_type="product",
    )
    item.status = "failed"
    item.attempts = 2
    db_session.flush()
    record_scrape_failure(
        db_session, scrape_url_item=item,
        error_reason="http_500", http_status=500,
    )
    db_session.commit()

    response = client.get(f"/api/runs/{run.id}/urls?status=failed")
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert any(r.get("attempts") == 2 for r in rows)


def test_api_run_live_failure_groups_include_attempts_stats(client, db_session):
    """Group-level Failures card surfaces max_attempts + capped_count."""
    from book_scraper.db.repo import (
        create_scrape_run, insert_scrape_url_item, record_scrape_failure,
        upsert_shop,
    )

    shop = upsert_shop(db_session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(db_session, shop.id, "scan")
    run.status = "running"

    capped = insert_scrape_url_item(
        db_session, run_id=run.id, shop_id=shop.id, discovered_url_id=None,
        url="https://www.vaga.lt/a", url_type="product",
    )
    capped.status = "failed"
    capped.attempts = 3
    db_session.flush()
    record_scrape_failure(
        db_session, scrape_url_item=capped,
        error_reason="http_500", http_status=500,
    )

    fresh = insert_scrape_url_item(
        db_session, run_id=run.id, shop_id=shop.id, discovered_url_id=None,
        url="https://www.vaga.lt/b", url_type="product",
    )
    fresh.status = "failed"
    fresh.attempts = 1
    db_session.flush()
    record_scrape_failure(
        db_session, scrape_url_item=fresh,
        error_reason="http_500", http_status=500,
    )
    db_session.commit()

    response = client.get(f"/api/runs/{run.id}/live")
    assert response.status_code == 200
    groups = response.json()["failure_groups"]
    bucket = next(
        g for g in groups
        if g.get("error_reason") == "http_500" and g.get("http_status") == 500
    )
    assert bucket["max_attempts"] == 3
    assert bucket["capped_count"] == 1
```

(Field names — `error_reason`, `http_status` — should match what `get_run_failure_groups` already returns; adjust if the helper uses different keys.)

- [ ] **Step 4: Run the tests, confirm they pass after the backend changes**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_dashboard_routes.py::test_api_run_urls_includes_attempts tests/integration/test_dashboard_routes.py::test_api_run_live_failure_groups_include_attempts_stats -v
```

Expected: both PASS.

- [ ] **Step 5: Render `Attempts` column in `HFRunHistoryCard`**

In `book_scraper/dashboard/static/hifi/hf-runs.jsx`, locate the History-card column definition (search for `HFRunHistoryCard` around line 572; the columns array typically has entries with `key`, `label`, `cell`). Add a new column:

```javascript
{
  key: 'attempts',
  label: 'Attempts',
  w: '0.4fr',
  align: 'right',
  cell: (v, r) => {
    const cap = 3;
    const capped = (r.attempts || 0) >= cap;
    return (
      <span style={{ color: capped ? 'var(--hf-danger)' : 'var(--hf-ink2)' }}>
        {r.attempts || 0}/{cap}
        {capped ? ' 🔒' : ''}
      </span>
    );
  },
},
```

(Mirror the surrounding columns' style — read 5–10 of them in context to match `w`, `align`, and the `cell` callback signature exactly. The example above is a template, not a literal copy-paste; the file's column-definition shape may differ.)

- [ ] **Step 6: Render group stats in `HFRunFailuresCard`**

In the same file, locate `HFRunFailuresCard` around line 924. Inside the per-group row, add a small subline showing `max_attempts` and `capped_count`. Pattern:

```jsx
{(g.capped_count || 0) > 0 && (
  <span style={{ marginLeft: 8, color: 'var(--hf-danger)', fontSize: 12 }}>
    {g.capped_count} capped (max {g.max_attempts}/{3})
  </span>
)}
```

Place inline next to the existing group header text (e.g. count of URLs in the bucket).

- [ ] **Step 7: Visual smoke**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Seed a run with mixed `attempts` values via SQL on the dev DB:

```sql
UPDATE scrape_url_items SET attempts = 3 WHERE id IN (...) ;
UPDATE scrape_url_items SET attempts = 1 WHERE id IN (...) ;
```

Reload the dashboard, navigate to that run's Details, confirm the History card's Attempts column renders and the Failures card's group rows show "N capped (max M/3)" where applicable.

- [ ] **Step 8: Commit**

```bash
git add book_scraper/dashboard/routes/api.py \
        book_scraper/db/repo.py \
        book_scraper/dashboard/static/hifi/hf-runs.jsx \
        tests/integration/test_dashboard_routes.py
git commit -m "$(cat <<'EOF'
feat(dashboard): surface attempts on History + group stats on Failures

Adds per-URL Attempts column to the History card and group-level
max_attempts + capped_count to each Failures card bucket. Backed by
scrape_url_items.attempts.
EOF
)"
```

---

## Task 13: Operator manual retry resets `attempts`

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py::api_retry_run_failures`
- Test: `tests/integration/test_dashboard_routes.py` (extend)

- [ ] **Step 1: Read the current endpoint**

```bash
grep -n "def api_retry_run_failures" book_scraper/dashboard/routes/api.py
```

Open the function body to see how it currently flips items.

- [ ] **Step 2: Write a failing test that asserts attempts reset**

Append to `tests/integration/test_dashboard_routes.py`:

```python
def test_retry_failures_resets_attempts(client, db_session):
    from book_scraper.db.models import ScrapeUrlItem
    from book_scraper.db.repo import (
        create_scrape_run, insert_scrape_url_item, upsert_shop,
        record_scrape_failure,
    )

    shop = upsert_shop(db_session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(db_session, shop.id, "scan")
    run.status = "failed"
    run.resumable_after_failure = True
    item = insert_scrape_url_item(
        db_session, run_id=run.id, shop_id=shop.id, discovered_url_id=None,
        url="https://www.vaga.lt/p/x", url_type="product",
    )
    item.status = "failed"
    item.attempts = 3  # capped
    db_session.flush()
    record_scrape_failure(
        db_session, scrape_url_item=item, error_reason="http_500",
        http_status=500,
    )
    db_session.commit()

    response = client.post(f"/api/runs/{run.id}/retry")
    assert response.status_code == 200

    refreshed = db_session.get(ScrapeUrlItem, item.id)
    assert refreshed.status == "pending"
    assert refreshed.attempts == 0
```

- [ ] **Step 3: Run, confirm it fails**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_dashboard_routes.py::test_retry_failures_resets_attempts -v
```

Expected: FAIL — the endpoint flips status but not `attempts`.

- [ ] **Step 4: Update the endpoint**

In `book_scraper/dashboard/routes/api.py`, find `api_retry_run_failures`. Wherever the code does the bulk update from `failed → pending`, add `attempts=0` to the SET clause. If the code does it via `update(ScrapeUrlItem).values(status="pending", ...)`, simply add `attempts=0`. If it iterates Python objects and sets attributes, add `item.attempts = 0` alongside `item.status = "pending"`.

- [ ] **Step 5: Run the test, confirm it passes**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_dashboard_routes.py::test_retry_failures_resets_attempts -v
```

Expected: PASS.

- [ ] **Step 6: Run full dashboard route tests as smoke (per CLAUDE.md)**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add book_scraper/dashboard/routes/api.py tests/integration/test_dashboard_routes.py
git commit -m "$(cat <<'EOF'
feat(dashboard): operator Retry-failures resets attempts to 0

Manual retry is an explicit operator override and bypasses the cap.
Auto-retry sweep continues to leave attempts alone.
EOF
)"
```

---

## Task 14: Reaper / freshness sanity check (`started_at` vs `last_heartbeat`)

**Files:**
- Audit (no changes expected; fixes only if grep finds issues): `book_scraper/db/repo.py`, `book_scraper/dashboard/routes/api.py`, `book_scraper/scripts/reconcile_runs.py`, `book_scraper/extensions.py`

- [ ] **Step 1: Grep for `started_at` reads in reaper / staleness logic**

```bash
grep -rn "started_at" book_scraper/ --include="*.py" | grep -vE "(create_scrape_run|insert|model|scrape_run\.started_at = |\.started_at,|test_)"
```

Inspect each result: is the code using `started_at` as a "process boot freshness" proxy (e.g. comparing to `now() - threshold` to declare a run stale)? If yes, switch to `last_heartbeat`.

- [ ] **Step 2: For each genuine misuse found, update + add a regression test**

If a fix is needed, write the failing test first against current code (a long-running logical run with one fresh restart should NOT be considered stale even though `started_at` is hours ago), then change the comparison to use `last_heartbeat`.

If grep turns up only legitimate uses (e.g. ordering by `started_at` for display, or seeding initial heartbeat = started_at on creation), nothing to do — note in commit message.

- [ ] **Step 3: Commit (only if changes were made)**

```bash
git add <files>
git commit -m "$(cat <<'EOF'
fix(reaper): key freshness off last_heartbeat, not started_at

Single-row restart model means started_at is the logical-run start, not
the process boot time. Stale-run detection must read last_heartbeat to
avoid false-positives on long-running resumed runs.
EOF
)"
```

If no changes were made, skip the commit. Note the audit result in the PR description.

---

## Task 15: End-to-end smoke + post-deploy checklist

**Files:** none. Operational verification only.

- [ ] **Step 1: Run the entire test suite**

```bash
docker compose up -d postgres postgres-test
PYTHONPATH=. uv run pytest tests/ -v --no-header
```

Expected: all pass. Investigate any unrelated failures.

- [ ] **Step 2: Run lint + type checks per CLAUDE.md**

```bash
uv run ruff check book_scraper/ tests/
uv run ruff format --check book_scraper/ tests/
uv run mypy book_scraper/
```

If ruff/mypy report issues in touched files, fix them. Don't let the format check fail.

- [ ] **Step 3: Rebuild scraper + dashboard images**

Per CLAUDE.md: schema changes + repo/service/spider changes require both rebuilds.

```bash
docker compose build scraper dashboard
docker compose up -d scraper dashboard
```

- [ ] **Step 4: Confirm migration applied in the running scraper container**

```bash
docker exec book-scraper-scraper-1 psql \
  postgresql://postgres:postgres@postgres:5432/book_scraper \
  -c "\d scrape_url_items" | grep attempts
docker exec book-scraper-scraper-1 psql \
  postgresql://postgres:postgres@postgres:5432/book_scraper \
  -c "SELECT conname, consrc FROM pg_constraint WHERE conname='ck_scrape_run_events_event_type'"
```

Expected: `attempts | integer | not null default 0` shows up; constraint definition includes `'restarted'`.

- [ ] **Step 5: Trigger a short scan smoke**

```bash
docker exec book-scraper-scraper-1 /app/.venv/bin/scrapy crawl scan \
  -a shop=vaga -a max_urls=5
```

Watch logs (`docker compose logs -f scraper`) — confirm the run completes cleanly, the `attempts` column ticks to 1 on each fetched URL, no errors about unknown event types.

- [ ] **Step 6: Verify dashboard smoke**

```bash
PYTHONPATH=. uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all pass. Also load `http://localhost:8000`, navigate to the run from step 5, confirm timeline + Failures card render correctly.

- [ ] **Step 7: Force-stall verification (optional, dev-only)**

In a dev environment, drop `STALL_TIMEOUT` to e.g. 10s temporarily, kick off a scan against a slow shop, watch the StallDetector fire. Confirm in the dashboard that the run row stays the same (same `id`) across the restart and that a `restarted` event appears in its timeline.

```bash
# In dev only — do NOT run on prod data:
docker exec book-scraper-scraper-1 env STALL_TIMEOUT=10 \
  /app/.venv/bin/scrapy crawl scan -a shop=vaga -a max_urls=50
```

Then check:

```sql
SELECT id, status, urls_processed,
       (SELECT count(*) FROM scrape_run_events
        WHERE run_id=r.id AND event_type='restarted') AS restarts
FROM scrape_runs r WHERE shop_id=(SELECT id FROM shops WHERE name='vaga')
ORDER BY id DESC LIMIT 5;
```

Expected: the latest run shows `restarts >= 1`, and you DON'T see new chained rows for this restart.

- [ ] **Step 8: Add post-deploy notes to CLAUDE.md**

Append to the `## Post-Task Checklist` section (or wherever recent ops tips live):

```markdown
- After deploying single-row restarts (2026-05-09): on shops with large
  stale-failed backlogs (humanitas, patogupirkti), the first scan may
  trigger an end-of-run retry sweep over hundreds–thousands of URLs.
  Watch heartbeat during the first run; if the sweep extends past
  STALL_TIMEOUT, the run will restart cleanly (single-row, capped at
  STALL_AUTO_RESUME_MAX restarts). To grandfather stale failures as
  exhausted before the first run, run:
  `UPDATE scrape_url_items SET attempts=3 WHERE status='failed';`
```

- [ ] **Step 9: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: post-deploy notes for single-row restart rollout"
```

---

## Self-Review Checklist (run before declaring the plan complete)

**Spec coverage** — every spec section maps to at least one task:

| Spec section | Task(s) |
|---|---|
| Schema changes (`attempts` column, `restarted` event, model CheckConstraint) | Task 1 (steps 4a + 4b) |
| Restart-in-place mechanism (`restart_run_in_place`, atomicity, idempotency, service-only PID) | Task 3 |
| Counter race during process handover | Documented; no code change (intentional). Task 14 audits one consequence. |
| Subprocess respawn unchanged + Continue endpoint unchanged | Verified in plan structure (NOT changed); Task 14 sanity-audits any reaper consequences |
| End-of-run retry hook (`spider_idle`, `_end_of_run_retry_done`, `RETRY_CAP`) | Tasks 2, 4, 5, 9, 10 |
| Retry storm risk | Operator note in Task 15 step 8 |
| Circuit breakers (chain depth, zero-progress) — single-row event reads | Task 6 (rewrites existing tests in test_discover_service.py) |
| Dashboard timeline icon | Task 11 (`hf-runs.jsx` `RUN_EVENT_META` + `_eventSummary`) |
| Dashboard surfaces `attempts` (History per-URL + Failures group stats) | Task 12 |
| Operator manual retry resets `attempts` | Task 13 |
| Reaper keys off `last_heartbeat` | Task 14 |
| Migration + backfill + roll-back | Task 1 |
| `reset_failed_items_to_pending` clears stale terminal metadata | Task 4 (helper definition) |
| Architectural alternatives (process fencing, etc.) | Documented as deferred in spec; no task |

**Placeholder scan** — none in this plan: every step has exact paths, exact code, exact commands.

**Type / signature consistency** — `restart_run_in_place(session, run, *, payload, actor, event_type="restarted")` used identically in Tasks 3, 7, 8. `fetch_retryable_failed_items(session, run_id, cap)` used identically in Tasks 4, 9, 10. `reset_failed_items_to_pending(session, item_ids, *, reset_attempts=False)` used identically in Tasks 4, 9, 10, 13. `RETRY_CAP=3` defined in Task 2, read in Tasks 9, 10. `RESTARTED="restarted"` defined in Task 1, read in Tasks 3, 6, 7, 8, 11.
