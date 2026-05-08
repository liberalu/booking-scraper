"""create canonical books layer

Adds the canonical bibliographic layer:

  publishers      — normalized publisher records
  series          — normalized series records
  authors         — canonical authors with VIAF / ISNI / LIBIS / Wikidata IDs
                    (separate from shop_authors which keeps raw shop-deduped
                    names; they can be linked later via shop_authors.canonical_author_id)
  books           — canonical book records (LIBIS or shop-inferred)
  book_isbns      — many-to-one ISBNs per book
  book_authors    — many-to-many books ↔ authors with role
  shop_books.book_id  — FK linking commercial listings to canonical books

Population is the next step: ibiblioteka spider writes to `books` directly,
the matcher links existing shop_books rows by ISBN.

Revision ID: c5d8e2f3a9b1
Revises: b1e4f7a9c2d6
Create Date: 2026-05-08 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, ENUM

revision: str = "c5d8e2f3a9b1"
down_revision: Union[str, None] = "b1e4f7a9c2d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _book_data_source_enum() -> ENUM:
    return ENUM(
        "ibiblioteka", "shop_inferred", "manual",
        name="book_data_source", create_type=False,
    )


def _book_isbn_type_enum() -> ENUM:
    return ENUM(
        "isbn10", "isbn13", "ebook", "audio", "unknown",
        name="book_isbn_type", create_type=False,
    )


def _book_author_role_enum() -> ENUM:
    return ENUM(
        "author", "translator", "narrator", "illustrator", "editor", "compiler",
        name="book_author_role", create_type=False,
    )


def upgrade() -> None:
    # ── enums ──────────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE book_data_source AS ENUM "
        "('ibiblioteka', 'shop_inferred', 'manual')"
    )
    op.execute(
        "CREATE TYPE book_isbn_type AS ENUM "
        "('isbn10', 'isbn13', 'ebook', 'audio', 'unknown')"
    )
    op.execute(
        "CREATE TYPE book_author_role AS ENUM "
        "('author', 'translator', 'narrator', 'illustrator', "
        "'editor', 'compiler')"
    )

    # ── publishers ─────────────────────────────────────────────────────────
    op.create_table(
        "publishers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("country", sa.Text, nullable=True),
        sa.Column("libis_codes", ARRAY(sa.Text), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_publishers_name"),
    )

    # ── series ─────────────────────────────────────────────────────────────
    op.create_table(
        "series",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("libis_code", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("title", name="uq_series_title"),
        sa.UniqueConstraint("libis_code", name="uq_series_libis_code"),
    )

    # ── authors (canonical, separate from shop_authors) ────────────────────
    op.create_table(
        "authors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("normalized_name", sa.Text, nullable=False),
        sa.Column("libis_code", sa.Text, nullable=True),
        sa.Column("viaf_id", sa.Text, nullable=True),
        sa.Column("isni", sa.Text, nullable=True),
        sa.Column("wikidata_id", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("normalized_name", name="uq_authors_normalized_name"),
        sa.UniqueConstraint("libis_code", name="uq_authors_libis_code"),
        sa.UniqueConstraint("viaf_id", name="uq_authors_viaf_id"),
        sa.UniqueConstraint("isni", name="uq_authors_isni"),
        sa.UniqueConstraint("wikidata_id", name="uq_authors_wikidata_id"),
    )

    # Link from existing shop_authors to canonical authors (filled by matcher).
    op.add_column(
        "shop_authors",
        sa.Column(
            "canonical_author_id",
            sa.Integer,
            sa.ForeignKey("authors.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_shop_authors_canonical_author_id",
        "shop_authors",
        ["canonical_author_id"],
    )

    # ── books ──────────────────────────────────────────────────────────────
    op.create_table(
        "books",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("data_source", _book_data_source_enum(), nullable=False),
        sa.Column("libis_code", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("title_full", sa.Text, nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column(
            "publisher_id",
            sa.Integer,
            sa.ForeignKey("publishers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "series_id",
            sa.Integer,
            sa.ForeignKey("series.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("release_place", sa.Text, nullable=True),
        sa.Column("type", sa.Text, nullable=True),
        sa.Column("format", sa.Text, nullable=True),
        sa.Column("pages", sa.Integer, nullable=True),
        sa.Column("duration", sa.Text, nullable=True),
        sa.Column("dimensions", sa.Text, nullable=True),
        sa.Column("language", sa.Text, nullable=True),
        sa.Column("translated_from", ARRAY(sa.Text), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("cover_url", sa.Text, nullable=True),
        sa.Column(
            "upcoming_release",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("udc_codes", ARRAY(sa.Text), nullable=True),
        sa.Column("subjects", ARRAY(sa.Text), nullable=True),
        sa.Column("audience", sa.Text, nullable=True),
        sa.Column("libis_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("libis_review_count", sa.Integer, nullable=True),
        sa.Column(
            "source_run_id",
            sa.Integer,
            sa.ForeignKey("scrape_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("libis_code", name="uq_books_libis_code"),
    )
    op.create_index("ix_books_publisher_id", "books", ["publisher_id"])
    op.create_index("ix_books_series_id", "books", ["series_id"])
    op.create_index("ix_books_year", "books", ["year"])
    op.create_index("ix_books_data_source", "books", ["data_source"])

    # libis_code is mandatory only for data_source='ibiblioteka' rows.
    op.execute(
        "ALTER TABLE books ADD CONSTRAINT ck_books_libis_code_for_ibiblioteka "
        "CHECK (data_source != 'ibiblioteka' OR libis_code IS NOT NULL)"
    )

    # ── book_isbns ─────────────────────────────────────────────────────────
    op.create_table(
        "book_isbns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "book_id",
            sa.Integer,
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("isbn", sa.Text, nullable=False),
        sa.Column(
            "isbn_type",
            _book_isbn_type_enum(),
            server_default="unknown",
            nullable=False,
        ),
        sa.UniqueConstraint("isbn", name="uq_book_isbns_isbn"),
    )
    op.create_index("ix_book_isbns_book_id", "book_isbns", ["book_id"])

    # ── book_authors ───────────────────────────────────────────────────────
    op.create_table(
        "book_authors",
        sa.Column(
            "book_id",
            sa.Integer,
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "author_id",
            sa.Integer,
            sa.ForeignKey("authors.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role",
            _book_author_role_enum(),
            primary_key=True,
            server_default="author",
        ),
        sa.Column("position", sa.Integer, server_default="0", nullable=False),
    )
    op.create_index("ix_book_authors_author_id", "book_authors", ["author_id"])

    # ── shop_books.book_id ─────────────────────────────────────────────────
    op.add_column(
        "shop_books",
        sa.Column(
            "book_id",
            sa.Integer,
            sa.ForeignKey("books.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_shop_books_book_id", "shop_books", ["book_id"])


def downgrade() -> None:
    op.drop_index("ix_shop_books_book_id", "shop_books")
    op.drop_column("shop_books", "book_id")

    op.drop_index("ix_book_authors_author_id", "book_authors")
    op.drop_table("book_authors")

    op.drop_index("ix_book_isbns_book_id", "book_isbns")
    op.drop_table("book_isbns")

    op.execute("ALTER TABLE books DROP CONSTRAINT ck_books_libis_code_for_ibiblioteka")
    op.drop_index("ix_books_data_source", "books")
    op.drop_index("ix_books_year", "books")
    op.drop_index("ix_books_series_id", "books")
    op.drop_index("ix_books_publisher_id", "books")
    op.drop_table("books")

    op.drop_index("ix_shop_authors_canonical_author_id", "shop_authors")
    op.drop_column("shop_authors", "canonical_author_id")

    op.drop_table("authors")
    op.drop_table("series")
    op.drop_table("publishers")

    op.execute("DROP TYPE book_author_role")
    op.execute("DROP TYPE book_isbn_type")
    op.execute("DROP TYPE book_data_source")
