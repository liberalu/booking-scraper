"""unique partial index on shop_books(shop_id, sku) where sku is not null

The pipeline's ``upsert_shop_book`` now matches on SKU first (URL
fallback) so that slug renames and category-path swaps don't create
duplicate shop_book rows for the same physical product. This index
enforces the invariant at the DB level — any future code path that
tries to insert a duplicate (shop_id, sku) gets an immediate
IntegrityError instead of silently going through.

The partial WHERE clause leaves NULL skus alone — vaga's HTML scrape
doesn't always populate one, and we don't want a unique constraint
that would reject every NULL-sku row.

Revision ID: f6a2b3c4d5e7
Revises: e5f1a2b3c4d6
Create Date: 2026-05-05 06:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f6a2b3c4d5e7"
down_revision: Union[str, None] = "e5f1a2b3c4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_shop_books_shop_sku",
        "shop_books",
        ["shop_id", "sku"],
        unique=True,
        postgresql_where="sku IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_shop_books_shop_sku", table_name="shop_books")
