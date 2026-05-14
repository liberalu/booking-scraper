"""CODEOBS-06: chain_skipped event is recorded when cron-chain parent fails."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from book_scraper.db import scrape_run_events as run_event_types
from book_scraper.db.models import ScrapeRun, ScrapeRunEvent, Shop
from book_scraper.db.repo import emit_scrape_run_event


def test_chain_skipped_constant_value() -> None:
    assert run_event_types.CHAIN_SKIPPED == "chain_skipped"


def test_chain_skipped_in_event_types() -> None:
    assert "chain_skipped" in run_event_types.EVENT_TYPES


def test_chain_skipped_event_can_be_inserted(db_session: Session) -> None:
    """DB check constraint accepts the new event_type."""
    shop = Shop(name="codeobs06-test", base_url="http://example.com")
    db_session.add(shop)
    db_session.flush()
    run = ScrapeRun(
        shop_id=shop.id,
        phase="scan",
        status="failed",
        started_at=datetime.now(UTC),
        urls_processed=0,
    )
    db_session.add(run)
    db_session.flush()

    emit_scrape_run_event(
        db_session,
        run.id,
        run_event_types.CHAIN_SKIPPED,
        payload={"parent_reason": "stall_timeout", "cron_job_id": 1},
    )
    db_session.commit()

    rows = (
        db_session.query(ScrapeRunEvent)
        .filter(
            ScrapeRunEvent.run_id == run.id,
            ScrapeRunEvent.event_type == "chain_skipped",
        )
        .all()
    )
    assert len(rows) == 1
    assert rows[0].payload == {"parent_reason": "stall_timeout", "cron_job_id": 1}
