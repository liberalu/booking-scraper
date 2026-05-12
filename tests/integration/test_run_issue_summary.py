from book_scraper.dashboard.queries import (
    get_run_issue_summary,
    get_validation_by_type,
)
from book_scraper.db.models import ScrapeRun, Shop, ShopBook
from book_scraper.db.repo import upsert_validation_issues


def _setup(db_session):
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    shop_book = ShopBook(shop_id=shop.id, url="https://vaga.lt/b", title="B")
    db_session.add(shop_book)
    db_session.flush()
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run)
    db_session.flush()
    return shop, shop_book, run


def _insert(db_session, shop_id, run_id, field, issue, shop_book_id):
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


def test_issue_summary_groups_and_sorts_desc(db_session):
    shop, shop_book, run = _setup(db_session)

    # Each distinct (entity, field, issue) is one canonical row with upsert.
    _insert(db_session, shop.id, run.id, "title", "too_short", shop_book.id)
    _insert(db_session, shop.id, run.id, "isbn", "invalid", shop_book.id)
    _insert(db_session, shop.id, run.id, "price", "missing", shop_book.id)
    db_session.flush()

    rows = get_run_issue_summary(db_session, run.id)
    assert rows == [
        {"field": "isbn", "issue": "invalid", "count": 1},
        {"field": "price", "issue": "missing", "count": 1},
        {"field": "title", "issue": "too_short", "count": 1},
    ]


def test_issue_summary_empty_for_unknown_run(db_session):
    assert get_run_issue_summary(db_session, 9999) == []


def test_validation_by_type_filters_by_run_id(db_session):
    shop, shop_book, run_a = _setup(db_session)
    run_b = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run_b)
    db_session.flush()

    # With upsert semantics: same entity×field×issue is one canonical row.
    # Insert for run_a; then upsert again for run_b updates last_seen_run_id.
    _insert(db_session, shop.id, run_a.id, "title", "too_short", shop_book.id)
    _insert(db_session, shop.id, run_b.id, "title", "too_short", shop_book.id)
    db_session.flush()

    all_issues = get_validation_by_type(db_session, "too_short", state=None)
    run_b_issues = get_validation_by_type(
        db_session, "too_short", state=None, run_id=run_b.id
    )

    assert len(all_issues) == 1
    assert len(run_b_issues) == 1
