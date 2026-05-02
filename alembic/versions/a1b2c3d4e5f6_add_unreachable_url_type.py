"""add unreachable to url_type enum

Revision ID: a1b2c3d4e5f6
Revises: f21086852374
Create Date: 2026-05-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f21086852374'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE url_type ADD VALUE IF NOT EXISTS 'unreachable'")


def downgrade() -> None:
    # Postgres does not support removing enum values without recreating the type.
    # Leave as-is; the value will simply be unused after a downgrade.
    pass
