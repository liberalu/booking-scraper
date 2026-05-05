from book_scraper.db.models import ScrapeRun, Shop, ShopBook, ValidationIssue
from book_scraper.db.repo import (
    acknowledge_validation_issue,
    bulk_insert_validation_issues,
)


def _setup(db_session):
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    shop_book = ShopBook(shop_id=shop.id, url="https://vaga.lt/b", title="B")
    db_session.add(shop_book)
    db_session.flush()
    return shop, shop_book


def _insert_issue(
    db_session, run_id, shop_book_id, field="price", issue="missing_price"
):
    bulk_insert_validation_issues(
        db_session,
        [
            {
                "scrape_run_id": run_id,
                "url": "https://vaga.lt/b",
                "field": field,
                "issue": issue,
                "raw_value": None,
                "shop_book_id": shop_book_id,
            }
        ],
    )
    db_session.flush()


def test_first_occurrence_is_new(db_session):
    shop, shop_book = _setup(db_session)
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run)
    db_session.flush()

    _insert_issue(db_session, run.id, shop_book.id)
    issue = db_session.query(ValidationIssue).one()
    assert issue.lifecycle_state == "new"


def test_second_occurrence_is_recurring(db_session):
    shop, shop_book = _setup(db_session)
    run1 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run1)
    db_session.flush()
    _insert_issue(db_session, run1.id, shop_book.id)

    run2 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run2)
    db_session.flush()
    _insert_issue(db_session, run2.id, shop_book.id)

    states = [
        i.lifecycle_state
        for i in db_session.query(ValidationIssue).order_by(ValidationIssue.id).all()
    ]
    assert states == ["new", "recurring"]


def test_acknowledged_reappears_as_new(db_session):
    """Acknowledging a recurring issue and then seeing it again on the
    next run should resurface it as `new` — the point of the ack is
    to mute it until its reality changes."""
    shop, shop_book = _setup(db_session)
    run1 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run1)
    db_session.flush()
    _insert_issue(db_session, run1.id, shop_book.id)

    issue = db_session.query(ValidationIssue).one()
    assert acknowledge_validation_issue(db_session, issue.id)
    db_session.refresh(issue)
    assert issue.lifecycle_state == "already_seen"
    assert issue.acknowledged_at is not None

    run2 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run2)
    db_session.flush()
    _insert_issue(db_session, run2.id, shop_book.id)

    newest = (
        db_session.query(ValidationIssue).order_by(ValidationIssue.id.desc()).first()
    )
    assert newest.lifecycle_state == "new"
