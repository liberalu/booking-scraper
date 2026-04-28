"""Integration tests for `scrape_failures` dual-write (PR 1).

Covers `record_scrape_failure` plus the four call sites that flip a
queue row to `failed`:
- `mark_scrape_url_item_response` (success=False)
- `mark_scrape_url_item_failed` (explicit failed marker)
- `abort_processing_scrape_url_items` (run_aborted bulk cleanup)
- `sweep_orphaned_processing_items` (stuck_in_processing reaper)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from book_scraper.db.models import (
    ScrapeFailure,
    ScrapeRun,
    ScrapeUrlItem,
    Shop,
)
from book_scraper.db.repo import (
    abort_processing_scrape_url_items,
    mark_scrape_url_item_failed,
    mark_scrape_url_item_response,
    record_scrape_failure,
    sweep_orphaned_processing_items,
)


def _make_shop_and_run(session: Session) -> tuple[Shop, ScrapeRun]:
    shop = session.query(Shop).filter(Shop.name == "vaga").first()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://www.vaga.lt")
        session.add(shop)
        session.flush()
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    session.add(run)
    session.flush()
    return shop, run


def _make_item(
    session: Session,
    *,
    shop: Shop,
    run: ScrapeRun,
    url: str,
    status: str = "processing",
) -> ScrapeUrlItem:
    item = ScrapeUrlItem(
        run_id=run.id,
        shop_id=shop.id,
        url=url,
        url_type="product",
        status=status,
        claimed_at=datetime.now(UTC) - timedelta(seconds=300),
    )
    session.add(item)
    session.flush()
    return item


@pytest.mark.integration
def test_record_scrape_failure_inserts_row(db_session: Session) -> None:
    shop, run = _make_shop_and_run(db_session)
    item = _make_item(db_session, shop=shop, run=run, url="https://vaga.lt/x")

    failure = record_scrape_failure(
        db_session,
        scrape_url_item=item,
        error_reason="http_503",
        http_status=503,
        response_bytes=42,
    )
    db_session.commit()

    assert failure.id is not None
    assert failure.scrape_url_item_id == item.id
    assert failure.run_id == run.id
    assert failure.shop_id == shop.id
    assert failure.url == item.url
    assert failure.error_reason == "http_503"
    assert failure.http_status == 503
    assert failure.response_bytes == 42
    assert failure.lifecycle_state == "new"
    assert failure.acknowledged_at is None
    assert failure.occurred_at is not None


@pytest.mark.integration
def test_record_scrape_failure_is_append_only_for_retries(
    db_session: Session,
) -> None:
    """A second failure for the same item creates a second row, ordered by
    occurred_at — that's the audit trail PR 1 is meant to provide."""
    shop, run = _make_shop_and_run(db_session)
    item = _make_item(db_session, shop=shop, run=run, url="https://vaga.lt/y")

    t1 = datetime.now(UTC) - timedelta(seconds=10)
    record_scrape_failure(
        db_session,
        scrape_url_item=item,
        error_reason="http_503",
        http_status=503,
        occurred_at=t1,
    )
    record_scrape_failure(
        db_session,
        scrape_url_item=item,
        error_reason="request_error:TimeoutError",
        http_status=None,
        occurred_at=t1 + timedelta(seconds=5),
    )
    db_session.commit()

    rows = (
        db_session.query(ScrapeFailure)
        .filter(ScrapeFailure.scrape_url_item_id == item.id)
        .order_by(ScrapeFailure.occurred_at)
        .all()
    )
    assert len(rows) == 2
    assert rows[0].error_reason == "http_503"
    assert rows[0].http_status == 503
    assert rows[1].error_reason == "request_error:TimeoutError"
    assert rows[1].http_status is None


