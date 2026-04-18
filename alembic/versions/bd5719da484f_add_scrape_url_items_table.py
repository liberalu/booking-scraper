"""add_scrape_url_items_table

Revision ID: bd5719da484f
Revises: 6b0d9f3c2a11
Create Date: 2026-04-18 08:19:04.255205

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bd5719da484f'
down_revision: Union[str, Sequence[str], None] = '6b0d9f3c2a11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    scrape_url_status = postgresql.ENUM(
        "pending", "processing", "done", "failed",
        name="scrape_url_status",
        create_type=False,
    )
    scrape_url_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "scrape_url_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("discovered_url_id", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "processing", "done", "failed",
                name="scrape_url_status",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["discovered_url_id"], ["discovered_urls.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["scrape_runs.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scrape_url_items_run_status", "scrape_url_items", ["run_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_scrape_url_items_run_status", table_name="scrape_url_items")
    op.drop_table("scrape_url_items")
    postgresql.ENUM(name="scrape_url_status").drop(op.get_bind(), checkfirst=True)
