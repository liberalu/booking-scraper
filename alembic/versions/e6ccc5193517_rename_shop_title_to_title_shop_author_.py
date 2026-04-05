"""rename shop_title to title, shop_author to author

Revision ID: e6ccc5193517
Revises: f71a5796938e
Create Date: 2026-04-05 23:23:24.875430

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e6ccc5193517'
down_revision: Union[str, Sequence[str], None] = 'f71a5796938e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('listings', 'shop_title', new_column_name='title')
    op.alter_column('listings', 'shop_author', new_column_name='author')


def downgrade() -> None:
    op.alter_column('listings', 'title', new_column_name='shop_title')
    op.alter_column('listings', 'author', new_column_name='shop_author')
