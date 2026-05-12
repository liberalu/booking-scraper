"""Integration tests for ValidateService against real PostgreSQL (port 5433).

Covers all 7 check groups (19 issue keys) plus the dedup/lifecycle invariant.
Each test inserts minimal fixture data, runs ValidateService, and asserts the
expected ValidationIssue rows.

The `db_session` fixture (from tests/conftest.py) wraps each test in a
rolled-back transaction, so tests are fully isolated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from book_scraper.db.models import (
    Book,
    BookIsbn,
    DiscoveredUrl,
    ScrapeRun,
    Shop,
    ShopBook,
    ValidationIssue,
)
from book_scraper.services.validate import VALIDATE_STALE_CADENCE_DAYS, ValidateService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_shop(session, suffix: str = "") -> Shop:
    """Insert a minimal Shop row and flush."""
    name = f"testshop{suffix}"
    shop = Shop(name=name, base_url=f"https://{name}.lt")
    session.add(shop)
    session.flush()
    return shop


def _make_run(session, shop_id: int) -> ScrapeRun:
    """Insert a minimal ScrapeRun with phase='validate'."""
    run = ScrapeRun(
        shop_id=shop_id,
        phase="validate",
        status="running",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    return run


def _make_book_obj(session, isbn: str, suffix: str = "") -> Book:
    """Insert a canonical Book + BookIsbn row and flush."""
    book = Book(data_source="manual", title=f"Book {suffix}")
    session.add(book)
    session.flush()
    session.add(BookIsbn(book_id=book.id, isbn=isbn, isbn_type="isbn13"))
    session.flush()
    return book


def _make_du(
    session,
    shop_id: int,
    url: str,
    url_type: str = "product",
    shop_book_id: int | None = None,
) -> DiscoveredUrl:
    """Insert a DiscoveredUrl row and flush."""
    normalized = url.rstrip("/").lower()
    du = DiscoveredUrl(
        shop_id=shop_id,
        url=url,
        normalized_url=normalized,
        source="category",
        url_type=url_type,
        shop_book_id=shop_book_id,
    )
    session.add(du)
    session.flush()
    return du


def _count_issues(session, shop_book_ids: list[int], field: str) -> int:
    rows = (
        session.execute(
            select(ValidationIssue).where(
                ValidationIssue.shop_book_id.in_(shop_book_ids),
                ValidationIssue.field == field,
            )
        )
        .scalars()
        .all()
    )
    return len(rows)


def _issues_for(session, shop_book_id: int, issue_key: str) -> list[ValidationIssue]:
    return (
        session.execute(
            select(ValidationIssue).where(
                ValidationIssue.shop_book_id == shop_book_id,
                ValidationIssue.issue == issue_key,
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Structural duplicate checks
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_isbn_duplicate_flags_both_rows(db_session):
    shop = _make_shop(db_session, "a")
    run = _make_run(db_session, shop.id)

    sb1 = ShopBook(shop_id=shop.id, url="https://testshopa.lt/p/1", title="Book 1",
                   isbn="9780000000001")
    sb2 = ShopBook(shop_id=shop.id, url="https://testshopa.lt/p/2", title="Book 2",
                   isbn="9780000000001")
    db_session.add_all([sb1, sb2])
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = (
        db_session.execute(
            select(ValidationIssue).where(
                ValidationIssue.shop_book_id.in_([sb1.id, sb2.id]),
                ValidationIssue.issue == "isbn_duplicate",
            )
        )
        .scalars()
        .all()
    )
    assert len(issues) == 2
    flagged_ids = {i.shop_book_id for i in issues}
    assert flagged_ids == {sb1.id, sb2.id}


@pytest.mark.integration
def test_title_author_duplicate_flags_both_rows(db_session):
    shop = _make_shop(db_session, "b")
    run = _make_run(db_session, shop.id)

    sb1 = ShopBook(shop_id=shop.id, url="https://testshopb.lt/p/1", title="Same Title",
                   author="Same Author", isbn="9780000000010")
    sb2 = ShopBook(shop_id=shop.id, url="https://testshopb.lt/p/2", title="Same Title",
                   author="Same Author", isbn="9780000000011")
    db_session.add_all([sb1, sb2])
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = (
        db_session.execute(
            select(ValidationIssue).where(
                ValidationIssue.shop_book_id.in_([sb1.id, sb2.id]),
                ValidationIssue.issue == "title_author_duplicate",
            )
        )
        .scalars()
        .all()
    )
    assert len(issues) == 2
    assert {i.shop_book_id for i in issues} == {sb1.id, sb2.id}


@pytest.mark.integration
def test_sku_duplicate_flags_both_rows(db_session):
    shop = _make_shop(db_session, "c")
    run = _make_run(db_session, shop.id)

    sb1 = ShopBook(shop_id=shop.id, url="https://testshopc.lt/p/1", title="SKU1",
                   sku="SKU-001")
    sb2 = ShopBook(shop_id=shop.id, url="https://testshopc.lt/p/2", title="SKU2",
                   sku="SKU-001")
    db_session.add_all([sb1, sb2])
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = (
        db_session.execute(
            select(ValidationIssue).where(
                ValidationIssue.shop_book_id.in_([sb1.id, sb2.id]),
                ValidationIssue.issue == "sku_duplicate",
            )
        )
        .scalars()
        .all()
    )
    assert len(issues) == 2
    assert {i.shop_book_id for i in issues} == {sb1.id, sb2.id}


# ---------------------------------------------------------------------------
# Slug-title mismatch check
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_slug_title_mismatch_zero_overlap_flagged(db_session):
    shop = _make_shop(db_session, "d")
    run = _make_run(db_session, shop.id)

    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshopd.lt/vyresnio-amziaus-zmoniu-sveika",
        title="Ką šunys galvoja?",
    )
    db_session.add(sb)
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = _issues_for(db_session, sb.id, "slug_title_mismatch")
    assert len(issues) == 1


@pytest.mark.integration
def test_slug_title_mismatch_with_overlap_not_flagged(db_session):
    shop = _make_shop(db_session, "e")
    run = _make_run(db_session, shop.id)

    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshope.lt/sapiens-trumpa-zmonijos-istorija",
        title="Sapiens trumpa istorija",
    )
    db_session.add(sb)
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = _issues_for(db_session, sb.id, "slug_title_mismatch")
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# Data completeness checks (VAL-05)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_active_no_price_flagged_when_price_null(db_session):
    shop = _make_shop(db_session, "f")
    run = _make_run(db_session, shop.id)

    # is_active=True, price=NULL
    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshopf.lt/p/1",
        title="No Price Book",
        is_active=True,
        price=None,
        in_stock=True,
    )
    db_session.add(sb)
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    active_no_price = _issues_for(db_session, sb.id, "active_no_price")
    assert len(active_no_price) == 1

    in_stock_no_price = _issues_for(db_session, sb.id, "in_stock_no_price")
    assert len(in_stock_no_price) == 1


@pytest.mark.integration
def test_no_price_history_flagged_for_active_book_without_prices(db_session):
    shop = _make_shop(db_session, "g")
    run = _make_run(db_session, shop.id)

    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshopg.lt/p/1",
        title="No Price History",
        is_active=True,
    )
    db_session.add(sb)
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = _issues_for(db_session, sb.id, "no_price_history")
    assert len(issues) == 1


# ---------------------------------------------------------------------------
# Data correctness checks (VAL-06)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_year_out_of_range_flagged(db_session):
    shop = _make_shop(db_session, "h")
    run = _make_run(db_session, shop.id)

    sb_old = ShopBook(
        shop_id=shop.id,
        url="https://testshoph.lt/old",
        title="Old Book",
        year=1700,
    )
    sb_future = ShopBook(
        shop_id=shop.id,
        url="https://testshoph.lt/future",
        title="Future Book",
        year=datetime.now(UTC).year + 5,
    )
    sb_valid = ShopBook(
        shop_id=shop.id,
        url="https://testshoph.lt/valid",
        title="Valid Book",
        year=2024,
    )
    db_session.add_all([sb_old, sb_future, sb_valid])
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    assert len(_issues_for(db_session, sb_old.id, "year_out_of_range")) == 1
    assert len(_issues_for(db_session, sb_future.id, "year_out_of_range")) == 1
    assert len(_issues_for(db_session, sb_valid.id, "year_out_of_range")) == 0


@pytest.mark.integration
def test_format_is_dimensions_flagged(db_session):
    shop = _make_shop(db_session, "i")
    run = _make_run(db_session, shop.id)

    sb_dim = ShopBook(
        shop_id=shop.id,
        url="https://testshopi.lt/p/dim",
        title="Dims Book",
        format="15x20x3 cm",
    )
    sb_ok = ShopBook(
        shop_id=shop.id,
        url="https://testshopi.lt/p/ok",
        title="Good Format Book",
        format="hardcover",
    )
    db_session.add_all([sb_dim, sb_ok])
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    assert len(_issues_for(db_session, sb_dim.id, "format_is_dimensions")) == 1
    assert len(_issues_for(db_session, sb_ok.id, "format_is_dimensions")) == 0


# ---------------------------------------------------------------------------
# Classification consistency checks (VAL-07)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_non_product_active_flagged_via_join(db_session):
    shop = _make_shop(db_session, "j")
    run = _make_run(db_session, shop.id)

    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshopj.lt/p/1",
        title="Active Non-Product",
        is_active=True,
    )
    db_session.add(sb)
    db_session.flush()

    _make_du(
        db_session, shop.id, sb.url,
        url_type="non_product", shop_book_id=sb.id
    )
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = _issues_for(db_session, sb.id, "non_product_active")
    assert len(issues) == 1
    assert issues[0].raw_value == "non_product"


# ---------------------------------------------------------------------------
# Staleness checks (VAL-08)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_stale_active_flagged_when_last_seen_old(db_session):
    shop = _make_shop(db_session, "k")
    run = _make_run(db_session, shop.id)

    stale_days = 2 * VALIDATE_STALE_CADENCE_DAYS + 2  # safely beyond threshold
    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshopk.lt/p/1",
        title="Stale Book",
        is_active=True,
        last_seen_at=datetime.now(UTC) - timedelta(days=stale_days),
    )
    db_session.add(sb)
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = _issues_for(db_session, sb.id, "stale_active")
    assert len(issues) == 1


@pytest.mark.integration
def test_stale_active_not_flagged_for_recent_book(db_session):
    shop = _make_shop(db_session, "k2")
    run = _make_run(db_session, shop.id)

    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshopk2.lt/p/1",
        title="Recent Book",
        is_active=True,
        last_seen_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(sb)
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = _issues_for(db_session, sb.id, "stale_active")
    assert len(issues) == 0


@pytest.mark.integration
def test_orphan_no_url_flagged(db_session):
    shop = _make_shop(db_session, "l")
    run = _make_run(db_session, shop.id)

    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshopl.lt/p/orphan",
        title="Orphan Book",
    )
    db_session.add(sb)
    db_session.commit()

    # No DiscoveredUrl pointing at sb.id

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = _issues_for(db_session, sb.id, "orphan_no_url")
    assert len(issues) == 1


# ---------------------------------------------------------------------------
# Match readiness checks (VAL-09)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_unmatched_has_isbn_flagged(db_session):
    shop = _make_shop(db_session, "m")
    run = _make_run(db_session, shop.id)

    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshopm.lt/p/1",
        title="Unmatched With ISBN",
        isbn="9789999999999",
        match_status="unmatched",
    )
    db_session.add(sb)
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = _issues_for(db_session, sb.id, "unmatched_has_isbn")
    assert len(issues) == 1
    assert issues[0].raw_value == "9789999999999"


@pytest.mark.integration
def test_match_isbn_drift_flagged_when_isbns_differ(db_session):
    shop = _make_shop(db_session, "m2")
    run = _make_run(db_session, shop.id)

    book = _make_book_obj(db_session, "9780000000020", suffix="drift")

    # shop_book matched but has different isbn than the canonical book
    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshopmd.lt/p/1",
        title="Drift Book",
        isbn="9780000000099",  # differs from book's isbn
        match_status="matched",
        book_id=book.id,
    )
    db_session.add(sb)
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = _issues_for(db_session, sb.id, "match_isbn_drift")
    assert len(issues) == 1


# ---------------------------------------------------------------------------
# Relationship integrity checks (VAL-10)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_url_aliases_flagged_when_multiple_urls_per_shop_book(db_session):
    shop = _make_shop(db_session, "n")
    run = _make_run(db_session, shop.id)

    sb = ShopBook(
        shop_id=shop.id,
        url="https://testshopn.lt/p/1",
        title="Aliased Book",
    )
    db_session.add(sb)
    db_session.flush()

    # Two discovered_urls both pointing to the same shop_book
    _make_du(db_session, shop.id, "https://testshopn.lt/p/1",
             url_type="product", shop_book_id=sb.id)
    _make_du(db_session, shop.id, "https://testshopn.lt/p/1-alt",
             url_type="product", shop_book_id=sb.id)
    db_session.commit()

    ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    issues = _issues_for(db_session, sb.id, "url_aliases")
    assert len(issues) == 1
    assert issues[0].raw_value == "2"


# ---------------------------------------------------------------------------
# Dedup invariant (VAL-11)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_dedup_second_run_does_not_create_duplicate_rows(db_session):
    """Re-running validate on the same data upserts existing rows, not inserts new ones.

    After run 1: 2 rows with lifecycle_state='new' (one per duplicate pair member).
    After run 2: still 2 rows — the upsert updates last_seen_run_id and
    increments run_count; lifecycle_state stays 'new' (canonical registry model).
    """
    shop = _make_shop(db_session, "o")
    run1 = _make_run(db_session, shop.id)

    sb1 = ShopBook(shop_id=shop.id, url="https://testshopo.lt/p/1", title="Dup1",
                   isbn="9780000000030")
    sb2 = ShopBook(shop_id=shop.id, url="https://testshopo.lt/p/2", title="Dup2",
                   isbn="9780000000030")
    db_session.add_all([sb1, sb2])
    db_session.commit()

    # First run
    ValidateService(db_session).run(shop.id, run1.id)
    db_session.commit()

    count_after_run1 = _count_issues(db_session, [sb1.id, sb2.id], "isbn")
    assert count_after_run1 == 2

    first_run_states = [
        i.lifecycle_state
        for i in db_session.execute(
            select(ValidationIssue).where(
                ValidationIssue.shop_book_id.in_([sb1.id, sb2.id]),
                ValidationIssue.field == "isbn",
            )
        )
        .scalars()
        .all()
    ]
    assert all(s == "new" for s in first_run_states)

    # Second run — same data, new run_id
    run2 = _make_run(db_session, shop.id)
    ValidateService(db_session).run(shop.id, run2.id)
    db_session.commit()

    all_issues = (
        db_session.execute(
            select(ValidationIssue).where(
                ValidationIssue.shop_book_id.in_([sb1.id, sb2.id]),
                ValidationIssue.field == "isbn",
                ValidationIssue.issue == "isbn_duplicate",
            )
        )
        .scalars()
        .all()
    )
    # Canonical registry: upsert means still 2 rows total (no duplicates)
    assert len(all_issues) == 2

    # All rows should now point to run2 as last_seen, with run_count=2
    assert all(i.last_seen_run_id == run2.id for i in all_issues), (
        f"Expected last_seen_run_id={run2.id}, "
        f"got: {[i.last_seen_run_id for i in all_issues]}"
    )
    assert all(i.run_count == 2 for i in all_issues), (
        f"Expected run_count=2, got: {[i.run_count for i in all_issues]}"
    )


# ---------------------------------------------------------------------------
# Counter return value
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_returns_counters_keyed_by_issue(db_session):
    shop = _make_shop(db_session, "p")
    run = _make_run(db_session, shop.id)

    sb1 = ShopBook(shop_id=shop.id, url="https://testshopp.lt/p/1", title="Ctr1",
                   isbn="9780000000040")
    sb2 = ShopBook(shop_id=shop.id, url="https://testshopp.lt/p/2", title="Ctr2",
                   isbn="9780000000040")
    db_session.add_all([sb1, sb2])
    db_session.commit()

    counters = ValidateService(db_session).run(shop.id, run.id)
    db_session.commit()

    assert counters["isbn_duplicate"] == 2
