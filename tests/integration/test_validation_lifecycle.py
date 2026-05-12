from book_scraper.db.models import ScrapeRun, Shop, ShopBook, ValidationIssue
from book_scraper.db.repo import (
    acknowledge_validation_issue,
    upsert_validation_issues,
)


def _setup(db_session):
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    shop_book = ShopBook(shop_id=shop.id, url="https://vaga.lt/b", title="B")
    db_session.add(shop_book)
    db_session.flush()
    return shop, shop_book


def _upsert_issue(
    db_session, shop_id, run_id, shop_book_id, field="price", issue="missing_price"
):
    upsert_validation_issues(
        db_session,
        [
            {
                "url": "https://vaga.lt/b",
                "field": field,
                "issue": issue,
                "raw_value": None,
                "shop_book_id": shop_book_id,
            }
        ],
        shop_id=shop_id,
        run_id=run_id,
    )
    db_session.flush()


def test_first_occurrence_is_new(db_session):
    shop, shop_book = _setup(db_session)
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run)
    db_session.flush()

    _upsert_issue(db_session, shop.id, run.id, shop_book.id)
    issue = db_session.query(ValidationIssue).one()
    assert issue.lifecycle_state == "new"


def test_second_occurrence_increments_run_count(db_session):
    """Re-detection of the same issue increments run_count on the canonical row."""
    shop, shop_book = _setup(db_session)
    run1 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run1)
    db_session.flush()
    _upsert_issue(db_session, shop.id, run1.id, shop_book.id)

    run2 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run2)
    db_session.flush()
    _upsert_issue(db_session, shop.id, run2.id, shop_book.id)

    issues = db_session.query(ValidationIssue).all()
    assert len(issues) == 1, "upsert must keep exactly one canonical row"
    assert issues[0].run_count == 2
    assert issues[0].lifecycle_state == "new"


def test_acknowledged_stays_acknowledged_on_re_detection(db_session):
    """An acknowledged issue stays acknowledged when re-detected (run_count still
    increments) — operator mute is preserved across runs."""
    shop, shop_book = _setup(db_session)
    run1 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run1)
    db_session.flush()
    _upsert_issue(db_session, shop.id, run1.id, shop_book.id)

    issue = db_session.query(ValidationIssue).one()
    assert acknowledge_validation_issue(db_session, issue.id)
    db_session.refresh(issue)
    assert issue.lifecycle_state == "acknowledged"
    assert issue.acknowledged_at is not None

    run2 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run2)
    db_session.flush()
    _upsert_issue(db_session, shop.id, run2.id, shop_book.id)

    db_session.refresh(issue)
    assert issue.lifecycle_state == "acknowledged"
    assert issue.run_count == 2
