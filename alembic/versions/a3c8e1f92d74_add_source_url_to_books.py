"""add_source_url_to_books

Revision ID: a3c8e1f92d74
Revises: f21086852374
Create Date: 2026-05-14 22:52:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "a3c8e1f92d74"
down_revision = "e7c4d5f9a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("books", sa.Column("source_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("books", "source_url")
