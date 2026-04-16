"""add listing_attributes table

Revision ID: f8a1c7b9d2e0
Revises: a29261e555de
Create Date: 2026-04-16 09:00:00.000000

Introduces a row-per-(listing, key) table for format-specific
attributes (duration, narrator, translator, cover_type, pages, ...)
that previously lived only in listings.properties JSONB.

The JSONB column is kept in place; writes now go to both places
(dual-write) so this migration stays reversible. A follow-up can drop
listings.properties once every consumer reads from listing_attributes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a1c7b9d2e0"
down_revision: Union[str, Sequence[str], None] = "a29261e555de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "listing_attributes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "listing_id", "key", name="uq_listing_attribute_listing_key"
        ),
    )
    op.create_index(
        "ix_listing_attributes_listing_id",
        "listing_attributes",
        ["listing_id"],
    )
    op.create_index(
        "ix_listing_attributes_key",
        "listing_attributes",
        ["key"],
    )


def downgrade() -> None:
    op.drop_index("ix_listing_attributes_key", table_name="listing_attributes")
    op.drop_index(
        "ix_listing_attributes_listing_id",
        table_name="listing_attributes",
    )
    op.drop_table("listing_attributes")
