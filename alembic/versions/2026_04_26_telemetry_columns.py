"""add telemetry columns to scrape_url_items

Revision ID: a1b7d4e92f10
Revises: 7c441ea07eb2
Create Date: 2026-04-26

Adds per-URL telemetry columns for the live observability spec
(docs/superpowers/specs/2026-04-26-live-scrape-observability-design.md):

- request_delay_s: pre-send wait observed in HttpxMiddleware
  (delay_source = 'httpx_observed' on this codebase; AUTOTHROTTLE is
  bypassed by HttpxMiddleware per Gate A's findings).
- delay_source: provenance of the delay value ('httpx_observed',
  'autothrottle_slot', 'configured_delay'). Persisted so postmortems
  can interpret request_delay_s correctly.
- retry_count: reserved for a future throttle-aware retry feature.
  Remains 0 in this spec.
- response_bytes: payload size; helps detect silent block pages
  (200 OK with tiny bodies).

Also creates ix_scrape_url_items_run_done_at to support the live-view
"requests in last 60s" aggregate query.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a1b7d4e92f10'
down_revision: str | Sequence[str] | None = '7c441ea07eb2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scrape_url_items",
        sa.Column("request_delay_s", sa.Float(), nullable=True),
    )
    op.add_column(
        "scrape_url_items",
        sa.Column("delay_source", sa.Text(), nullable=True),
    )
    op.add_column(
        "scrape_url_items",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "scrape_url_items",
        sa.Column("response_bytes", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_scrape_url_items_run_done_at",
        "scrape_url_items",
        ["run_id", "done_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scrape_url_items_run_done_at",
        table_name="scrape_url_items",
    )
    op.drop_column("scrape_url_items", "response_bytes")
    op.drop_column("scrape_url_items", "retry_count")
    op.drop_column("scrape_url_items", "delay_source")
    op.drop_column("scrape_url_items", "request_delay_s")
