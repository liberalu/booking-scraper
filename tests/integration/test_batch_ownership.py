"""ScanService.flush_progress must NOT touch scrape_url_items terminal state.

Per the live observability spec, terminal state on scrape_url_items
(status, done_at, http_status, error_reason, response_bytes) is owned
by the spider's immediate `_mark_response` path. The batched flush is
explicitly stripped of writes to those columns. This test pins that
ownership split so a future regression is loud.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from book_scraper.db.models import (
    DiscoveredUrl,
    ScrapeRun,
    ScrapeUrlItem,
    Shop,
)
from book_scraper.services.scan import ScanService


def _seed(db_session: Session) -> tuple[Shop, ScrapeRun, ScrapeUrlItem]:
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()

    discovered = DiscoveredUrl(
        shop_id=shop.id,
        url="https://vaga.lt/book/a",
        normalized_url="https://vaga.lt/book/a",
        source="sitemap",
        url_type="product",
        fail_count=0,
    )
    db_session.add(discovered)

    run = ScrapeRun(
        shop_id=shop.id,
        phase="scan",
        status="running",
    )
    db_session.add(run)
    db_session.flush()

    item = ScrapeUrlItem(
        run_id=run.id,
        shop_id=shop.id,
        discovered_url_id=discovered.id,
        url=discovered.url,
        url_type="product",
        status="pending",
    )
    db_session.add(item)
    db_session.commit()
    return shop, run, item


def test_flush_progress_does_not_modify_scrape_url_item_terminal_state(
    db_session: Session,
) -> None:
    shop, run, item = _seed(db_session)

    # Snapshot terminal-state columns before flush_progress.
    item_before = db_session.get(ScrapeUrlItem, item.id)
    assert item_before is not None
    snapshot = {
        "status": item_before.status,
        "done_at": item_before.done_at,
        "http_status": item_before.http_status,
        "response_bytes": item_before.response_bytes,
    }

    # Build an update that, in the OLD batched ownership model, would
    # have terminated the row to status='done'. With the new ownership,
    # flush_progress should leave the scrape_url_items row alone.
    service = ScanService(db_session)
    service.flush_progress(
        run.id,
        urls_processed=1,
        url_status_updates=[
            {
                "url_id": item.discovered_url_id,
                "http_status": 200,
                "url_type": "product",
                "increment_fail": False,
                "book_score": 5,
                "is_book_product": True,
                "book_score_reasons": ["isbn_present"],
            }
        ],
    )

    # Re-read and verify NONE of the terminal-state columns moved.
    db_session.expire_all()
    after = db_session.get(ScrapeUrlItem, item.id)
    assert after is not None
    assert after.status == snapshot["status"]
    assert after.done_at == snapshot["done_at"]
    assert after.http_status == snapshot["http_status"]
    assert after.response_bytes == snapshot["response_bytes"]


def test_finish_scan_does_not_modify_scrape_url_item_terminal_state(
    db_session: Session,
) -> None:
    shop, run, item = _seed(db_session)

    item_before = db_session.get(ScrapeUrlItem, item.id)
    assert item_before is not None
    snapshot = {
        "status": item_before.status,
        "done_at": item_before.done_at,
        "http_status": item_before.http_status,
        "response_bytes": item_before.response_bytes,
    }

    service = ScanService(db_session)
    service.finish_scan(
        run.id,
        urls_processed=1,
        url_status_updates=[
            {
                "url_id": item.discovered_url_id,
                "http_status": 503,
                "url_type": "product",
                "increment_fail": True,
            }
        ],
        reason="finished",
    )

    db_session.expire_all()
    after = db_session.get(ScrapeUrlItem, item.id)
    assert after is not None
    assert after.status == snapshot["status"]
    assert after.done_at == snapshot["done_at"]
    assert after.http_status == snapshot["http_status"]
    assert after.response_bytes == snapshot["response_bytes"]
