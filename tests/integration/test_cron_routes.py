"""Dashboard /cron routes."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db
from book_scraper.db.repo import (
    create_cron_job,
    get_cron_job,
    list_cron_jobs,
    upsert_shop,
)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_cron_page_returns_200(client: TestClient, db_session: Session) -> None:
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="discover",
        strategy="sitemap",
        args="",
        cron_expression="0 2 * * *",
        enabled=True,
    )
    db_session.commit()

    r = client.get("/cron")
    assert r.status_code == 200
    assert "0 2 * * *" in r.text
    assert "discover" in r.text


def test_post_cron_creates_job(client: TestClient, db_session: Session) -> None:
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    r = client.post(
        "/cron",
        data={
            "shop_id": shop.id,
            "phase": "scan",
            "strategy": "",
            "args": "-a rescrape=true",
            "cron_expression": "0 4 * * *",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    db_session.expire_all()
    jobs = list_cron_jobs(db_session)
    assert any(j.cron_expression == "0 4 * * *" for j in jobs)


def test_post_toggle_flips_enabled(client: TestClient, db_session: Session) -> None:
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

    r = client.post(f"/cron/{job.id}/toggle", follow_redirects=False)
    assert r.status_code == 303

    db_session.expire_all()
    toggled = get_cron_job(db_session, job.id)
    assert toggled is not None
    assert toggled.enabled is False


def test_post_delete_removes_job(client: TestClient, db_session: Session) -> None:
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

    r = client.post(f"/cron/{job.id}/delete", follow_redirects=False)
    assert r.status_code == 303

    db_session.expire_all()
    assert get_cron_job(db_session, job.id) is None
