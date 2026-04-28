"""rename run_events to scrape_run_events

Revision ID: e7c1a2b9d4f3
Revises: d3e8b1f4a721
Create Date: 2026-04-28

Aligns the table name with the rest of the schema (scrape_runs,
scrape_url_items, scrape_failures) and disambiguates from the existing
per-response JSONL "event log" (book_scraper/event_log.py →
logs/scrapy_events.log).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7c1a2b9d4f3"
down_revision: str | Sequence[str] | None = "5ab883ccbf29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("run_events", "scrape_run_events")
    op.execute("ALTER INDEX ix_run_events_run_id RENAME TO ix_scrape_run_events_run_id")
    op.execute(
        "ALTER INDEX ix_run_events_run_created RENAME TO ix_scrape_run_events_run_created"
    )
    op.execute(
        "ALTER TABLE scrape_run_events "
        "RENAME CONSTRAINT ck_run_events_event_type TO ck_scrape_run_events_event_type"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE scrape_run_events "
        "RENAME CONSTRAINT ck_scrape_run_events_event_type TO ck_run_events_event_type"
    )
    op.execute(
        "ALTER INDEX ix_scrape_run_events_run_created RENAME TO ix_run_events_run_created"
    )
    op.execute("ALTER INDEX ix_scrape_run_events_run_id RENAME TO ix_run_events_run_id")
    op.rename_table("scrape_run_events", "run_events")
