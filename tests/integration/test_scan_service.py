"""Integration tests for ScanService — hits real PostgreSQL."""

import pytest

from book_scraper.db.repo import (
    create_scrape_run,
    update_discovered_url_status,
    upsert_discovered_url,
    upsert_shop,
)
from book_scraper.services.scan import ScanService


@pytest.mark.integration
class TestScanServicePrepareScan:
    def test_creates_run_and_returns_plan(self, db_session):
        shop = upsert_shop(db_session, name="svc_shop", base_url="https://svc.lt")
        upsert_discovered_url(db_session, shop.id, "https://svc.lt/book-1", "sitemap")
        upsert_discovered_url(db_session, shop.id, "https://svc.lt/book-2", "sitemap")

        service = ScanService(db_session)
        plan = service.prepare_scan("svc_shop", "https://svc.lt", {})

        assert plan.run_id is not None
        assert len(plan.urls_to_scrape) == 2
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

        urls = [u.url for u in plan.urls_to_scrape]
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

        urls = [u.url for u in plan.urls_to_scrape]
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
