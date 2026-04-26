"""add non_book to shop_book_type enum

Revision ID: 6b0d9f3c2a11
Revises: 7857873aa4bb
Create Date: 2026-04-18 10:15:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b0d9f3c2a11"
down_revision: str | Sequence[str] | None = "7857873aa4bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ADD VALUE cannot run inside a transaction in PostgreSQL.
    # Use autocommit_block so the value is committed before any subsequent
    # migration that references it (e.g. e7d678837069).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE shop_book_type ADD VALUE IF NOT EXISTS 'non_book'")


def downgrade() -> None:
    op.execute("UPDATE shop_books SET type = 'book' WHERE type = 'non_book'")
    op.execute("ALTER TYPE shop_book_type RENAME TO shop_book_type_old")
    op.execute(
        "CREATE TYPE shop_book_type AS ENUM ('book', 'audio', 'ebook')"
    )
    op.execute(
        "ALTER TABLE shop_books "
        "ALTER COLUMN type TYPE shop_book_type "
        "USING type::text::shop_book_type"
    )
    op.execute("DROP TYPE shop_book_type_old")
