"""Paginated lists must order by a unique column last.

Every list below sorts on a non-unique column. Without an id tiebreaker
Postgres may return ties in any order per query, so the same row can land on
two pages while another never appears — measured in production as 13 books on
both page 1 and 2, and 227 duplicate rows in a ~6,300-row CSV export (which
pages through `list_books`).

These assert the emitted SQL, not the row order: a small table happens to come
back in insertion order, so a behavioural test passes with or without the fix
and guards nothing.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from book_scraper.dashboard.queries import (
    get_discovered_urls_page,
    get_run_books_added,
    get_run_books_updated,
    get_run_discovered_urls,
    get_shop_books_page,
    list_books,
)


@contextmanager
def order_by_clauses(session: Session) -> Iterator[list[str]]:
    """Collect the ORDER BY of every paginated SELECT run inside the block."""
    clauses: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        sql = " ".join(statement.lower().split())
        if " order by " in sql and (" offset " in sql or " limit " in sql):
            clauses.append(sql.split(" order by ", 1)[1])

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", capture)
    try:
        yield clauses
    finally:
        event.remove(bind, "before_cursor_execute", capture)


def assert_tiebroken_on(clauses: list[str], column: str) -> None:
    assert clauses, "no paginated SELECT was captured"
    for clause in clauses:
        assert column in clause, f"ORDER BY {clause!r} has no {column} tiebreaker"


@pytest.mark.parametrize("sort_order", ["asc", "desc"])
def test_shop_books_page_ties_on_id(db_session: Session, sort_order: str):
    with order_by_clauses(db_session) as clauses:
        get_shop_books_page(db_session, page=2, per_page=10, sort_order=sort_order)
    assert_tiebroken_on(clauses, "shop_books.id")


@pytest.mark.parametrize("sort_order", ["asc", "desc"])
def test_discovered_urls_page_ties_on_id(db_session: Session, sort_order: str):
    with order_by_clauses(db_session) as clauses:
        get_discovered_urls_page(db_session, page=2, per_page=10, sort_order=sort_order)
    assert_tiebroken_on(clauses, "discovered_urls.id")


def test_list_books_ties_on_id(db_session: Session):
    with order_by_clauses(db_session) as clauses:
        list_books(db_session, page=2, per_page=10)
    assert_tiebroken_on(clauses, "books.id")


def test_run_books_added_ties_on_id(db_session: Session):
    from book_scraper.db.models import ScrapeRun, Shop

    shop = Shop(name="tie-run", base_url="https://tierun.example")
    db_session.add(shop)
    db_session.flush()
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="completed")
    db_session.add(run)
    db_session.commit()

    with order_by_clauses(db_session) as clauses:
        get_run_books_added(db_session, run.id, page=2, per_page=10)
    assert_tiebroken_on(clauses, "shop_books.id")

    with order_by_clauses(db_session) as clauses:
        get_run_books_updated(db_session, run.id, page=2, per_page=10)
    assert_tiebroken_on(clauses, "shop_books.id")


def test_run_discovered_urls_ties_on_id(db_session: Session):
    from book_scraper.db.models import ScrapeRun, Shop

    shop = Shop(name="tie-disc", base_url="https://tiedisc.example")
    db_session.add(shop)
    db_session.flush()
    run = ScrapeRun(shop_id=shop.id, phase="discover_sitemap", status="completed")
    db_session.add(run)
    db_session.commit()

    with order_by_clauses(db_session) as clauses:
        get_run_discovered_urls(db_session, run.id, page=2, per_page=10)
    assert_tiebroken_on(clauses, "discovered_urls.id")
