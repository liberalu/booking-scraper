from fastapi.testclient import TestClient

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db
from book_scraper.db.models import Listing, ScrapeRun, Shop, ValidationIssue
from book_scraper.db.repo import (
    acknowledge_validation_issue,
    bulk_insert_validation_issues,
)


def _setup(db_session):
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    listing = Listing(shop_id=shop.id, url="https://vaga.lt/b", title="B")
    db_session.add(listing)
    db_session.flush()
    return shop, listing


def _insert_issue(db_session, run_id, listing_id, field="price", issue="missing_price"):
    bulk_insert_validation_issues(
        db_session,
        [
            {
                "scrape_run_id": run_id,
                "url": "https://vaga.lt/b",
                "field": field,
                "issue": issue,
                "raw_value": None,
                "listing_id": listing_id,
            }
        ],
    )
    db_session.flush()


def test_first_occurrence_is_new(db_session):
    shop, listing = _setup(db_session)
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run)
    db_session.flush()

    _insert_issue(db_session, run.id, listing.id)
    issue = db_session.query(ValidationIssue).one()
    assert issue.lifecycle_state == "new"


def test_second_occurrence_is_recurring(db_session):
    shop, listing = _setup(db_session)
    run1 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run1)
    db_session.flush()
    _insert_issue(db_session, run1.id, listing.id)

    run2 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run2)
    db_session.flush()
    _insert_issue(db_session, run2.id, listing.id)

    states = [
        i.lifecycle_state
        for i in db_session.query(ValidationIssue)
        .order_by(ValidationIssue.id)
        .all()
    ]
    assert states == ["new", "recurring"]


def test_acknowledged_reappears_as_new(db_session):
    """Acknowledging a recurring issue and then seeing it again on the
    next run should resurface it as `new` — the point of the ack is
    to mute it until its reality changes."""
    shop, listing = _setup(db_session)
    run1 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run1)
    db_session.flush()
    _insert_issue(db_session, run1.id, listing.id)

    issue = db_session.query(ValidationIssue).one()
    assert acknowledge_validation_issue(db_session, issue.id)
    db_session.refresh(issue)
    assert issue.lifecycle_state == "already_seen"
    assert issue.acknowledged_at is not None

    run2 = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run2)
    db_session.flush()
    _insert_issue(db_session, run2.id, listing.id)

    newest = (
        db_session.query(ValidationIssue)
        .order_by(ValidationIssue.id.desc())
        .first()
    )
    assert newest.lifecycle_state == "new"


def test_acknowledge_endpoint(db_session):
    shop, listing = _setup(db_session)
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run)
    db_session.flush()
    _insert_issue(db_session, run.id, listing.id)
    issue = db_session.query(ValidationIssue).one()

    # Bind the app to the same transactional session.
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            resp = client.post(
                f"/validation-issues/{issue.id}/acknowledge",
                follow_redirects=False,
            )
            assert resp.status_code == 303

        db_session.refresh(issue)
        assert issue.lifecycle_state == "already_seen"
        assert issue.acknowledged_at is not None
    finally:
        app.dependency_overrides.pop(get_db, None)
