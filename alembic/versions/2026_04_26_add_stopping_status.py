"""add 'stopping' to scrape_status enum

Revision ID: d7e4a2c91b65
Revises: c5a3f7d8b914
Create Date: 2026-04-26

"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7e4a2c91b65"
down_revision: str | Sequence[str] | None = "c5a3f7d8b914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres ALTER TYPE ADD VALUE cannot run inside a transaction block.
    op.execute("COMMIT")
    op.execute("ALTER TYPE scrape_status ADD VALUE IF NOT EXISTS 'stopping'")


def downgrade() -> None:
    # Postgres has no native enum-value drop. Recreate the enum without
    # 'stopping'. Any existing 'stopping' rows must be rewritten first
    # (they're transient, so this is normally safe).
    op.execute("UPDATE scrape_runs SET status = 'failed' WHERE status = 'stopping'")
    op.execute("ALTER TYPE scrape_status RENAME TO scrape_status_old")
    op.execute(
        "CREATE TYPE scrape_status AS ENUM ('running', 'completed', 'failed')"
    )
    op.execute(
        "ALTER TABLE scrape_runs "
        "ALTER COLUMN status TYPE scrape_status USING status::text::scrape_status"
    )
    op.execute("DROP TYPE scrape_status_old")
