"""add close_reason to scrape_runs

Revision ID: a4f9c2b85d31
Revises: e8b3c1a7f054
Create Date: 2026-04-27

Adds a free-form text column that records why a scrape_run terminated.
Stamped at finalize for every code path that transitions a run to
completed/failed (Scrapy `closed(reason)`, StallDetector, dashboard
reaper, manual kill, boot reconciliation).

Examples: "finished", "shutdown", "stall_timeout", "heartbeat_timeout",
"orphan_on_boot", "stale_pre_scan", "killed_pid_dead".

Nullable on existing rows; no backfill for runs that finalized before
this column existed.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4f9c2b85d31"
down_revision: str | Sequence[str] | None = "e8b3c1a7f054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scrape_runs",
        sa.Column("close_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scrape_runs", "close_reason")
