"""rename listings to shop_books

Revision ID: 7857873aa4bb
Revises: 905fbbbc4372
Create Date: 2026-04-17 16:31:10.757280

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7857873aa4bb'
down_revision: Union[str, Sequence[str], None] = '905fbbbc4372'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop CHECK that references the old column name — recreated below.
    op.drop_constraint(
        "ck_validation_issues_single_entity",
        "validation_issues",
        type_="check",
    )

    # 2. Rename the enum type.
    op.execute("ALTER TYPE listing_type RENAME TO shop_book_type")

    # 3. Rename FK columns (tables still have old names here).
    op.alter_column("prices", "listing_id", new_column_name="shop_book_id")
    op.alter_column("listing_changes", "listing_id", new_column_name="shop_book_id")
    op.alter_column("listing_attributes", "listing_id", new_column_name="shop_book_id")
    op.alter_column(
        "listing_field_updates", "listing_id", new_column_name="shop_book_id"
    )
    op.alter_column("listing_authors", "listing_id", new_column_name="shop_book_id")
    op.alter_column("discovered_urls", "listing_id", new_column_name="shop_book_id")
    op.alter_column("validation_issues", "listing_id", new_column_name="shop_book_id")

    # 4. Rename tables.
    op.rename_table("listings", "shop_books")
    op.rename_table("listing_authors", "shop_book_authors")
    op.rename_table("listing_attributes", "shop_book_attributes")
    op.rename_table("listing_changes", "shop_book_changes")
    op.rename_table("listing_field_updates", "shop_book_field_updates")

    # 5. Rename constraints.
    op.execute(
        "ALTER TABLE shop_books RENAME CONSTRAINT uq_listing_shop_url "
        "TO uq_shop_book_shop_url"
    )
    op.execute(
        "ALTER TABLE shop_book_attributes RENAME CONSTRAINT "
        "uq_listing_attribute_listing_key TO uq_shop_book_attribute_shop_book_key"
    )
    op.execute(
        "ALTER TABLE shop_book_field_updates RENAME CONSTRAINT "
        "uq_listing_field_updates_listing_field TO "
        "uq_shop_book_field_updates_shop_book_field"
    )

    # 6. Rename indexes.
    op.execute(
        "ALTER INDEX ix_listing_field_updates_listing_field "
        "RENAME TO ix_shop_book_field_updates_shop_book_field"
    )
    op.execute(
        "ALTER INDEX ix_discovered_urls_listing_id "
        "RENAME TO ix_discovered_urls_shop_book_id"
    )
    op.execute(
        "ALTER INDEX ix_listing_attributes_listing_id "
        "RENAME TO ix_shop_book_attributes_shop_book_id"
    )
    op.execute(
        "ALTER INDEX ix_listing_attributes_key "
        "RENAME TO ix_shop_book_attributes_key"
    )
    op.execute(
        "ALTER INDEX ix_listing_authors_author_id "
        "RENAME TO ix_shop_book_authors_author_id"
    )
    op.execute(
        "ALTER INDEX ix_listing_changes_listing_id "
        "RENAME TO ix_shop_book_changes_shop_book_id"
    )
    op.execute(
        "ALTER INDEX ix_validation_issues_listing_id "
        "RENAME TO ix_validation_issues_shop_book_id"
    )

    # 7. Recreate CHECK with the new column name.
    op.create_check_constraint(
        "ck_validation_issues_single_entity",
        "validation_issues",
        "NOT (shop_book_id IS NOT NULL AND discovered_url_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_validation_issues_single_entity",
        "validation_issues",
        type_="check",
    )

    op.execute(
        "ALTER INDEX ix_validation_issues_shop_book_id "
        "RENAME TO ix_validation_issues_listing_id"
    )
    op.execute(
        "ALTER INDEX ix_shop_book_changes_shop_book_id "
        "RENAME TO ix_listing_changes_listing_id"
    )
    op.execute(
        "ALTER INDEX ix_shop_book_authors_author_id "
        "RENAME TO ix_listing_authors_author_id"
    )
    op.execute(
        "ALTER INDEX ix_shop_book_attributes_key "
        "RENAME TO ix_listing_attributes_key"
    )
    op.execute(
        "ALTER INDEX ix_shop_book_attributes_shop_book_id "
        "RENAME TO ix_listing_attributes_listing_id"
    )
    op.execute(
        "ALTER INDEX ix_discovered_urls_shop_book_id "
        "RENAME TO ix_discovered_urls_listing_id"
    )
    op.execute(
        "ALTER INDEX ix_shop_book_field_updates_shop_book_field "
        "RENAME TO ix_listing_field_updates_listing_field"
    )

    op.execute(
        "ALTER TABLE shop_book_field_updates RENAME CONSTRAINT "
        "uq_shop_book_field_updates_shop_book_field TO "
        "uq_listing_field_updates_listing_field"
    )
    op.execute(
        "ALTER TABLE shop_book_attributes RENAME CONSTRAINT "
        "uq_shop_book_attribute_shop_book_key TO uq_listing_attribute_listing_key"
    )
    op.execute(
        "ALTER TABLE shop_books RENAME CONSTRAINT uq_shop_book_shop_url "
        "TO uq_listing_shop_url"
    )

    op.rename_table("shop_book_field_updates", "listing_field_updates")
    op.rename_table("shop_book_changes", "listing_changes")
    op.rename_table("shop_book_attributes", "listing_attributes")
    op.rename_table("shop_book_authors", "listing_authors")
    op.rename_table("shop_books", "listings")

    op.alter_column("validation_issues", "shop_book_id", new_column_name="listing_id")
    op.alter_column("discovered_urls", "shop_book_id", new_column_name="listing_id")
    op.alter_column("listing_authors", "shop_book_id", new_column_name="listing_id")
    op.alter_column(
        "listing_field_updates", "shop_book_id", new_column_name="listing_id"
    )
    op.alter_column("listing_attributes", "shop_book_id", new_column_name="listing_id")
    op.alter_column("listing_changes", "shop_book_id", new_column_name="listing_id")
    op.alter_column("prices", "shop_book_id", new_column_name="listing_id")

    op.execute("ALTER TYPE shop_book_type RENAME TO listing_type")

    op.create_check_constraint(
        "ck_validation_issues_single_entity",
        "validation_issues",
        "NOT (listing_id IS NOT NULL AND discovered_url_id IS NOT NULL)",
    )

