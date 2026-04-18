# tests/unit/test_relative_time.py
from datetime import UTC, datetime, timedelta


def test_relative_time_just_now():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(seconds=30)
    assert _relative_time(dt) == "just now"


def test_relative_time_minutes():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(minutes=5)
    assert _relative_time(dt) == "5m ago"


def test_relative_time_hours():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(hours=3)
    assert _relative_time(dt) == "3h ago"


def test_relative_time_days():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(days=2)
    assert _relative_time(dt) == "2d ago"


def test_relative_time_weeks():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(weeks=3)
    assert _relative_time(dt) == "3w ago"


def test_relative_time_months():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(days=65)
    assert _relative_time(dt) == "2mo ago"


def test_relative_time_years():
    from book_scraper.dashboard.app import _relative_time
    dt = datetime.now(UTC) - timedelta(days=400)
    assert _relative_time(dt) == "1y ago"


def test_relative_time_none():
    from book_scraper.dashboard.app import _relative_time
    assert _relative_time(None) == "—"


def test_relative_time_naive_datetime():
    from book_scraper.dashboard.app import _relative_time
    # naive datetimes should not raise
    dt = datetime.utcnow() - timedelta(hours=1)
    result = _relative_time(dt)
    assert "h ago" in result
