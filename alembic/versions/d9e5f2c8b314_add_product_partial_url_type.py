"""add product_partial to url_type enum

Revision ID: d9e5f2c8b314
Revises: c5d8e2f3a9b1
Create Date: 2026-05-08 00:00:00.000000

Adds a new ``url_type`` value that distinguishes URLs we know are
products but whose metadata was only partially captured at discovery
time (e.g. lupasearch yields title+price but no ISBN). The scan spider
promotes ``product_partial`` -> ``product`` after the first successful
fetch, so the partial state is transient.

Why this is needed: ``get_urls_already_scraped`` filters by
``url_type = 'product'`` to skip the delta-scan queue. With everything
that ever entered ``shop_books`` marked as ``product``, lupasearch-
discovered books were never re-fetched even though their ISBN was
NULL. The new value lets those books pass through the delta scan.

"""

from collections.abc import Sequence

from alembic import op

revision: str = "d9e5f2c8b314"
down_revision: str | Sequence[str] | None = "c5d8e2f3a9b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE url_type ADD VALUE IF NOT EXISTS 'product_partial'")


def downgrade() -> None:
    # Postgres does not support removing enum values without recreating the type.
    # Leave as-is; the value will simply be unused after a downgrade.
    pass
