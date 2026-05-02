"""add planned_availability_date, rating, review_count to shop_books

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('shop_books', sa.Column('planned_availability_date', sa.Date(), nullable=True))
    op.add_column('shop_books', sa.Column('rating', sa.Numeric(3, 2), nullable=True))
    op.add_column('shop_books', sa.Column('review_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('shop_books', 'review_count')
    op.drop_column('shop_books', 'rating')
    op.drop_column('shop_books', 'planned_availability_date')
