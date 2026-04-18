"""End-to-end: prepare_discover seeds queue, spider consumes, cleanup fires."""

from types import SimpleNamespace

from book_scraper.db.models import ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import (
    create_cron_job,
    get_cron_job,
    upsert_shop,
)
from book_scraper.services.discover import DiscoverService


def _config():
    return SimpleNamespace(
        discover=SimpleNamespace(
            sitemap=SimpleNamespace(url="https://vaga.lt/sitemap.xml"),
            categories=SimpleNamespace(url="https://vaga.lt/p?page={page}"),
            full_crawl=SimpleNamespace(start_url="https://vaga.lt/"),
        )
    )


def test_finish_discover_marks_last_run_and_cleans_up(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    job = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="discover",
        strategy="sitemap",
        args="",
        cron_expression="0 2 * * *",
        enabled=True,
    )
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 1

    service.finish_discover(plan.run_id, urls_processed=1, reason="finished")

    db_session.expire_all()
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 0
    assert db_session.get(ScrapeRun, plan.run_id).status == "completed"
    assert get_cron_job(db_session, job.id).last_run_at is not None
