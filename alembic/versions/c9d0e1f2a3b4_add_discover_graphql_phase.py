"""add discover_graphql to scrape_phase enum

Revision ID: c9d0e1f2a3b4
Revises: b2c3d4e5f6a7
Create Date: 2026-05-02 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE scrape_phase ADD VALUE IF NOT EXISTS 'discover_graphql'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating the type.
    # This downgrade is intentionally a no-op; removing the value would require
    # migrating any rows that use it first.
    pass
