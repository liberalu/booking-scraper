"""Integration tests for ScanService — hits real PostgreSQL."""

import pytest

from book_scraper.db.repo import (
    create_scrape_run,
    update_discovered_url_status,
    upsert_discovered_url,
    upsert_shop,
)
from book_scraper.services.scan import ScanService


# ---------------------------------------------------------------------------
# Fixtures shared by ScrapeUrlItem tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def shop(db_session):
    return upsert_shop(db_session, name="item_shop", base_url="https://item.lt")


@pytest.fixture()
def scrape_run(db_session, shop):
    run = create_scrape_run(db_session, shop.id, "scan")
    db_session.flush()
    return run


@pytest.fixture()
def discovered_urls(db_session, shop):
    from book_scraper.db.models import DiscoveredUrl

    urls = []
    for i in range(5):
        du = DiscoveredUrl(
            shop_id=shop.id,
            url=f"https://item.lt/book-{i}",
            normalized_url=f"https://item.lt/book-{i}",
            source="sitemap",
        )
        db_session.add(du)
        urls.append(du)
    db_session.flush()
    return urls


@pytest.mark.integration
class TestScanServicePrepareScan:
    def test_creates_run_and_returns_plan(self, db_session):
        shop = upsert_shop(db_session, name="svc_shop", base_url="https://svc.lt")
        upsert_discovered_url(db_session, shop.id, "https://svc.lt/book-1", "sitemap")
        upsert_discovered_url(db_session, shop.id, "https://svc.lt/book-2", "sitemap")

        service = ScanService(db_session)
        plan = service.prepare_scan("svc_shop", "https://svc.lt", {})

        assert plan.run_id is not None
        assert plan.urls_total == 2
        assert plan.urls_skipped == 0

    def test_skips_already_done_urls(self, db_session):
        shop = upsert_shop(db_session, name="skip_shop", base_url="https://sk.lt")
        upsert_discovered_url(db_session, shop.id, "https://sk.lt/book-1", "sitemap")
        upsert_discovered_url(db_session, shop.id, "https://sk.lt/book-2", "sitemap")

        # Mark book-1 as already scraped (url_type='product')
        from book_scraper.db.models import DiscoveredUrl

        url_record = (
            db_session.query(DiscoveredUrl)
            .filter_by(url="https://sk.lt/book-1")
            .first()
        )
        update_discovered_url_status(
            db_session, url_id=url_record.id, http_status=200, url_type="product"
        )
        db_session.flush()

        service = ScanService(db_session)
        plan = service.prepare_scan("skip_shop", "https://sk.lt", {})

        from book_scraper.db.repo import get_pending_scrape_url_items

        items = get_pending_scrape_url_items(db_session, plan.run_id)
        urls = [i["url"] for i in items]
        assert "https://sk.lt/book-1" not in urls
        assert "https://sk.lt/book-2" in urls
        assert plan.urls_skipped == 1

    def test_marks_stale_runs_failed(self, db_session):
        shop = upsert_shop(db_session, name="stale_svc", base_url="https://st.lt")
        upsert_discovered_url(db_session, shop.id, "https://st.lt/book", "sitemap")
        stale_run = create_scrape_run(db_session, shop.id, "scan")
        db_session.flush()

        service = ScanService(db_session)
        service.prepare_scan("stale_svc", "https://st.lt", {})

        db_session.refresh(stale_run)
        assert stale_run.status == "failed"

    def test_raises_when_no_discovered_urls(self, db_session):
        upsert_shop(db_session, name="no_urls", base_url="https://nu.lt")

        service = ScanService(db_session)
        with pytest.raises(RuntimeError, match="No discovered URLs"):
            service.prepare_scan("no_urls", "https://nu.lt", {})

    def test_rescrape_includes_already_done_urls(self, db_session):
        shop = upsert_shop(db_session, name="rescrape_shop", base_url="https://rs.lt")
        url1 = upsert_discovered_url(
            db_session, shop.id, "https://rs.lt/book-1", "sitemap"
        )
        upsert_discovered_url(db_session, shop.id, "https://rs.lt/book-2", "sitemap")

        # Mark book-1 as already scraped
        update_discovered_url_status(
            db_session, url_id=url1.id, http_status=200, url_type="product"
        )
        db_session.flush()

        service = ScanService(db_session)
        plan = service.prepare_scan("rescrape_shop", "https://rs.lt", {}, rescrape=True)

        from book_scraper.db.repo import get_pending_scrape_url_items

        items = get_pending_scrape_url_items(db_session, plan.run_id)
        urls = [i["url"] for i in items]
        assert "https://rs.lt/book-1" in urls
        assert "https://rs.lt/book-2" in urls
        assert plan.urls_skipped == 0

    def test_includes_freshness_warnings(self, db_session):
        shop = upsert_shop(db_session, name="warn_shop", base_url="https://w.lt")
        upsert_discovered_url(db_session, shop.id, "https://w.lt/book", "sitemap")

        config = {
            "discover": {
                "sitemap": {"url": "https://w.lt/sitemap.xml", "max_age_hours": 168}
            }
        }
        service = ScanService(db_session)
        plan = service.prepare_scan("warn_shop", "https://w.lt", config)

        # No completed discover run exists → should warn
        assert len(plan.freshness_warnings) == 1
        assert "No completed" in plan.freshness_warnings[0]


