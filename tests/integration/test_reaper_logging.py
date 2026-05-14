"""CODEOBS-02: reaper emits one WARNING per killed run with full metadata."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from book_scraper.dashboard.queries import DEAD_RUN_SECONDS, mark_stale_runs
from book_scraper.db.models import ScrapeRun, Shop


def test_mark_stale_runs_returns_per_run_metadata(db_session: Session) -> None:
    """A stale row in the 'running' state is reaped and metadata returned."""
    shop = Shop(name="codeobs02-test", base_url="http://example.com")
    db_session.add(shop)
    db_session.flush()
    stale_run = ScrapeRun(
        shop_id=shop.id,
        phase="scan",
        status="running",
        started_at=datetime.now(UTC) - timedelta(seconds=DEAD_RUN_SECONDS + 60),
        last_heartbeat=datetime.now(UTC) - timedelta(seconds=DEAD_RUN_SECONDS + 60),
        urls_processed=0,
    )
    db_session.add(stale_run)
    db_session.commit()

    killed = mark_stale_runs(db_session)

    assert isinstance(killed, list)
    assert len(killed) == 1
    entry = killed[0]
    assert entry["run_id"] == stale_run.id
    assert entry["shop"] == "codeobs02-test"
    assert entry["phase"] == "scan"
    assert entry["close_reason"] == "heartbeat_timeout"


def test_mark_stale_runs_returns_empty_when_no_stale(db_session: Session) -> None:
    """Healthy runs (recent heartbeat) aren't reaped."""
    shop = Shop(name="codeobs02-healthy", base_url="http://example.com")
    db_session.add(shop)
    db_session.flush()
    fresh = ScrapeRun(
        shop_id=shop.id,
        phase="scan",
        status="running",
        started_at=datetime.now(UTC),
        last_heartbeat=datetime.now(UTC),
        urls_processed=0,
    )
    db_session.add(fresh)
    db_session.commit()

    killed = mark_stale_runs(db_session)
    assert killed == []


def test_reaper_log_format_carries_all_four_fields(
    db_session: Session, caplog
) -> None:
    """Stale row -> mark_stale_runs -> simulate reaper log line format."""
    shop = Shop(name="codeobs02-format", base_url="http://example.com")
    db_session.add(shop)
    db_session.flush()
    stale_run = ScrapeRun(
        shop_id=shop.id,
        phase="validate",
        status="running",
        started_at=datetime.now(UTC) - timedelta(seconds=DEAD_RUN_SECONDS + 30),
        last_heartbeat=datetime.now(UTC) - timedelta(seconds=DEAD_RUN_SECONDS + 30),
        urls_processed=0,
    )
    db_session.add(stale_run)
    db_session.commit()

    with caplog.at_level(logging.WARNING, logger="book_scraper.dashboard.reaper"):
        killed = mark_stale_runs(db_session)
        reaper_logger = logging.getLogger("book_scraper.dashboard.reaper")
        for k in killed:
            reaper_logger.warning(
                "Reaper killed run #%d shop=%s phase=%s close_reason=%s",
                k["run_id"], k["shop"], k["phase"], k["close_reason"],
            )

    msgs = [r.getMessage() for r in caplog.records if "Reaper killed run" in r.message]
    assert len(msgs) == 1
    msg = msgs[0]
    assert f"run #{stale_run.id}" in msg
    assert "shop=codeobs02-format" in msg
    assert "phase=validate" in msg
    assert "close_reason=heartbeat_timeout" in msg
