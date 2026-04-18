"""delete_non_book_shop_books

Revision ID: e7d678837069
Revises: 74dbaec63e45
Create Date: 2026-04-18 17:35:37.693400

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7d678837069'
down_revision: Union[str, Sequence[str], None] = '74dbaec63e45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: mark discovered_urls as non_product so they are never re-scanned,
    # and NULL out the FK so we can delete the shop_books rows
    op.execute("""
        UPDATE discovered_urls
        SET url_type = 'non_product',
            shop_book_id = NULL
        WHERE shop_book_id IN (
            SELECT id FROM shop_books WHERE type = 'non_book'
        )
    """)

    # Step 2: delete dependent rows that lack ON DELETE CASCADE
    op.execute("""
        DELETE FROM prices
        WHERE shop_book_id IN (
            SELECT id FROM shop_books WHERE type = 'non_book'
        )
    """)
    op.execute("""
        DELETE FROM shop_book_changes
        WHERE shop_book_id IN (
            SELECT id FROM shop_books WHERE type = 'non_book'
        )
    """)
    op.execute("""
        DELETE FROM validation_issues
        WHERE shop_book_id IN (
            SELECT id FROM shop_books WHERE type = 'non_book'
        )
    """)

    # Step 3: delete the non_book shop_books themselves
    # (shop_book_attributes, shop_book_authors, shop_book_field_updates
    #  have ON DELETE CASCADE and are cleaned up automatically)
    op.execute("DELETE FROM shop_books WHERE type = 'non_book'")


def downgrade() -> None:
    pass  # data deletion is not reversible

