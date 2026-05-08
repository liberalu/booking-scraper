"""add_discover_ibiblioteka_api_phase

Revision ID: b1e4f7a9c2d6
Revises: a3f7d92b1c44
Create Date: 2026-05-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "b1e4f7a9c2d6"
down_revision: Union[str, None] = "a3f7d92b1c44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE scrape_phase ADD VALUE IF NOT EXISTS 'discover_ibiblioteka_api'"
    )


def downgrade() -> None:
    # Postgres does not support removing enum values; this is a no-op.
    pass
