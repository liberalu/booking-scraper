"""refactor: JSONB properties, drop books table, rename isbn

Revision ID: d34132e979d1
Revises: 47a56ea82802
Create Date: 2026-04-05 23:53:01.385349

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'd34132e979d1'
down_revision: Union[str, Sequence[str], None] = '47a56ea82802'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add JSONB properties column
    op.add_column('listings', sa.Column('properties', JSONB, nullable=True))

    # 2. Add price/price_original/in_stock to listings (latest snapshot)
    op.add_column('listings', sa.Column('price', sa.Numeric(10, 2), nullable=True))
    op.add_column('listings', sa.Column('price_original', sa.Numeric(10, 2), nullable=True))
    op.add_column('listings', sa.Column('in_stock', sa.Boolean(), nullable=True, server_default='true'))

    # 3. Migrate format-specific columns into JSONB properties
    op.execute("""
        UPDATE listings SET properties = jsonb_strip_nulls(jsonb_build_object(
            'pages', pages,
            'cover_type', cover_type,
            'duration', duration,
            'narrator', narrator,
            'translator', translator
        ))
        WHERE pages IS NOT NULL
           OR cover_type IS NOT NULL
           OR duration IS NOT NULL
           OR narrator IS NOT NULL
           OR translator IS NOT NULL
    """)

    # 4. Drop format-specific columns
    op.drop_column('listings', 'pages')
    op.drop_column('listings', 'cover_type')
    op.drop_column('listings', 'duration')
    op.drop_column('listings', 'narrator')
    op.drop_column('listings', 'translator')

    # 5. Rename isbn_from_shop -> isbn
    op.alter_column('listings', 'isbn_from_shop', new_column_name='isbn')

    # 6. Drop book_id FK and column
    op.drop_constraint('listings_book_id_fkey', 'listings', type_='foreignkey')
    op.drop_column('listings', 'book_id')

    # 7. Drop books-related tables
    op.drop_table('book_categories')
    op.drop_table('books')

    # 8. Set in_stock NOT NULL default
    op.alter_column('listings', 'in_stock', nullable=False, server_default='true')


def downgrade() -> None:
    # Reverse is complex — not implementing full downgrade for this refactor
    raise NotImplementedError("Downgrade not supported for this migration")
