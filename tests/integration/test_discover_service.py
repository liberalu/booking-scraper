"""DiscoverService: prepare_discover seeds scrape_url_items per strategy."""

from types import SimpleNamespace

from book_scraper.db.models import ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import upsert_shop
from book_scraper.services.discover import DiscoverService


def _config(sitemap_url="https://vaga.lt/sitemap.xml",
            categories_url="https://vaga.lt/knygos?page={page}",
            full_crawl_start_url="https://vaga.lt/"):
    return SimpleNamespace(
        discover=SimpleNamespace(
            sitemap=SimpleNamespace(url=sitemap_url),
            categories=SimpleNamespace(url=categories_url),
            full_crawl=SimpleNamespace(start_url=full_crawl_start_url),
        )
    )


def test_prepare_discover_sitemap_seeds_one_item(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    assert items[0].url == "https://vaga.lt/sitemap.xml"
    assert items[0].url_type == "sitemap"
    assert items[0].status == "pending"

    run = db_session.get(ScrapeRun, plan.run_id)
    assert run.phase == "discover_sitemap"
    assert run.status == "running"


def test_prepare_discover_categories_seeds_page_one(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "categories", _config())

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    assert "page=1" in items[0].url
    assert items[0].url_type == "category_page"


def test_prepare_discover_full_crawl_seeds_start_url(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "full_crawl", _config())

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    assert items[0].url == "https://vaga.lt/"
    assert items[0].url_type == "crawl"


def test_prepare_discover_resumes_running_run_with_pending_items(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    first = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())

    second = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())
    assert second.run_id == first.run_id  # resumed, not new


def test_finish_discover_deletes_staging_rows(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 1

    service.finish_discover(plan.run_id, urls_processed=1, reason="finished")
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 0
