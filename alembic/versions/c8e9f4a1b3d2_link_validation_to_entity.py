"""link validation issues to listing or discovered_url

Revision ID: c8e9f4a1b3d2
Revises: b7c4e1d22fa1
Create Date: 2026-04-17 10:30:00.000000

Adds nullable listing_id + discovered_url_id FKs on validation_issues
plus a CHECK constraint forbidding both being populated. We intentionally
allow both NULL during backfill and for issues on URLs that never became
listings and haven't been discovered yet — the spec's "exactly one"
becomes "at most one" at the storage layer.

Backfill picks the listing match first (by shop_id + url), falls back to
the matching discovered_url row otherwise.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8e9f4a1b3d2"
down_revision: Union[str, Sequence[str], None] = "b7c4e1d22fa1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "validation_issues",
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listings.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "validation_issues",
        sa.Column(
            "discovered_url_id",
            sa.Integer(),
            sa.ForeignKey("discovered_urls.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_validation_issues_listing_id",
        "validation_issues",
        ["listing_id"],
    )
    op.create_index(
        "ix_validation_issues_discovered_url_id",
        "validation_issues",
        ["discovered_url_id"],
    )
    op.create_check_constraint(
        "ck_validation_issues_single_entity",
        "validation_issues",
        "NOT (listing_id IS NOT NULL AND discovered_url_id IS NOT NULL)",
    )

    # Backfill: prefer listing match, else the discovered_url row. The
    # MIN aggregation picks a deterministic row when the legacy URL
    # string somehow matched multiple rows (shouldn't happen post
    # b7c4e1d22fa1, but defence in depth).
    op.execute(
        """
        UPDATE validation_issues vi
        SET listing_id = matched.listing_id
        FROM (
            SELECT vi.id AS vi_id, MIN(l.id) AS listing_id
            FROM validation_issues vi
            JOIN scrape_runs sr ON sr.id = vi.scrape_run_id
            JOIN listings l ON l.shop_id = sr.shop_id AND l.url = vi.url
            GROUP BY vi.id
        ) matched
        WHERE vi.id = matched.vi_id
        """
    )
    op.execute(
        """
        UPDATE validation_issues vi
        SET discovered_url_id = matched.du_id
        FROM (
            SELECT vi.id AS vi_id, MIN(du.id) AS du_id
            FROM validation_issues vi
            JOIN scrape_runs sr ON sr.id = vi.scrape_run_id
            JOIN discovered_urls du
              ON du.shop_id = sr.shop_id AND du.url = vi.url
            WHERE vi.listing_id IS NULL
            GROUP BY vi.id
        ) matched
        WHERE vi.id = matched.vi_id
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_validation_issues_single_entity",
        "validation_issues",
        type_="check",
    )
    op.drop_index(
        "ix_validation_issues_discovered_url_id",
        table_name="validation_issues",
    )
    op.drop_index(
        "ix_validation_issues_listing_id",
        table_name="validation_issues",
    )
    op.drop_column("validation_issues", "discovered_url_id")
    op.drop_column("validation_issues", "listing_id")
