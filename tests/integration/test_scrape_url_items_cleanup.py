"""Cleanup of scrape_url_items when a run finishes."""

from book_scraper.db.models import DiscoveredUrl, ScrapeUrlItem
from book_scraper.db.repo import upsert_shop
from book_scraper.services.scan import ScanService


def test_finish_scan_deletes_staging_rows(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/a",
            normalized_url="https://vaga.lt/a",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 1

    service.finish_scan(
        plan.run_id, urls_processed=0, url_status_updates=[], reason="finished"
    )

    remaining = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count()
    assert remaining == 0, "scrape_url_items for a finished run must be deleted"


def test_finish_scan_failed_run_also_deletes_rows(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/b",
            normalized_url="https://vaga.lt/b",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)
    service.finish_scan(
        plan.run_id, urls_processed=0, url_status_updates=[], reason="cancelled"
    )

    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 0
