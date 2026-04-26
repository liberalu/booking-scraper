"""add http_status and error_reason to scrape_url_items

Revision ID: 7c441ea07eb2
Revises: 4fd083f042b7
Create Date: 2026-04-26 06:23:24.586099

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c441ea07eb2'
down_revision: Union[str, Sequence[str], None] = '4fd083f042b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scrape_url_items",
        sa.Column("http_status", sa.Integer(), nullable=True),
    )
    op.add_column(
        "scrape_url_items",
        sa.Column("error_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_scrape_url_items_shop_claimed_at",
        "scrape_url_items",
        ["shop_id", "claimed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scrape_url_items_shop_claimed_at", table_name="scrape_url_items"
    )
    op.drop_column("scrape_url_items", "error_reason")
    op.drop_column("scrape_url_items", "http_status")

