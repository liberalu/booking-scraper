"""drop legacy listings.properties jsonb column

Revision ID: a4bd6135313a
Revises: f8a1c7b9d2e0
Create Date: 2026-04-16 23:47:27.929071

Drops the JSONB `properties` column from `listings`. All attribute data
now lives in the `listing_attributes` table (row-per-(listing, key)).
The previous dual-write was the bridge migration; this completes the
cut-over. Make sure the backfill
(`scripts/backfill_listing_attributes.py`) has been run at least once
against this database before applying this upgrade, otherwise any
legacy values only stored in the JSONB will be lost.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a4bd6135313a'
down_revision: Union[str, Sequence[str], None] = 'f8a1c7b9d2e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the legacy JSONB column."""
    op.drop_column("listings", "properties")


def downgrade() -> None:
    """Restore the JSONB column (data is not recovered — attributes live in
    listing_attributes now). A manual re-hydration would need to read from
    listing_attributes and write the dict back into this column."""
    op.add_column(
        "listings",
        sa.Column("properties", JSONB(), nullable=True),
    )
