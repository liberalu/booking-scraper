from book_scraper.dashboard.queries import get_run_close_reason
from book_scraper.db.models import ScrapeRun, Shop
from book_scraper.db.repo import record_scrape_run_failed_issue


def _shop(db_session) -> Shop:
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    return shop


def _run(db_session, *, status: str, error_count: int = 0) -> ScrapeRun:
    shop = _shop(db_session)
    run = ScrapeRun(
        shop_id=shop.id, phase="scan", status=status, error_count=error_count
    )
    db_session.add(run)
    db_session.flush()
    return run


def test_completed_clean_run_returns_completed_ok(db_session):
    run = _run(db_session, status="completed", error_count=0)
    assert get_run_close_reason(db_session, run) == "completed_ok"


def test_completed_run_with_errors_returns_completed_with_errors(db_session):
    run = _run(db_session, status="completed", error_count=4)
    assert get_run_close_reason(db_session, run) == "completed_with_errors"


def test_failed_run_returns_reason_from_validation_issue(db_session):
    run = _run(db_session, status="failed")
    record_scrape_run_failed_issue(db_session, run, "heartbeat_timeout")
    db_session.flush()
    assert get_run_close_reason(db_session, run) == "heartbeat_timeout"


def test_failed_run_without_issue_row_falls_back_to_failed(db_session):
    run = _run(db_session, status="failed")
    assert get_run_close_reason(db_session, run) == "failed"


def test_running_run_returns_none(db_session):
    run = _run(db_session, status="running")
    assert get_run_close_reason(db_session, run) is None


def test_paused_run_returns_none(db_session):
    run = _run(db_session, status="paused")
    assert get_run_close_reason(db_session, run) is None


def test_stopping_run_returns_none(db_session):
    run = _run(db_session, status="stopping")
    assert get_run_close_reason(db_session, run) is None
