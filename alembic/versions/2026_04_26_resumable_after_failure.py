"""add resumable_after_failure to scrape_runs

Revision ID: c5a3f7d8b914
Revises: a1b7d4e92f10
Create Date: 2026-04-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5a3f7d8b914"
down_revision: str | Sequence[str] | None = "a1b7d4e92f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scrape_runs",
        sa.Column(
            "resumable_after_failure",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("scrape_runs", "resumable_after_failure")
