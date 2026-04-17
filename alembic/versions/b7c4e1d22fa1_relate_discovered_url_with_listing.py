"""relate discovered_url with listing

Revision ID: b7c4e1d22fa1
Revises: 1d4700998a48
Create Date: 2026-04-17 10:00:00.000000

Adds normalized_url, listing_id, last_seen_run_id, first_seen_at,
last_seen_at to discovered_urls. Swaps the (shop_id, url) unique
constraint for (shop_id, normalized_url). Backfills normalized_url
from url and listing_id by normalized URL equality against
listings.url. Ambiguous matches are left NULL (logged via RAISE
NOTICE).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from book_scraper.url_utils import normalize_url

revision: str = "b7c4e1d22fa1"
down_revision: Union[str, Sequence[str], None] = "1d4700998a48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "discovered_urls",
        sa.Column("normalized_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "discovered_urls",
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "discovered_urls",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "discovered_urls",
        sa.Column(
            "last_seen_run_id",
            sa.Integer(),
            sa.ForeignKey("scrape_runs.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "discovered_urls",
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listings.id"),
            nullable=True,
        ),
    )

    bind = op.get_bind()

    # Backfill timestamps from the legacy discovered_at column.
    op.execute(
        "UPDATE discovered_urls SET first_seen_at = discovered_at, "
        "last_seen_at = COALESCE(last_checked_at, discovered_at)"
    )

    # Backfill normalized_url in Python (rules live in one place) but
    # push updates back in batches via UPDATE ... FROM (VALUES ...) so
    # we're not round-tripping per row.
    rows = bind.execute(sa.text("SELECT id, url FROM discovered_urls")).fetchall()
    pairs = [(row.id, normalize_url(row.url)) for row in rows]
    BATCH = 500
    for start in range(0, len(pairs), BATCH):
        batch = pairs[start : start + BATCH]
        values_sql = ", ".join(
            f"(:id_{i}, :n_{i})" for i in range(len(batch))
        )
        params: dict[str, object] = {}
        for i, (row_id, norm) in enumerate(batch):
            params[f"id_{i}"] = row_id
            params[f"n_{i}"] = norm
        bind.execute(
            sa.text(
                f"UPDATE discovered_urls AS du "
                f"SET normalized_url = v.n "
                f"FROM (VALUES {values_sql}) AS v(id, n) "
                f"WHERE du.id = v.id"
            ),
            params,
        )

    # Collapse duplicate (shop_id, normalized_url) rows by keeping the
    # oldest row; this is required before the new unique constraint can
    # be enforced. Duplicates get their hits merged into the survivor.
    op.execute(
        """
        WITH ranked AS (
            SELECT id, shop_id, normalized_url,
                   ROW_NUMBER() OVER (
                       PARTITION BY shop_id, normalized_url
                       ORDER BY discovered_at, id
                   ) AS rn
            FROM discovered_urls
        )
        DELETE FROM discovered_urls
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    op.alter_column(
        "discovered_urls",
        "normalized_url",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "discovered_urls",
        "first_seen_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column(
        "discovered_urls",
        "last_seen_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    # Backfill listing_id by normalized-URL equality. Ambiguous matches
    # (same normalized URL mapped to multiple listings) are left NULL.
    op.execute(
        """
        UPDATE discovered_urls du
        SET listing_id = matched.listing_id
        FROM (
            SELECT du.id AS du_id, MIN(l.id) AS listing_id, COUNT(*) AS n
            FROM discovered_urls du
            JOIN listings l
              ON l.shop_id = du.shop_id
             AND l.url = du.url
            GROUP BY du.id
            HAVING COUNT(*) = 1
        ) matched
        WHERE du.id = matched.du_id
        """
    )

    op.drop_constraint("uq_discovered_urls_shop_url", "discovered_urls", type_="unique")
    op.create_unique_constraint(
        "uq_discovered_urls_shop_normalized",
        "discovered_urls",
        ["shop_id", "normalized_url"],
    )
    op.create_index(
        "ix_discovered_urls_listing_id",
        "discovered_urls",
        ["listing_id"],
    )
    op.create_index(
        "ix_discovered_urls_last_seen_run_id",
        "discovered_urls",
        ["last_seen_run_id"],
    )
    op.drop_column("discovered_urls", "discovered_at")


def downgrade() -> None:
    op.add_column(
        "discovered_urls",
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE discovered_urls SET discovered_at = first_seen_at")
    op.alter_column(
        "discovered_urls",
        "discovered_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.drop_index(
        "ix_discovered_urls_last_seen_run_id", table_name="discovered_urls"
    )
    op.drop_index("ix_discovered_urls_listing_id", table_name="discovered_urls")
    op.drop_constraint(
        "uq_discovered_urls_shop_normalized", "discovered_urls", type_="unique"
    )
    op.create_unique_constraint(
        "uq_discovered_urls_shop_url",
        "discovered_urls",
        ["shop_id", "url"],
    )
    op.drop_column("discovered_urls", "listing_id")
    op.drop_column("discovered_urls", "last_seen_run_id")
    op.drop_column("discovered_urls", "last_seen_at")
    op.drop_column("discovered_urls", "first_seen_at")
    op.drop_column("discovered_urls", "normalized_url")
