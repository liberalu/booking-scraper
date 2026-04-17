"""add type column to listings for audio/ebook distinction

Revision ID: e4f8a2c6b701
Revises: d1f2e5b8a9c4
Create Date: 2026-04-17 11:30:00.000000

Adds a listing_type enum column (book/audio/ebook, default book) to
the listings table and backfills it from the existing `format` string
— audiobook → audio, anything else stays book.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4f8a2c6b701"
down_revision: Union[str, Sequence[str], None] = "d1f2e5b8a9c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE listing_type AS ENUM ('book', 'audio', 'ebook')")
    op.add_column(
        "listings",
        sa.Column(
            "type",
            sa.Enum(
                "book",
                "audio",
                "ebook",
                name="listing_type",
                create_type=False,
            ),
            nullable=False,
            server_default="book",
        ),
    )
    # Backfill — audiobook format is the only existing signal.
    op.execute(
        "UPDATE listings SET type = 'audio' WHERE format = 'audiobook'"
    )


def downgrade() -> None:
    op.drop_column("listings", "type")
    op.execute("DROP TYPE listing_type")
