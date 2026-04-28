"""PR 3 of scrape_failures migration: drop scrape_url_items.error_reason and clean legacy validation_issues

Revision ID: 5ab883ccbf29
Revises: d3e8b1f4a721
Create Date: 2026-04-28 19:48:28.117607

PR 3 of docs/superpowers/plans/2026-04-28-scrape-failures-migration.md.
After PR 1 (`scrape_failures` table) and PR 2 (readers switched), the
queue's denormalized `error_reason` column has no remaining writers or
readers — drop it. Also delete the legacy `http_4xx`/`http_5xx`/
`request_error` rows in `validation_issues` that the spider used to
double-write; their factual content lives in `scrape_failures` now.

`empty_response` and `redirect_to_homepage` validation_issues stay —
they fire on HTTP 200 successful fetches and are page-quality signals,
not transport failures.

`http_status` on `scrape_url_items` stays as the last-response cache
(it's written for both success and failure, used by the History card
and the sortable URL list). Diverges from the original plan; documented
in the plan's PR 3 section as an explicitly optional drop.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5ab883ccbf29"
down_revision: Union[str, Sequence[str], None] = "d3e8b1f4a721"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Delete the legacy double-written validation_issues rows. Their
    #    factual content has lived in scrape_failures since PR 1; PR 3
    #    of the same migration stops the spider writing them.
    op.execute(
        """
        DELETE FROM validation_issues
         WHERE issue IN ('http_4xx', 'http_5xx', 'request_error')
        """
    )

    # 2. Drop the denormalized error_reason column on scrape_url_items.
    #    Every reader sources from scrape_failures.error_reason now.
    op.drop_column("scrape_url_items", "error_reason")


def downgrade() -> None:
    # Restore the column with a best-effort backfill from the latest
    # scrape_failures event per item. Currently-failed rows recover
    # their reason; done/pending rows get NULL (which is what they had
    # on a healthy queue before the column was dropped).
    op.add_column(
        "scrape_url_items",
        sa.Column("error_reason", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE scrape_url_items sui
           SET error_reason = sf.error_reason
          FROM (
            SELECT DISTINCT ON (scrape_url_item_id)
                   scrape_url_item_id, error_reason
              FROM scrape_failures
             ORDER BY scrape_url_item_id, occurred_at DESC, id DESC
          ) sf
         WHERE sui.id = sf.scrape_url_item_id
           AND sui.status = 'failed'
        """
    )
    # The deleted validation_issues rows are NOT restored — PR 1 already
    # backfilled the equivalent into scrape_failures; rebuilding here
    # would risk duplication. Acceptable for downgrade; the original
    # rows are recoverable from a backup if needed.
