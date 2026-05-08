"""add_match_phase_enum_value

Revision ID: a3cf682de91e
Revises: d9e5f2c8b314
Create Date: 2026-05-08 22:12:17.899725

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3cf682de91e'
down_revision: Union[str, Sequence[str], None] = 'd9e5f2c8b314'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE scrape_phase ADD VALUE IF NOT EXISTS 'match'")


def downgrade() -> None:
    # Postgres does not support removing enum values; no-op.
    pass

