"""add_cron_jobs_table

Revision ID: 74dbaec63e45
Revises: da5969e6777d
Create Date: 2026-04-18 10:00:36.281111

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "74dbaec63e45"
down_revision: str | Sequence[str] | None = "da5969e6777d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cron_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=True),
        sa.Column("args", sa.Text(), nullable=False, server_default=""),
        sa.Column("cron_expression", sa.Text(), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cron_jobs_shop_enabled", "cron_jobs", ["shop_id", "enabled"])

    # Seed the two existing jobs so parity with cron/scraper-crontab is preserved.
    conn = op.get_bind()
    shop_row = conn.execute(
        sa.text("SELECT id FROM shops WHERE name = 'vaga'")
    ).fetchone()
    if shop_row is not None:
        shop_id = shop_row[0]
        conn.execute(
            sa.text(
                "INSERT INTO cron_jobs (shop_id, phase, strategy, args, "
                "cron_expression, enabled) "
                "VALUES (:shop_id, 'discover', 'sitemap', '', '0 2 * * *', true), "
                "(:shop_id, 'scan', NULL, '', '0 3 * * *', true)"
            ),
            {"shop_id": shop_id},
        )


def downgrade() -> None:
    op.drop_index("ix_cron_jobs_shop_enabled", table_name="cron_jobs")
    op.drop_table("cron_jobs")
