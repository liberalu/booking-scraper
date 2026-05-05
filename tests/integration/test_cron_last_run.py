"""When a scan or discover run completes, its matching cron_job.last_run_at updates."""

from book_scraper.db.models import DiscoveredUrl
from book_scraper.db.repo import (
    create_cron_job,
    get_cron_job,
    upsert_shop,
)
from book_scraper.services.scan import ScanService


def test_scan_finish_updates_matching_cron_job_last_run(db_session):
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
    job = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="scan",
        strategy=None,
        args="",
        cron_expression="0 3 * * *",
        enabled=True,
    )
    db_session.commit()

    assert get_cron_job(db_session, job.id).last_run_at is None

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)
    service.finish_scan(
        plan.run_id, urls_processed=1, url_status_updates=[], reason="finished"
    )

    db_session.expire_all()
    updated = get_cron_job(db_session, job.id).last_run_at
    assert updated is not None


def test_scan_finish_no_matching_job_is_noop(db_session):
    """If no cron_job matches the shop/phase, finish_scan should not crash."""
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
    service.finish_scan(
        plan.run_id, urls_processed=1, url_status_updates=[], reason="finished"
    )


def test_mark_cron_job_ran_if_matches_strategy(db_session):
    """Strategy discriminator: sitemap matches only sitemap job, not categories."""
    from book_scraper.db.repo import mark_cron_job_ran_if_matches

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    sitemap_job = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="discover",
        strategy="sitemap",
        args="",
        cron_expression="0 2 * * *",
        enabled=True,
    )
    categories_job = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="discover",
        strategy="categories",
        args="",
        cron_expression="0 4 * * *",
        enabled=True,
    )
    db_session.commit()

    mark_cron_job_ran_if_matches(db_session, shop.id, "discover", "sitemap")
    db_session.commit()

    db_session.expire_all()
    assert get_cron_job(db_session, sitemap_job.id).last_run_at is not None
    assert get_cron_job(db_session, categories_job.id).last_run_at is None


def test_mark_cron_job_ran_updates_all_matches(db_session):
    """Multiple cron_jobs matching (shop_id, phase, strategy) all get updated."""
    from book_scraper.db.repo import mark_cron_job_ran_if_matches

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    morning = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="scan",
        strategy=None,
        args="",
        cron_expression="0 3 * * *",
        enabled=True,
    )
    evening = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="scan",
        strategy=None,
        args="",
        cron_expression="0 15 * * *",
        enabled=True,
    )
    db_session.commit()

    mark_cron_job_ran_if_matches(db_session, shop.id, "scan", None)
    db_session.commit()

    db_session.expire_all()
    assert get_cron_job(db_session, morning.id).last_run_at is not None
    assert get_cron_job(db_session, evening.id).last_run_at is not None
