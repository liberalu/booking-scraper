from book_scraper.dashboard.queries import (
    get_run_issue_summary,
    get_validation_by_type,
)
from book_scraper.db.models import Listing, ScrapeRun, Shop
from book_scraper.db.repo import bulk_insert_validation_issues


def _setup(db_session):
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    listing = Listing(shop_id=shop.id, url="https://vaga.lt/b", title="B")
    db_session.add(listing)
    db_session.flush()
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run)
    db_session.flush()
    return shop, listing, run


def _insert(db_session, run_id, field, issue, listing_id):
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


def test_issue_summary_groups_and_sorts_desc(db_session):
    _shop, listing, run = _setup(db_session)

    # 3 x (title, too_short), 2 x (isbn, invalid), 1 x (price, missing)
    for _ in range(3):
        _insert(db_session, run.id, "title", "too_short", listing.id)
    for _ in range(2):
        _insert(db_session, run.id, "isbn", "invalid", listing.id)
    _insert(db_session, run.id, "price", "missing", listing.id)
    db_session.flush()

    rows = get_run_issue_summary(db_session, run.id)
    assert rows == [
        {"field": "title", "issue": "too_short", "count": 3},
        {"field": "isbn", "issue": "invalid", "count": 2},
        {"field": "price", "issue": "missing", "count": 1},
    ]


def test_issue_summary_empty_for_unknown_run(db_session):
    assert get_run_issue_summary(db_session, 9999) == []


def test_validation_by_type_filters_by_run_id(db_session):
    shop, listing, run_a = _setup(db_session)
    run_b = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run_b)
    db_session.flush()

    _insert(db_session, run_a.id, "title", "too_short", listing.id)
    _insert(db_session, run_a.id, "title", "too_short", listing.id)
    _insert(db_session, run_b.id, "title", "too_short", listing.id)
    db_session.flush()

    all_issues = get_validation_by_type(db_session, "too_short", state=None)
    run_a_issues = get_validation_by_type(
        db_session, "too_short", state=None, run_id=run_a.id
    )
    run_b_issues = get_validation_by_type(
        db_session, "too_short", state=None, run_id=run_b.id
    )

    assert len(all_issues) == 3
    assert len(run_a_issues) == 2
    assert len(run_b_issues) == 1
    assert all(i["scrape_run_id"] == run_a.id for i in run_a_issues)