@pytest.mark.integration
def test_mark_scrape_url_item_response_failure_writes_event(
    db_session: Session,
) -> None:
    shop, run = _make_shop_and_run(db_session)
    item = _make_item(db_session, shop=shop, run=run, url="https://vaga.lt/r")

    mark_scrape_url_item_response(
        db_session,
        item.id,
        success=False,
        http_status=404,
        received_at=datetime.now(UTC).timestamp(),
        response_bytes=120,
        error_reason="http_404",
    )
    db_session.commit()

    failures = (
        db_session.query(ScrapeFailure)
        .filter(ScrapeFailure.scrape_url_item_id == item.id)
        .all()
    )
    assert len(failures) == 1
    assert failures[0].error_reason == "http_404"
    assert failures[0].http_status == 404
    assert failures[0].response_bytes == 120


@pytest.mark.integration
def test_mark_scrape_url_item_response_success_does_not_write_event(
    db_session: Session,
) -> None:
    shop, run = _make_shop_and_run(db_session)
    item = _make_item(db_session, shop=shop, run=run, url="https://vaga.lt/s")

    mark_scrape_url_item_response(
        db_session,
        item.id,
        success=True,
        http_status=200,
        received_at=datetime.now(UTC).timestamp(),
        response_bytes=4096,
    )
    db_session.commit()

    assert (
        db_session.query(ScrapeFailure)
        .filter(ScrapeFailure.scrape_url_item_id == item.id)
        .count()
        == 0
    )


@pytest.mark.integration
def test_mark_scrape_url_item_failed_writes_event(db_session: Session) -> None:
    shop, run = _make_shop_and_run(db_session)
    item = _make_item(db_session, shop=shop, run=run, url="https://vaga.lt/f")

    mark_scrape_url_item_failed(
        db_session,
        item.id,
        http_status=500,
        error_reason="http_500",
    )
    db_session.commit()

    failures = (
        db_session.query(ScrapeFailure)
        .filter(ScrapeFailure.scrape_url_item_id == item.id)
        .all()
    )
    assert len(failures) == 1
    assert failures[0].error_reason == "http_500"
    assert failures[0].http_status == 500


@pytest.mark.integration
def test_abort_processing_writes_one_event_per_item(
    db_session: Session,
) -> None:
    shop, run = _make_shop_and_run(db_session)
    items = [
        _make_item(
            db_session,
            shop=shop,
            run=run,
            url=f"https://vaga.lt/abort/{i}",
            status="processing",
        )
        for i in range(3)
    ]

    aborted = abort_processing_scrape_url_items(db_session, run.id)
    db_session.commit()

    assert aborted == 3
    failures = (
        db_session.query(ScrapeFailure)
        .filter(
            ScrapeFailure.scrape_url_item_id.in_([i.id for i in items])
        )
        .all()
    )
    assert len(failures) == 3
    # All carry the run_aborted detail; error_reason is also "run_aborted"
    # because that's what the queue row was stamped with.
    assert all(f.error_detail == "run_aborted" for f in failures)
    assert all(f.error_reason == "run_aborted" for f in failures)


@pytest.mark.integration
def test_sweep_stuck_processing_writes_event(db_session: Session) -> None:
    """The reaper for `processing` rows on alive runs writes an event with
    error_detail='stuck_in_processing'."""
    shop, run = _make_shop_and_run(db_session)
    # Run is `running`; row was claimed long enough ago to be stuck.
    item = _make_item(
        db_session,
        shop=shop,
        run=run,
        url="https://vaga.lt/stuck",
        status="processing",
    )
    item.claimed_at = datetime.now(UTC) - timedelta(seconds=600)
    db_session.flush()

    cleaned = sweep_orphaned_processing_items(db_session)
    db_session.commit()

    assert cleaned >= 1
    failures = (
        db_session.query(ScrapeFailure)
        .filter(ScrapeFailure.scrape_url_item_id == item.id)
        .all()
    )
    assert len(failures) == 1
    assert failures[0].error_detail == "stuck_in_processing"
    assert failures[0].error_reason == "stuck_in_processing"
