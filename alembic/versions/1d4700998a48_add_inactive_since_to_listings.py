"""add inactive_since to listings

Revision ID: 1d4700998a48
Revises: a4bd6135313a
Create Date: 2026-04-16 23:48:39.213509

Adds an `inactive_since` timestamp column to `listings`. When change
detection transitions a listing from active -> inactive (its URL
vanished from the shop's sitemap), this column records the moment of
the transition. A listing that comes back (re-scraped successfully)
resets this column to NULL.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1d4700998a48'
down_revision: Union[str, Sequence[str], None] = 'a4bd6135313a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "listings",
        sa.Column(
            "inactive_since",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Backfill: any listing that is currently inactive didn't have a
    # recorded transition time. Use NOW() as a best-effort stamp so the
    # dashboard can still show "inactive since <today>" for pre-existing
    # rows rather than a perpetual NULL.
    op.execute(
        "UPDATE listings SET inactive_since = NOW() "
        "WHERE is_active = FALSE AND inactive_since IS NULL"
    )


def downgrade() -> None:
    op.drop_column("listings", "inactive_since")
