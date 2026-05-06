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
