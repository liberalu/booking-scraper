"""add 'paused' to scrape_status enum

Revision ID: e8b3c1a7f054
Revises: d7e4a2c91b65
Create Date: 2026-04-27

"""

from collections.abc import Sequence

from alembic import op

revision: str = "e8b3c1a7f054"
down_revision: str | Sequence[str] | None = "d7e4a2c91b65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Must run outside a transaction block.
    op.execute("COMMIT")
    op.execute("ALTER TYPE scrape_status ADD VALUE IF NOT EXISTS 'paused'")


def downgrade() -> None:
    op.execute("UPDATE scrape_runs SET status = 'running' WHERE status = 'paused'")
    op.execute("ALTER TYPE scrape_status RENAME TO scrape_status_old")
    op.execute(
        "CREATE TYPE scrape_status AS ENUM "
        "('running', 'stopping', 'completed', 'failed')"
    )
    op.execute(
        "ALTER TABLE scrape_runs "
        "ALTER COLUMN status TYPE scrape_status USING status::text::scrape_status"
    )
    op.execute("DROP TYPE scrape_status_old")
