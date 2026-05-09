"""Integration coverage for end-of-run retry helpers."""

from book_scraper.db.models import ScrapeUrlItem
from book_scraper.db.repo import (
    create_scrape_run,
    fetch_retryable_failed_items,
    insert_scrape_url_item,
    reset_failed_items_to_pending,
    upsert_shop,
)


def _seed_run_with_items(session, attempts_per_status):
    """attempts_per_status: list of (status, attempts) tuples."""
    shop = upsert_shop(session, "vaga", "https://www.vaga.lt")
    run = create_scrape_run(session, shop.id, "scan")
    items = []
    for i, (status, attempts) in enumerate(attempts_per_status):
        item = insert_scrape_url_item(
            session,
            run_id=run.id,
            shop_id=shop.id,
            discovered_url_id=None,
            url=f"https://www.vaga.lt/p/{i}",
            url_type="product",
        )
        item.status = status
        item.attempts = attempts
        items.append(item)
    session.flush()
    session.commit()
    return run, items


def test_fetch_retryable_failed_items_excludes_capped(db_session):
    run, items = _seed_run_with_items(
        db_session,
        [
            ("failed", 0),
            ("failed", 1),
            ("failed", 2),
            ("failed", 3),  # capped
            ("done", 1),
            ("pending", 0),
        ],
    )

    eligible = fetch_retryable_failed_items(db_session, run.id, cap=3)

    eligible_ids = {item.id for item in eligible}
    assert eligible_ids == {items[0].id, items[1].id, items[2].id}


def test_fetch_retryable_failed_items_only_current_run(db_session):
    run_a, items_a = _seed_run_with_items(db_session, [("failed", 1)])
    run_b, items_b = _seed_run_with_items(db_session, [("failed", 1)])

    eligible_a = fetch_retryable_failed_items(db_session, run_a.id, cap=3)
    assert {item.id for item in eligible_a} == {items_a[0].id}


def test_reset_failed_items_to_pending_default_keeps_attempts(db_session):
    run, items = _seed_run_with_items(
        db_session,
        [
            ("failed", 1),
            ("failed", 2),
        ],
    )

    reset_failed_items_to_pending(db_session, [items[0].id, items[1].id])
    db_session.commit()

    refreshed = [db_session.get(ScrapeUrlItem, item.id) for item in items]
    assert all(item.status == "pending" for item in refreshed)
    assert refreshed[0].attempts == 1  # untouched
    assert refreshed[1].attempts == 2  # untouched


def test_reset_failed_items_to_pending_with_attempts_reset(db_session):
    """Operator-triggered Retry-failures path resets attempts to 0."""
    run, items = _seed_run_with_items(
        db_session,
        [
            ("failed", 3),  # capped
        ],
    )

    reset_failed_items_to_pending(db_session, [items[0].id], reset_attempts=True)
    db_session.commit()

    refreshed = db_session.get(ScrapeUrlItem, items[0].id)
    assert refreshed.status == "pending"
    assert refreshed.attempts == 0


def test_mark_processing_increments_attempts(db_session):
    import time

    from book_scraper.db.repo import mark_scrape_url_item_processing

    run, items = _seed_run_with_items(db_session, [("pending", 0)])
    db_session.get(type(items[0]), items[0].id)  # ensure attached

    # Run must be 'running' for mark_scrape_url_item_processing to apply.
    run.status = "running"
    db_session.commit()

    mark_scrape_url_item_processing(db_session, items[0].id, time.time())
    db_session.commit()

    refreshed = db_session.get(type(items[0]), items[0].id)
    assert refreshed.status == "processing"
    assert refreshed.attempts == 1


def test_mark_processing_increments_attempts_on_redispatch(db_session):
    import time

    from book_scraper.db.repo import mark_scrape_url_item_processing

    run, items = _seed_run_with_items(db_session, [("pending", 1)])
    run.status = "running"
    db_session.commit()

    mark_scrape_url_item_processing(db_session, items[0].id, time.time())
    db_session.commit()

    refreshed = db_session.get(type(items[0]), items[0].id)
    assert refreshed.attempts == 2
