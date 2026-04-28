"""Add scrape_failures table and backfill from scrape_url_items

Revision ID: c82154caca5a
Revises: 11ad8dbb08d1
Create Date: 2026-04-28 18:39:20.116101

Per docs/superpowers/plans/2026-04-28-scrape-failures-migration.md (PR 1):
introduces an append-only scrape_failures event log so each failed fetch
becomes its own row (retries get their own rows ordered by occurred_at)
and acknowledgments / lifecycle live with the failure event rather than
on the queue row. Reuses the existing validation_lifecycle enum.

Backfill: every scrape_url_items row currently in status='failed' gets
one scrape_failures row carrying its error_reason / http_status. The
queue's denormalized error_reason / http_status columns stay (PR 1 is
dual-write); they get dropped in PR 3 once readers have all migrated.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c82154caca5a"
down_revision: Union[str, Sequence[str], None] = "11ad8dbb08d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scrape_failures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scrape_url_item_id",
            sa.Integer(),
            sa.ForeignKey("scrape_url_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("scrape_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "shop_id",
            sa.Integer(),
            sa.ForeignKey("shops.id"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "discovered_url_id",
            sa.Integer(),
            sa.ForeignKey("discovered_urls.id"),
            nullable=True,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_bytes", sa.Integer(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "lifecycle_state",
            postgresql.ENUM(
                "new",
                "recurring",
                "already_seen",
                name="validation_lifecycle",
                create_type=False,
            ),
            nullable=False,
            server_default="new",
        ),
        sa.Column(
            "acknowledged_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("acknowledged_note", sa.Text(), nullable=True),
    )

    # Failure-card grouping (filter run_id, group by reason+http).
    op.create_index(
        "ix_scrape_failures_run_bucket",
        "scrape_failures",
        ["run_id", "error_reason", "http_status"],
    )
    # Cross-run recurrence ("has this URL+reason failed before?").
    op.create_index(
        "ix_scrape_failures_shop_url",
        "scrape_failures",
        ["shop_id", "url"],
    )
    # Open-issues inbox (already_seen rows hidden by default).
    op.create_index(
        "ix_scrape_failures_lifecycle_open",
        "scrape_failures",
        ["lifecycle_state"],
        postgresql_where=sa.text("lifecycle_state != 'already_seen'"),
    )
    # Timeline queries ("what failed in the last hour").
    op.create_index(
        "ix_scrape_failures_occurred_at",
        "scrape_failures",
        [sa.text("occurred_at DESC")],
    )

    # Backfill: one scrape_failures row per currently-failed
    # scrape_url_items row. Carries forward the queue's denormalized
    # error_reason / http_status. Pre-migration retry history is already
    # lost on the queue (rows were overwritten in place), so we don't
    # try to fabricate it here.
    op.execute(
        """
        INSERT INTO scrape_failures (
            scrape_url_item_id, run_id, shop_id, url, discovered_url_id,
            occurred_at, error_reason, http_status,
            response_bytes, error_detail, lifecycle_state
        )
        SELECT
            sui.id, sui.run_id, sui.shop_id, sui.url, sui.discovered_url_id,
            COALESCE(sui.done_at, sui.claimed_at, NOW()),
            sui.error_reason, sui.http_status,
            sui.response_bytes, NULL, 'new'
        FROM scrape_url_items sui
        WHERE sui.status = 'failed'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scrape_failures_occurred_at", table_name="scrape_failures"
    )
    op.drop_index(
        "ix_scrape_failures_lifecycle_open", table_name="scrape_failures"
    )
    op.drop_index(
        "ix_scrape_failures_shop_url", table_name="scrape_failures"
    )
    op.drop_index(
        "ix_scrape_failures_run_bucket", table_name="scrape_failures"
    )
    op.drop_table("scrape_failures")