@pytest.mark.integration
class TestScanServiceFinishScan:
    def test_completes_run(self, db_session):
        shop = upsert_shop(db_session, name="fin_shop", base_url="https://fin.lt")
        run = create_scrape_run(db_session, shop.id, "scan", urls_total=10)
        db_session.flush()

        service = ScanService(db_session)
        service.finish_scan(
            run.id, urls_processed=8, url_status_updates=[], reason="finished"
        )

        db_session.refresh(run)
        assert run.status == "completed"
        assert run.urls_processed == 8
        assert run.finished_at is not None

    def test_marks_failed_on_non_finished_reason(self, db_session):
        shop = upsert_shop(db_session, name="fail_shop", base_url="https://fail.lt")
        run = create_scrape_run(db_session, shop.id, "scan")
        db_session.flush()

        service = ScanService(db_session)
        service.finish_scan(
            run.id, urls_processed=3, url_status_updates=[], reason="shutdown"
        )

        db_session.refresh(run)
        assert run.status == "failed"

    def test_processes_url_status_updates(self, db_session):
        shop = upsert_shop(db_session, name="upd_shop", base_url="https://upd.lt")
        url_record = upsert_discovered_url(
            db_session, shop.id, "https://upd.lt/book", "sitemap"
        )
        run = create_scrape_run(db_session, shop.id, "scan")
        db_session.flush()

        updates = [
            {
                "url_id": url_record.id,
                "http_status": 200,
                "url_type": "product",
                "increment_fail": False,
            },
        ]

        service = ScanService(db_session)
        service.finish_scan(
            run.id,
            urls_processed=1,
            url_status_updates=updates,
            reason="finished",
        )

        db_session.refresh(url_record)
        assert url_record.last_http_status == 200
        assert url_record.url_type == "product"


# ---------------------------------------------------------------------------
# ScrapeUrlItem repo function tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_prepare_scrape_url_items_inserts_pending_rows(
    db_session, shop, scrape_run, discovered_urls
):
    """prepare_scrape_url_items inserts all URL records as 'pending'."""
    from book_scraper.db.repo import (
        get_pending_scrape_url_items,
        prepare_scrape_url_items,
    )

    url_records = discovered_urls[:3]
    prepare_scrape_url_items(db_session, shop.id, scrape_run.id, url_records)
    db_session.commit()

    items = get_pending_scrape_url_items(db_session, scrape_run.id)
    assert len(items) == 3
    urls = {item["url"] for item in items}
    assert urls == {u.url for u in url_records}
    for item in items:
        assert "id" in item
        assert "url" in item
        assert "discovered_url_id" in item


@pytest.mark.integration
def test_mark_scrape_url_item_done(db_session, shop, scrape_run, discovered_urls):
    """mark_scrape_url_item_done removes item from pending list."""
    from book_scraper.db.repo import (
        get_pending_scrape_url_items,
        mark_scrape_url_item_done,
        prepare_scrape_url_items,
    )

    url_records = discovered_urls[:3]
    prepare_scrape_url_items(db_session, shop.id, scrape_run.id, url_records)
    db_session.commit()

    items = get_pending_scrape_url_items(db_session, scrape_run.id)
    first_id = items[0]["id"]
    mark_scrape_url_item_done(db_session, first_id)
    db_session.commit()

    remaining = get_pending_scrape_url_items(db_session, scrape_run.id)
    assert len(remaining) == 2
    assert all(item["id"] != first_id for item in remaining)


@pytest.mark.integration
def test_reset_processing_scrape_url_items(
    db_session, shop, scrape_run, discovered_urls
):
    """reset_processing_scrape_url_items resets 'processing' to 'pending'."""
    from book_scraper.db.models import ScrapeUrlItem
    from book_scraper.db.repo import (
        get_pending_scrape_url_items,
        prepare_scrape_url_items,
        reset_processing_scrape_url_items,
    )

    url_records = discovered_urls[:2]
    prepare_scrape_url_items(db_session, shop.id, scrape_run.id, url_records)
    db_session.commit()

    # Manually set one to 'processing' (simulates crashed mid-run)
    item = db_session.query(ScrapeUrlItem).filter_by(run_id=scrape_run.id).first()
    item.status = "processing"
    db_session.commit()

    count = reset_processing_scrape_url_items(db_session, scrape_run.id)
    db_session.commit()

    assert count == 1
    pending = get_pending_scrape_url_items(db_session, scrape_run.id)
    assert len(pending) == 2  # both are pending again
