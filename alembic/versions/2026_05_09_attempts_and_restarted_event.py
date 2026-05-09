"""add attempts to scrape_url_items + 'restarted' event type

Revision ID: 8f2a4d6b3e91
Revises: a3cf682de91e
Create Date: 2026-05-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8f2a4d6b3e91"
down_revision: str | Sequence[str] | None = "a3cf682de91e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scrape_url_items",
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Drop and re-add the event-type CHECK constraint with 'restarted'.
    op.drop_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        "event_type IN ("
        "'started','paused','resumed','stop_requested','retry_failures',"
        "'rerun','continued','resumed_after_failure','restarted',"
        "'completed','failed','subdivided'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        "event_type IN ("
        "'started','paused','resumed','stop_requested','retry_failures',"
        "'rerun','continued','resumed_after_failure',"
        "'completed','failed','subdivided'"
        ")",
    )
    op.drop_column("scrape_url_items", "attempts")
