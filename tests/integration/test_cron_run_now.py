"""Dashboard 'Run now' endpoint."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db
from book_scraper.db.repo import create_cron_job, upsert_shop


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_post_run_now_invokes_exec_run(
    client: TestClient, db_session: Session
) -> None:
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

    fake_container = MagicMock()
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [fake_container]

    with patch(
        "book_scraper.dashboard.routes.cron.get_docker_client",
        return_value=fake_client,
    ):
        r = client.post(f"/cron/{job.id}/run", follow_redirects=False)

    assert r.status_code in (200, 303)
    fake_container.exec_run.assert_called_once()
    kwargs = fake_container.exec_run.call_args.kwargs
    cmd = fake_container.exec_run.call_args.args[0]
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    assert "scrapy" in cmd_str
    assert "crawl" in cmd_str
    assert "discover" in cmd_str
    assert "shop=vaga" in cmd_str
    assert "strategy=sitemap" in cmd_str
    assert kwargs.get("detach") is True


def test_post_run_now_handles_missing_docker(
    client: TestClient, db_session: Session
) -> None:
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

    with patch(
        "book_scraper.dashboard.routes.cron.get_docker_client",
        return_value=None,
    ):
        r = client.post(f"/cron/{job.id}/run", follow_redirects=False)
    assert r.status_code == 503


def test_post_run_now_disabled_job_still_runs(
    client: TestClient, db_session: Session
) -> None:
    """Run now bypasses the enabled flag — admin override."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session,
        shop_id=shop.id,
        phase="scan",
        strategy=None,
        args="-a rescrape=true",
        cron_expression="0 3 * * *",
        enabled=False,
    )
    db_session.commit()

    fake_container = MagicMock()
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [fake_container]

    with patch(
        "book_scraper.dashboard.routes.cron.get_docker_client",
        return_value=fake_client,
    ):
        r = client.post(f"/cron/{job.id}/run", follow_redirects=False)

    assert r.status_code in (200, 303)
    fake_container.exec_run.assert_called_once()
    cmd = fake_container.exec_run.call_args.args[0]
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    assert "scan" in cmd_str
    assert "rescrape=true" in cmd_str
