"""A 'running' scrape run with pending scrape_url_items is resumable."""

from book_scraper.db.models import DiscoveredUrl, ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import upsert_shop
from book_scraper.services.scan import ScanService


def _seed_one_url(db_session, shop_id, url="https://vaga.lt/a"):
    db_session.add(
        DiscoveredUrl(
            shop_id=shop_id,
            url=url,
            normalized_url=url,
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()


def test_resume_running_run_with_pending_items(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id)

    service = ScanService(db_session)
    first = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)
    first_run_id = first.run_id
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=first_run_id).count() == 1

    # Second prepare_scan: simulates restart. Should resume, not create a new run.
    second = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)

    assert second.run_id == first_run_id, "must reuse the resumable run"
    assert db_session.query(ScrapeRun).filter_by(status="running").count() == 1
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=first_run_id).count() == 1


def test_new_run_created_when_previous_run_has_no_pending_items(db_session):
    """A run whose items were all finished (and cleaned up) is NOT resumable."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    _seed_one_url(db_session, shop.id)

    service = ScanService(db_session)
    first = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)

    # Finish the first run — this deletes the staging rows (Task 2 cleanup).
    service.finish_scan(
        first.run_id, urls_processed=1, url_status_updates=[], reason="finished"
    )

    # Add a new URL so there is something to do on the second run.
    _seed_one_url(db_session, shop.id, url="https://vaga.lt/b")

    second = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)
    assert second.run_id != first.run_id, "a new run must be created"
