"""add_url_classifications

Revision ID: 6437528439cc
Revises: e7d678837069
Create Date: 2026-04-19 13:29:16.830005

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6437528439cc'
down_revision: Union[str, Sequence[str], None] = 'e7d678837069'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Primary change: add url_classifications table
    op.create_table('url_classifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('discovered_url_id', sa.Integer(), nullable=False),
    sa.Column('book_score', sa.Integer(), nullable=False),
    sa.Column('is_book_product', sa.Boolean(), nullable=False),
    sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('classified_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['discovered_url_id'], ['discovered_urls.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('discovered_url_id')
    )
    op.create_index('ix_url_classifications_book_score', 'url_classifications', ['book_score'], unique=False)
    op.create_index('ix_url_classifications_is_book_product', 'url_classifications', ['is_book_product'], unique=False)

    # Schema drift cleanup (IF EXISTS guards make these safe on clean DBs)
    op.execute("DROP TABLE IF EXISTS listings_description_backup")
    # Replace separate unique constraint + non-unique index with a single unique index
    op.execute(
        "ALTER TABLE shop_authors DROP CONSTRAINT IF EXISTS uq_shop_authors_normalized"
    )
    op.execute("DROP INDEX IF EXISTS ix_shop_authors_normalized_name")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_shop_authors_normalized_name "
        "ON shop_authors (normalized_name)"
    )
    op.execute("DROP INDEX IF EXISTS ix_shop_book_attributes_key")
    op.execute("DROP INDEX IF EXISTS ix_shop_book_attributes_shop_book_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_url_classifications_is_book_product', table_name='url_classifications')
    op.drop_index('ix_url_classifications_book_score', table_name='url_classifications')
    op.drop_table('url_classifications')
    # Note: schema drift cleanup (listings_description_backup drop, index changes)
    # is not reversed as those were stale/incorrect states.

