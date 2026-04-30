"""add_created_run_id_to_shop_books

Revision ID: f21086852374
Revises: e7c1a2b9d4f3
Create Date: 2026-04-29 21:23:20.989894

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f21086852374'
down_revision: Union[str, Sequence[str], None] = 'e7c1a2b9d4f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('shop_books', sa.Column('created_run_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_shop_books_created_run_id'), 'shop_books', ['created_run_id'], unique=False)
    op.create_foreign_key(None, 'shop_books', 'scrape_runs', ['created_run_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(None, 'shop_books', type_='foreignkey')
    op.drop_index(op.f('ix_shop_books_created_run_id'), table_name='shop_books')
    op.drop_column('shop_books', 'created_run_id')

