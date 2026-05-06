"""CRUD helpers for cron_jobs."""

from book_scraper.db.repo import (
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    list_cron_jobs,
    toggle_cron_job,
    update_cron_job,
    update_cron_job_last_run,
    upsert_shop,
)


def test_create_and_list_cron_job(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
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

    jobs = list_cron_jobs(db_session)
    assert len(jobs) == 1
    assert jobs[0].id == job.id
    assert jobs[0].cron_expression == "0 2 * * *"
    assert jobs[0].enabled is True
    assert jobs[0].last_run_at is None


def test_toggle_cron_job(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
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

    toggle_cron_job(db_session, job.id)
    db_session.commit()
    assert get_cron_job(db_session, job.id).enabled is False

    toggle_cron_job(db_session, job.id)
    db_session.commit()
    assert get_cron_job(db_session, job.id).enabled is True


def test_update_cron_job(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
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

    update_cron_job(
        db_session, job.id, cron_expression="0 4 * * *", args="-a rescrape=true"
    )
    db_session.commit()
    got = get_cron_job(db_session, job.id)
    assert got.cron_expression == "0 4 * * *"
    assert got.args == "-a rescrape=true"


def test_delete_cron_job(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
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

    delete_cron_job(db_session, job.id)
    db_session.commit()
    assert get_cron_job(db_session, job.id) is None
    assert list_cron_jobs(db_session) == []


def test_update_last_run(db_session):
    from datetime import UTC, datetime

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
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

    when = datetime.now(UTC)
    update_cron_job_last_run(db_session, job.id, when)
    db_session.commit()
    assert get_cron_job(db_session, job.id).last_run_at == when


def test_chain_to_job_id_create_and_update(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job_a = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="discover",
        strategy="sitemap",
        args="",
        cron_expression="0 2 * * *",
        enabled=True,
        chain_to_job_id=None,
    )
    db_session.commit()

    job_b = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="scan",
        strategy=None,
        args="",
        cron_expression="0 3 * * *",
        enabled=True,
        chain_to_job_id=job_a.id,
    )
    db_session.commit()

    # chain FK is stored
    assert get_cron_job(db_session, job_b.id).chain_to_job_id == job_a.id

    # update clears chain
    update_cron_job(db_session, job_b.id, chain_to_job_id=None)
    db_session.commit()
    assert get_cron_job(db_session, job_b.id).chain_to_job_id is None

    # update sets chain
    update_cron_job(db_session, job_b.id, chain_to_job_id=job_a.id)
    db_session.commit()
    assert get_cron_job(db_session, job_b.id).chain_to_job_id == job_a.id


def test_chain_to_job_id_set_null_on_delete(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job_a = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *", enabled=True,
    )
    job_b = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 3 * * *", enabled=True,
        chain_to_job_id=job_a.id,
    )
    db_session.commit()

    delete_cron_job(db_session, job_a.id)
    db_session.commit()

    db_session.expire(job_b)
    assert get_cron_job(db_session, job_b.id).chain_to_job_id is None
