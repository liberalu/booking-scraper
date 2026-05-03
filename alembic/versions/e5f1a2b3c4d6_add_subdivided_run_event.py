"""add subdivided to scrape_run_events.event_type check constraint

Revision ID: e5f1a2b3c4d6
Revises: d4e1f2a3b4c5
Create Date: 2026-05-03 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e5f1a2b3c4d6"
down_revision: Union[str, None] = "d4e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_VALUES = (
    "started",
    "paused",
    "resumed",
    "stop_requested",
    "retry_failures",
    "rerun",
    "continued",
    "resumed_after_failure",
    "completed",
    "failed",
    "subdivided",
)

_OLD_VALUES = _NEW_VALUES[:-1]  # without "subdivided"


def _set_check(values):
    quoted = ", ".join(f"'{v}'" for v in values)
    op.execute("ALTER TABLE scrape_run_events DROP CONSTRAINT ck_scrape_run_events_event_type")
    op.execute(
        "ALTER TABLE scrape_run_events ADD CONSTRAINT ck_scrape_run_events_event_type "
        f"CHECK (event_type::text = ANY (ARRAY[{quoted}]::text[]))"
    )


def upgrade() -> None:
    _set_check(_NEW_VALUES)


def downgrade() -> None:
    op.execute(
        "DELETE FROM scrape_run_events WHERE event_type = 'subdivided'"
    )
    _set_check(_OLD_VALUES)
