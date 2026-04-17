"""add shop_authors and listing_authors tables

Revision ID: 905fbbbc4372
Revises: 4dad32ce93eb
Create Date: 2026-04-17

Shops return the author field as a single string glued together with
separators like ", ; & / ir and" — listing 13525 stores
"L. Šernienė, M. Puzaitė" in a single Listing.author column. This
collapses structured info: grouping/filtering by author is unreliable.

Introduce a shop_authors catalogue and a listing_authors join table so
a listing can reference N authors. Listing.author stays as the original
raw string (rollback-friendly, and matches what the parsers emit).

Backfill: split every existing Listing.author on the multi-author
regex, upsert each trimmed name, and create the join row with `position`
set to its index in the split.
"""
import re
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '905fbbbc4372'
down_revision: Union[str, Sequence[str], None] = '4dad32ce93eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MULTI_AUTHOR_RE = re.compile(
    r"(?:,\s|;|\s&\s|\s/\s|\s+and\s+|\s+ir\s+)", re.IGNORECASE
)


def _split_authors(raw: str) -> list[str]:
    return [p.strip() for p in _MULTI_AUTHOR_RE.split(raw) if p and p.strip()]


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def upgrade() -> None:
    op.create_table(
        "shop_authors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "normalized_name", sa.String(length=255), nullable=False, index=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("normalized_name", name="uq_shop_authors_normalized"),
    )
    op.create_table(
        "listing_authors",
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("shop_authors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("listing_id", "author_id"),
    )
    op.create_index(
        "ix_listing_authors_author_id", "listing_authors", ["author_id"]
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, author FROM listings WHERE author IS NOT NULL "
            "AND author <> ''"
        )
    ).fetchall()
    author_ids: dict[str, int] = {}
    for listing_id, raw_author in rows:
        parts = _split_authors(raw_author) or [raw_author.strip()]
        for idx, name in enumerate(parts):
            norm = _normalize(name)
            if not norm:
                continue
            author_id = author_ids.get(norm)
            if author_id is None:
                existing = bind.execute(
                    sa.text(
                        "SELECT id FROM shop_authors WHERE normalized_name = :n"
                    ),
                    {"n": norm},
                ).fetchone()
                if existing is not None:
                    author_id = existing[0]
                else:
                    author_id = bind.execute(
                        sa.text(
                            "INSERT INTO shop_authors (name, normalized_name) "
                            "VALUES (:name, :norm) RETURNING id"
                        ),
                        {"name": name, "norm": norm},
                    ).scalar_one()
                author_ids[norm] = author_id
            bind.execute(
                sa.text(
                    "INSERT INTO listing_authors (listing_id, author_id, position) "
                    "VALUES (:lid, :aid, :pos) ON CONFLICT DO NOTHING"
                ),
                {"lid": listing_id, "aid": author_id, "pos": idx},
            )


def downgrade() -> None:
    op.drop_index("ix_listing_authors_author_id", table_name="listing_authors")
    op.drop_table("listing_authors")
    op.drop_table("shop_authors")
