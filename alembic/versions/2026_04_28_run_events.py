"""add run_events table and backfill

Revision ID: d3e8b1f4a721
Revises: c82154caca5a
Create Date: 2026-04-28

Backfill rules:
  - Every existing scrape_runs row gets a `started` event at started_at
    (actor=NULL, payload=NULL — original args are not recoverable).
  - Rows with finished_at IS NOT NULL get a `completed` or `failed`
    event at finished_at, derived from (status, close_reason).
  - Zombie rows (status='running' with stale heartbeat) get only
    `started`. The reaper will emit a real `failed` event when it
    next runs; synthesizing one here would duplicate.
  - Pause/resume/retry/rerun history is unrecoverable.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3e8b1f4a721"
down_revision: str | Sequence[str] | None = "c82154caca5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("scrape_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor", sa.String(length=20), nullable=True),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'started','paused','resumed','stop_requested','retry_failures',"
            "'rerun','continued','resumed_after_failure','completed','failed'"
            ")",
            name="ck_run_events_event_type",
        ),
    )
    op.create_index(
        "ix_run_events_run_id", "run_events", ["run_id"]
    )
    op.create_index(
        "ix_run_events_run_created", "run_events", ["run_id", "created_at"]
    )

    # Backfill: started for every run.
    op.execute(
        """
        INSERT INTO run_events (run_id, event_type, created_at, actor, payload)
        SELECT id, 'started', started_at, NULL, NULL
        FROM scrape_runs
        """
    )
    # Backfill: terminal event for runs with finished_at set.
    op.execute(
        """
        INSERT INTO run_events (run_id, event_type, created_at, actor, payload)
        SELECT
            id,
            CASE
                WHEN status = 'completed' THEN 'completed'
                ELSE 'failed'
            END,
            finished_at,
            NULL,
            jsonb_build_object(
                'close_reason', close_reason,
                'urls_processed', urls_processed,
                'error_count', error_count,
                'backfilled', true
            )
        FROM scrape_runs
        WHERE finished_at IS NOT NULL
          AND status IN ('completed', 'failed')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_run_events_run_created", table_name="run_events")
    op.drop_index("ix_run_events_run_id", table_name="run_events")
    op.drop_table("run_events")
