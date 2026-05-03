"""add discover_lupasearch to scrape_phase enum

Revision ID: d4e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d4e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE scrape_phase ADD VALUE IF NOT EXISTS 'discover_lupasearch'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating
    # the type. Removing the value would require migrating any rows that
    # use it first; this downgrade is intentionally a no-op.
    pass
