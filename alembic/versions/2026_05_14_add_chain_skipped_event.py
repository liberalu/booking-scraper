"""add chain_skipped to scrape_run_events.event_type check constraint

Revision ID: e7c4d5f9a1b2
Revises: 398650bd271c
Create Date: 2026-05-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e7c4d5f9a1b2"
down_revision: Union[str, None] = "398650bd271c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED = (
    "started",
    "paused",
    "resumed",
    "stop_requested",
    "retry_failures",
    "rerun",
    "continued",
    "resumed_after_failure",
    "restarted",
    "completed",
    "failed",
    "subdivided",
    "chain_skipped",
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        type_="check",
    )
    quoted = ", ".join(f"'{v}'" for v in _ALLOWED)
    op.create_check_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        f"event_type IN ({quoted})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        type_="check",
    )
    quoted = ", ".join(f"'{v}'" for v in _ALLOWED if v != "chain_skipped")
    op.create_check_constraint(
        "ck_scrape_run_events_event_type",
        "scrape_run_events",
        f"event_type IN ({quoted})",
    )
