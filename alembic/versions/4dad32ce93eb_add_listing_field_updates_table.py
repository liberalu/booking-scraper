"""add listing_field_updates table

Revision ID: 4dad32ce93eb
Revises: e4f8a2c6b701
Create Date: 2026-04-17

Tracks the per-field last-changed timestamp for watched listing fields
(price, description, image_url, author, isbn, publisher, year, format).
Backfills existing rows from `listings.last_seen_at` as a best-effort
initial timestamp for every currently-populated field — the pipeline
advances it from there on actual change.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4dad32ce93eb'
down_revision: Union[str, Sequence[str], None] = 'e4f8a2c6b701'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


WATCHED_FIELDS = (
    "price",
    "description",
    "image_url",
    "author",
    "isbn",
    "publisher",
    "year",
    "format",
)


def upgrade() -> None:
    op.create_table(
        "listing_field_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "listing_id", "field", name="uq_listing_field_updates_listing_field"
        ),
    )
    op.create_index(
        "ix_listing_field_updates_listing_field",
        "listing_field_updates",
        ["listing_id", "field"],
    )
    # Backfill: seed a row for every (listing, watched-field) pair whose
    # value is currently non-null. Use last_seen_at as the best-effort
    # initial stamp — we don't know when the value actually changed.
    for field in WATCHED_FIELDS:
        op.execute(
            f"""
            INSERT INTO listing_field_updates (listing_id, field, updated_at)
            SELECT id, '{field}', last_seen_at
            FROM listings
            WHERE {field} IS NOT NULL
            """
        )


def downgrade() -> None:
    op.drop_index(
        "ix_listing_field_updates_listing_field",
        table_name="listing_field_updates",
    )
    op.drop_table("listing_field_updates")
