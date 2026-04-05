"""initial schema

Revision ID: 9d044f7a03d6
Revises:
Create Date: 2026-04-05 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9d044f7a03d6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    match_status = postgresql.ENUM(
        "unmatched", "matched", "uncertain", name="match_status", create_type=False
    )
    match_method = postgresql.ENUM(
        "isbn", "fuzzy", "manual", name="match_method", create_type=False
    )
    match_status.create(op.get_bind(), checkfirst=True)
    match_method.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isbn", sa.String(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("publisher", sa.String(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("format", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("labels", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isbn"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "book_categories",
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("book_id", "category_id"),
    )

    op.create_table(
        "shops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "listings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("shop_title", sa.Text(), nullable=False),
        sa.Column("shop_author", sa.Text(), nullable=True),
        sa.Column("isbn_from_shop", sa.String(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column(
            "match_status",
            sa.Enum("unmatched", "matched", "uncertain", name="match_status"),
            nullable=False,
        ),
        sa.Column(
            "match_method",
            sa.Enum("isbn", "fuzzy", "manual", name="match_method"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "url", name="uq_listing_shop_url"),
    )

    op.create_table(
        "prices",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("price_original", sa.Numeric(10, 2), nullable=True),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "discount_pct",
            sa.Numeric(5, 2),
            sa.Computed(
                "CASE WHEN price_original IS NOT NULL AND price_original > 0 "
                "THEN ROUND((1 - price / price_original) * 100, 2) END"
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("prices")
    op.drop_table("listings")
    op.drop_table("shops")
    op.drop_table("book_categories")
    op.drop_table("categories")
    op.drop_table("books")

    match_status = postgresql.ENUM(name="match_status")
    match_method = postgresql.ENUM(name="match_method")
    match_status.drop(op.get_bind(), checkfirst=True)
    match_method.drop(op.get_bind(), checkfirst=True)
