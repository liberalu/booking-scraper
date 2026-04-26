"""Unit tests for the JSONL per-response event log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from book_scraper import event_log


@pytest.fixture
def log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "scrapy_events.log"
    monkeypatch.setattr(event_log, "_log_path", None)
    monkeypatch.setattr(event_log, "_DEFAULT_LOG_PATH", path)
    return path


def test_log_response_event_writes_one_line(log_path: Path) -> None:
    event_log.log_response_event(
        run_id=42,
        url="https://example.com/a",
        status=200,
        duration_ms=312,
        request_delay_s=2.4,
        delay_source="httpx_observed",
        retry_count=0,
        in_flight=1,
        bytes_=18432,
    )

    contents = log_path.read_text()
    lines = [line for line in contents.splitlines() if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["run_id"] == 42
    assert record["url"] == "https://example.com/a"
    assert record["status"] == 200
    assert record["duration_ms"] == 312
    assert record["request_delay_s"] == 2.4
    assert record["delay_source"] == "httpx_observed"
    assert record["retry_count"] == 0
    assert record["in_flight"] == 1
    assert record["bytes"] == 18432
    assert "ts" in record
    assert "error_reason" not in record


def test_log_response_event_includes_error_reason_when_set(log_path: Path) -> None:
    event_log.log_response_event(
        run_id=1,
        url="https://example.com/b",
        status=503,
        duration_ms=900,
        request_delay_s=None,
        delay_source=None,
        retry_count=0,
        in_flight=0,
        bytes_=None,
        error_reason="http_503",
    )

    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["error_reason"] == "http_503"
    assert record["status"] == 503
    assert record["bytes"] is None


def test_log_response_event_appends_lines(log_path: Path) -> None:
    for i in range(3):
        event_log.log_response_event(
            run_id=7,
            url=f"https://example.com/{i}",
            status=200,
            duration_ms=100,
            request_delay_s=None,
            delay_source="httpx_observed",
            retry_count=0,
            in_flight=1,
            bytes_=500,
        )

    lines = [line for line in log_path.read_text().splitlines() if line]
    assert len(lines) == 3
    urls = [json.loads(line)["url"] for line in lines]
    assert urls == [
        "https://example.com/0",
        "https://example.com/1",
        "https://example.com/2",
    ]
