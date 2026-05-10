"""add validate to scrape_phase enum

Revision ID: f1a2b3c4d5e6
Revises: 8f2a4d6b3e91
Create Date: 2026-05-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "8f2a4d6b3e91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE scrape_phase ADD VALUE IF NOT EXISTS 'validate'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating the type.
    # This downgrade is intentionally a no-op; removing the value would require
    # migrating any rows that use it first.
    pass
