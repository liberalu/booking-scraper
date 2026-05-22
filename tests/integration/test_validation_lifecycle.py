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


def _upsert_issue_with_initial_state(
    db_session, shop_id, run_id, shop_book_id, initial_state: str
):
    upsert_validation_issues(
        db_session,
        [
            {
                "url": "https://vaga.lt/b",
                "field": "slug",
                "issue": "slug_diacritic_loss",
                "raw_value": "kale-du-pu-ga",
                "shop_book_id": shop_book_id,
                "initial_state": initial_state,
            }
        ],
        shop_id=shop_id,
        run_id=run_id,
    )
    db_session.flush()


def test_initial_state_acknowledged_on_first_detection(db_session):
    """Validators that set initial_state='acknowledged' produce an acknowledged
    issue on first detection — the issue never lands in the 'new' queue.

    This is the behaviour for slug_diacritic_loss: the bug lives in the
    shop's slug generator and we will never fix it ourselves, so surfacing
    it as 'new' only creates manual-ack churn.
    """
    shop, shop_book = _setup(db_session)
    run = ScrapeRun(shop_id=shop.id, phase="validate", status="running")
    db_session.add(run)
    db_session.flush()

    _upsert_issue_with_initial_state(db_session, shop.id, run.id, shop_book.id, "acknowledged")
    issue = db_session.query(ValidationIssue).one()
    assert issue.lifecycle_state == "acknowledged", (
        "initial_state='acknowledged' must produce an acknowledged issue, not 'new'"
    )


def test_resolved_issue_with_initial_state_acknowledged_reopens_as_acknowledged(db_session):
    """When a resolved issue is re-detected with initial_state='acknowledged',
    it should reopen as 'acknowledged', not 'new'.

    Without this, slug_diacritic_loss issues would cycle new→ack→resolved→new
    every time the operator clears them, defeating the whole point of
    initial_state='acknowledged'.
    """
    shop, shop_book = _setup(db_session)
    run1 = ScrapeRun(shop_id=shop.id, phase="validate", status="running")
    db_session.add(run1)
    db_session.flush()

    # First detection — acknowledged.
    _upsert_issue_with_initial_state(db_session, shop.id, run1.id, shop_book.id, "acknowledged")
    issue = db_session.query(ValidationIssue).one()
    assert issue.lifecycle_state == "acknowledged"

    # Simulate operator resolution (e.g. issue marked resolved externally).
    issue.lifecycle_state = "resolved"
    db_session.flush()

    # Re-detect — should come back as 'acknowledged', not 'new'.
    run2 = ScrapeRun(shop_id=shop.id, phase="validate", status="running")
    db_session.add(run2)
    db_session.flush()
    _upsert_issue_with_initial_state(db_session, shop.id, run2.id, shop_book.id, "acknowledged")

    db_session.refresh(issue)
    assert issue.lifecycle_state == "acknowledged", (
        "re-detected resolved issue with initial_state='acknowledged' must reopen "
        "as 'acknowledged', not 'new'"
    )
