"""add unique constraint run_id url to scrape_url_items

Revision ID: 4fd083f042b7
Revises: 6437528439cc
Create Date: 2026-04-19 19:14:48.584355

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4fd083f042b7'
down_revision: Union[str, Sequence[str], None] = '6437528439cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint('uq_scrape_url_items_run_url', 'scrape_url_items', ['run_id', 'url'])


def downgrade() -> None:
    op.drop_constraint('uq_scrape_url_items_run_url', 'scrape_url_items', type_='unique')

