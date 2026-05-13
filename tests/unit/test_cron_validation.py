"""Unit tests for the _validate_cron helper."""
import pytest
from fastapi import HTTPException

from book_scraper.dashboard.routes.api import _validate_cron


def test_valid_5field_passes():
    _validate_cron("0 2 * * *")
    _validate_cron("*/5 * * * *")
    _validate_cron("0 0 1 1 *")


def test_invalid_syntax_raises_422():
    with pytest.raises(HTTPException) as exc:
        _validate_cron("not a cron")
    assert exc.value.status_code == 422
    assert "Invalid cron expression" in exc.value.detail


def test_six_field_rejected():
    """6-field (with seconds) is rejected — we want strict 5-field."""
    with pytest.raises(HTTPException) as exc:
        _validate_cron("0 0 2 * * *")
    assert exc.value.status_code == 422


def test_seven_field_rejected():
    with pytest.raises(HTTPException) as exc:
        _validate_cron("0 0 2 * * * 2025")
    assert exc.value.status_code == 422


def test_extra_whitespace_normalized():
    """Leading/trailing whitespace and double spaces should still parse."""
    _validate_cron("  0 2 * * *  ")
    _validate_cron("0  2  *  *  *")


def test_empty_string_rejected():
    with pytest.raises(HTTPException) as exc:
        _validate_cron("")
    assert exc.value.status_code == 422
