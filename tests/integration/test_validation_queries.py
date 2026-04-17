from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from book_scraper.dashboard.queries import (
    get_issues_page,
    get_validation_lifecycle_counts,
)
from book_scraper.db.models import ScrapeRun, Shop, ShopBook, ValidationIssue


def _seed(db_session: Session) -> tuple[int, int]:
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    run = ScrapeRun(
        shop_id=shop.id,
        phase="scan",
        status="completed",
        started_at=datetime(2026, 4, 17, 15, 0, 0, tzinfo=UTC),
    )
    db_session.add(run)
    db_session.flush()
    book = ShopBook(
        shop_id=shop.id,
        url="https://vaga.lt/x",
        title="Test Book",
    )
    db_session.add(book)
    db_session.flush()
    db_session.add_all(
        [
            ValidationIssue(
                scrape_run_id=run.id,
                url="https://vaga.lt/x",
                field="title",
                issue="suspicious_title",
                raw_value="short",
                shop_book_id=book.id,
                lifecycle_state="new",
            ),
            ValidationIssue(
                scrape_run_id=run.id,
                url="https://vaga.lt/y",
                field="price",
                issue="missing_price",
                raw_value=None,
                shop_book_id=None,
                lifecycle_state="recurring",
            ),
        ]
    )
    db_session.flush()
    return shop.id, run.id


@pytest.mark.integration
def test_get_issues_page_returns_paginated_rows(db_session: Session) -> None:
    shop_id, run_id = _seed(db_session)
    rows, total = get_issues_page(
        db_session, state="open", page=1, per_page=50
    )
    assert total == 2
    assert len(rows) == 2
    # Newest-first by scrape_runs.started_at then by id
    assert rows[0]["issue"] in {"suspicious_title", "missing_price"}
    assert rows[0]["added_at"] is not None


@pytest.mark.integration
def test_get_issues_page_filters_by_shop(db_session: Session) -> None:
    shop_id, _ = _seed(db_session)
    rows, total = get_issues_page(
        db_session, state="open", shop_id=shop_id, page=1, per_page=50
    )
    assert total == 2


@pytest.mark.integration
def test_get_issues_page_filters_by_issue_type(db_session: Session) -> None:
    _seed(db_session)
    rows, total = get_issues_page(
        db_session,
        state="open",
        issue_type="missing_price",
        page=1,
        per_page=50,
    )
    assert total == 1
    assert rows[0]["issue"] == "missing_price"


@pytest.mark.integration
def test_get_issues_page_filters_by_run_id(db_session: Session) -> None:
    _, run_id = _seed(db_session)
    rows, total = get_issues_page(
        db_session, state="open", run_id=run_id, page=1, per_page=50
    )
    assert total == 2
    assert all(r["scrape_run_id"] == run_id for r in rows)


@pytest.mark.integration
def test_get_issues_page_search_matches_title_or_url(db_session: Session) -> None:
    _seed(db_session)
    # Match by book title
    rows, total = get_issues_page(
        db_session, state="open", q="Test Book", page=1, per_page=50
    )
    assert total == 1
    assert rows[0]["shop_book_title"] == "Test Book"
    # Match by URL substring for unresolved book
    rows, total = get_issues_page(
        db_session, state="open", q="vaga.lt/y", page=1, per_page=50
    )
    assert total == 1
    assert rows[0]["url"] == "https://vaga.lt/y"


@pytest.mark.integration
def test_get_issues_page_sort_order(db_session: Session) -> None:
    _seed(db_session)
    rows_desc, _ = get_issues_page(
        db_session, state="open", order="desc", page=1, per_page=50
    )
    rows_asc, _ = get_issues_page(
        db_session, state="open", order="asc", page=1, per_page=50
    )
    # Both return same set, but reversed
    assert [r["id"] for r in rows_desc] == list(reversed([r["id"] for r in rows_asc]))


@pytest.mark.integration
def test_lifecycle_counts_filters_by_issue_type_and_run(db_session: Session) -> None:
    _, run_id = _seed(db_session)
    counts = get_validation_lifecycle_counts(
        db_session,
        issue_type="missing_price",
        run_id=run_id,
    )
    assert counts["recurring"] == 1
    assert counts["new"] == 0
    assert counts["open"] == 1


@pytest.mark.integration
def test_lifecycle_counts_filters_by_search(db_session: Session) -> None:
    """`q=` exercises the outerjoin(ShopBook) + ILIKE branch."""
    _seed(db_session)
    # Match by book title (resolved shop_book)
    counts_title = get_validation_lifecycle_counts(db_session, q="Test Book")
    assert counts_title["new"] == 1
    assert counts_title["recurring"] == 0
    assert counts_title["open"] == 1
    # Match by URL substring (unresolved shop_book)
    counts_url = get_validation_lifecycle_counts(db_session, q="vaga.lt/y")
    assert counts_url["recurring"] == 1
    assert counts_url["new"] == 0
    assert counts_url["open"] == 1
