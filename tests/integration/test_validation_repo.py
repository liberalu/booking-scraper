from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from book_scraper.db.models import ScrapeRun, Shop, ValidationIssue
from book_scraper.db.repo import (
    acknowledge_validation_issues_bulk,
    delete_validation_issues_matching,
)


def _make_two_issues(db_session: Session) -> tuple[int, int, int]:
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    run = ScrapeRun(
        shop_id=shop.id,
        phase="scan",
        status="completed",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            ValidationIssue(
                scrape_run_id=run.id,
                url="https://vaga.lt/a",
                field="title",
                issue="suspicious_title",
                lifecycle_state="new",
            ),
            ValidationIssue(
                scrape_run_id=run.id,
                url="https://vaga.lt/b",
                field="price",
                issue="missing_price",
                lifecycle_state="new",
            ),
        ]
    )
    db_session.flush()
    return shop.id, run.id, db_session.query(ValidationIssue).count()


@pytest.mark.integration
def test_ack_bulk_respects_issue_type_filter(db_session: Session) -> None:
    _make_two_issues(db_session)
    updated = acknowledge_validation_issues_bulk(db_session, issue_type="missing_price")
    assert updated == 1
    remaining_open = (
        db_session.query(ValidationIssue)
        .filter(ValidationIssue.lifecycle_state != "already_seen")
        .count()
    )
    assert remaining_open == 1


@pytest.mark.integration
def test_ack_bulk_respects_run_id_filter(db_session: Session) -> None:
    _, run_id, _ = _make_two_issues(db_session)
    updated = acknowledge_validation_issues_bulk(db_session, run_id=run_id)
    assert updated == 2


@pytest.mark.integration
def test_delete_matching_hard_deletes(db_session: Session) -> None:
    _, _, total = _make_two_issues(db_session)
    assert total == 2
    deleted = delete_validation_issues_matching(db_session, issue_type="missing_price")
    assert deleted == 1
    remaining = db_session.query(ValidationIssue).count()
    assert remaining == 1


@pytest.mark.integration
def test_delete_matching_requires_at_least_one_filter(db_session: Session) -> None:
    _make_two_issues(db_session)
    with pytest.raises(ValueError):
        delete_validation_issues_matching(db_session)


@pytest.mark.integration
def test_ack_bulk_filters_by_search_query(db_session: Session) -> None:
    """`q=` exercises the outerjoin(ShopBook) + ILIKE branch in ack."""
    from book_scraper.db.models import ShopBook

    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    run = ScrapeRun(
        shop_id=shop.id,
        phase="scan",
        status="completed",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.flush()
    book = ShopBook(shop_id=shop.id, url="https://vaga.lt/x", title="Target Book")
    db_session.add(book)
    db_session.flush()
    db_session.add_all(
        [
            ValidationIssue(
                scrape_run_id=run.id,
                url="https://vaga.lt/x",
                field="title",
                issue="suspicious_title",
                shop_book_id=book.id,
                lifecycle_state="new",
            ),
            ValidationIssue(
                scrape_run_id=run.id,
                url="https://vaga.lt/y",
                field="price",
                issue="missing_price",
                lifecycle_state="new",
            ),
        ]
    )
    db_session.flush()
    # Match by title — should hit the book row only
    updated = acknowledge_validation_issues_bulk(db_session, q="Target Book")
    assert updated == 1
    # Match by URL substring — should hit the unresolved row
    updated = acknowledge_validation_issues_bulk(db_session, q="vaga.lt/y")
    assert updated == 1


@pytest.mark.integration
def test_delete_matching_supports_state_open(db_session: Session) -> None:
    """state='open' on delete excludes already_seen rows."""
    shop_id, run_id, _ = _make_two_issues(db_session)
    # Acknowledge one row so it becomes already_seen
    first = db_session.query(ValidationIssue).first()
    assert first is not None
    first.lifecycle_state = "already_seen"
    first.acknowledged_at = datetime.now(UTC)
    db_session.flush()
    # Delete with state='open' should hit only the remaining open row
    deleted = delete_validation_issues_matching(db_session, state="open")
    assert deleted == 1
    remaining = db_session.query(ValidationIssue).count()
    assert remaining == 1  # the acknowledged one
