"""CODEOBS-05: _spawn_scrapy_in_container log includes source_run_id."""
from __future__ import annotations
import logging
from unittest.mock import MagicMock, patch


def test_spawn_log_includes_source_run_id(caplog) -> None:
    from book_scraper.dashboard.routes import api
    fake_container = MagicMock()
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [fake_container]
    with patch.object(api, "get_docker_client", return_value=fake_client):
        with caplog.at_level(logging.INFO, logger="book_scraper.dashboard.routes.api"):
            api._spawn_scrapy_in_container(phase="scan", shop="vaga", source_run_id=427)
    msgs = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any("source_run_id=427" in m for m in msgs)


def test_spawn_log_uses_dash_when_no_source_run_id(caplog) -> None:
    from book_scraper.dashboard.routes import api
    fake_container = MagicMock()
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [fake_container]
    with patch.object(api, "get_docker_client", return_value=fake_client):
        with caplog.at_level(logging.INFO, logger="book_scraper.dashboard.routes.api"):
            api._spawn_scrapy_in_container(phase="scan", shop="vaga")
    msgs = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any("source_run_id=-" in m for m in msgs)
