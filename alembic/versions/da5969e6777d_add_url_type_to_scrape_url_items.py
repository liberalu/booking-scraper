"""add_url_type_to_scrape_url_items

Revision ID: da5969e6777d
Revises: bd5719da484f
Create Date: 2026-04-18 09:10:17.683578

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'da5969e6777d'
down_revision: Union[str, Sequence[str], None] = 'bd5719da484f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scrape_url_items",
        sa.Column(
            "url_type",
            sa.Text(),
            nullable=False,
            server_default="product",
        ),
    )


def downgrade() -> None:
    op.drop_column("scrape_url_items", "url_type")

