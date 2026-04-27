"""add_shop_settings_table

Revision ID: 11ad8dbb08d1
Revises: a4f9c2b85d31
Create Date: 2026-04-27 16:12:03.253366

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11ad8dbb08d1'
down_revision: Union[str, Sequence[str], None] = 'a4f9c2b85d31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shop_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "shop_id",
            sa.Integer(),
            sa.ForeignKey("shops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False, server_default="str"),
        sa.UniqueConstraint("shop_id", "key", name="uq_shop_settings_shop_key"),
    )


def downgrade() -> None:
    op.drop_table("shop_settings")

