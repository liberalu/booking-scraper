from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from book_scraper.db.models import ScrapeRun, Shop, ShopBook, ValidationIssue
from book_scraper.db.repo import (
    acknowledge_validation_issue,
    bulk_acknowledge_issues,
    create_scrape_run,
    finalize_run_failsafe,
    finish_scrape_run,
    get_latest_completed_run,
    mark_orphan_runs_failed,
    mark_stale_runs_failed,
    resolve_gone_issues,
    update_scrape_run_progress,
    upsert_validation_issues,
)
from tests.conftest import TEST_DATABASE_URL


def test_create_scrape_run(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    run = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    assert run.status == "running"
    assert run.started_at is not None
    assert run.finished_at is None
    assert run.urls_processed == 0


def test_finish_scrape_run_completed(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    run = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    finish_scrape_run(db_session, run_id=run.id, status="completed", reason="finished")
    db_session.refresh(run)
    assert run.status == "completed"
    assert run.finished_at is not None
    assert run.close_reason == "finished"


def test_finish_scrape_run_failed_persists_close_reason(db_session):
    """Failed runs record their close reason on the row itself, not just
    in the parallel validation_issues entry."""
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    run = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    finish_scrape_run(
        db_session, run_id=run.id, status="failed", reason="stall_timeout"
    )
    db_session.refresh(run)
    assert run.status == "failed"
    assert run.close_reason == "stall_timeout"


def test_mark_stale_runs_failed(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    stale = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    db_session.flush()
    count = mark_stale_runs_failed(db_session, shop_id=shop.id, phase="scan")
    assert count == 1
    db_session.refresh(stale)
    assert stale.status == "failed"
    assert stale.finished_at is not None
    # Out-of-band close paths must also stamp close_reason on the row.
    assert stale.close_reason == "stale_pre_scan"


def test_mark_stale_runs_failed_custom_reason(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    stale = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    db_session.flush()
    mark_stale_runs_failed(
        db_session, shop_id=shop.id, phase="scan", reason="manual_cleanup"
    )
    db_session.refresh(stale)
    assert stale.close_reason == "manual_cleanup"


def test_finalize_run_failsafe_swallows_errors():
    """Failsafe must never raise — its job is to be the belt-and-suspenders
    finalize that runs even when everything else has gone wrong. Calling
    it for a non-existent run_id exercises the no-op branch and verifies
    no exception escapes."""
    # No db_session fixture — the helper opens its own connection.
    finalize_run_failsafe(
        TEST_DATABASE_URL,
        run_id=999_999_999,
        status="failed",
        reason="nonexistent_run_test",
    )


def test_finalize_run_failsafe_persists_close_reason(engine):
    """End-to-end: helper opens a fresh session, finalizes the run,
    and persists close_reason where the next session can read it.

    Bypasses the rollback-isolated db_session fixture because the helper
    opens its own connection that won't see uncommitted fixture data.
    """
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine)
    setup = session_factory()
    try:
        shop = Shop(name="failsafe_test_shop", base_url="https://failsafe.lt")
        setup.add(shop)
        setup.flush()
        run = create_scrape_run(setup, shop_id=shop.id, phase="scan")
        setup.commit()
        run_id = run.id
        shop_id = shop.id
    finally:
        setup.close()

    try:
        finalize_run_failsafe(
            TEST_DATABASE_URL,
            run_id=run_id,
            status="failed",
            reason="poisoned_session_test",
            resumable_after_failure=True,
        )

        verify = session_factory()
        try:
            updated = verify.get(ScrapeRun, run_id)
            assert updated is not None
            assert updated.status == "failed"
            assert updated.close_reason == "poisoned_session_test"
            assert updated.resumable_after_failure is True
        finally:
            verify.close()
    finally:
        cleanup = session_factory()
        try:
            cleanup.execute(
                text("DELETE FROM validation_issues WHERE scrape_run_id = :id"),
                {"id": run_id},
            )
            cleanup.execute(
                text("DELETE FROM scrape_runs WHERE id = :id"), {"id": run_id}
            )
            cleanup.execute(text("DELETE FROM shops WHERE id = :id"), {"id": shop_id})
            cleanup.commit()
        finally:
            cleanup.close()


def test_finalize_run_failsafe_skips_already_terminal_run(engine):
    """finalize_run_failsafe must NOT overwrite a run that already reached a
    terminal state (completed or failed).

    Regression test for the validate spider bug: finish_scrape_run sets
    status='completed' inside start(), then Scrapy calls closed() which
    fires finalize_run_failsafe(..., status='failed'). Without the guard the
    completed status is clobbered — run 424 exhibited exactly this."""
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine)
    setup = session_factory()
    try:
        shop = Shop(name="failsafe_terminal_guard_shop", base_url="https://guard.lt")
        setup.add(shop)
        setup.flush()
        run = create_scrape_run(setup, shop_id=shop.id, phase="validate")
        setup.commit()
        run_id = run.id
        shop_id = shop.id
    finally:
        setup.close()

    try:
        # Simulate the happy path: spider finishes and marks the run completed.
        happy = session_factory()
        try:
            finish_scrape_run(happy, run_id, status="completed", reason="finished")
            happy.commit()
        finally:
            happy.close()

        # Simulate closed() firing after start() already completed successfully.
        finalize_run_failsafe(
            TEST_DATABASE_URL,
            run_id=run_id,
            status="failed",
            reason="spider_closed",
        )

        verify = session_factory()
        try:
            updated = verify.get(ScrapeRun, run_id)
            assert updated is not None
            assert updated.status == "completed", (
                f"finalize_run_failsafe clobbered completed→failed "
                f"(close_reason={updated.close_reason!r})"
            )
        finally:
            verify.close()
    finally:
        cleanup = session_factory()
        try:
            cleanup.execute(
                text("DELETE FROM validation_issues WHERE scrape_run_id = :id"),
                {"id": run_id},
            )
            cleanup.execute(
                text("DELETE FROM scrape_runs WHERE id = :id"), {"id": run_id}
            )
            cleanup.execute(text("DELETE FROM shops WHERE id = :id"), {"id": shop_id})
            cleanup.commit()
        finally:
            cleanup.close()


def test_get_latest_completed_run(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    run = create_scrape_run(db_session, shop_id=shop.id, phase="discover_sitemap")
    finish_scrape_run(db_session, run_id=run.id, status="completed")
    latest = get_latest_completed_run(
        db_session, shop_id=shop.id, phase="discover_sitemap"
    )
    assert latest is not None
    assert latest.id == run.id


def test_get_latest_completed_run_returns_none(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    latest = get_latest_completed_run(
        db_session, shop_id=shop.id, phase="discover_sitemap"
    )
    assert latest is None


def test_mark_orphan_runs_failed_spans_shops_and_phases(db_session):
    shop_a = Shop(name="shop_a", base_url="https://a.lt")
    shop_b = Shop(name="shop_b", base_url="https://b.lt")
    db_session.add_all([shop_a, shop_b])
    db_session.flush()

    orphan_scan = create_scrape_run(db_session, shop_id=shop_a.id, phase="scan")
    orphan_discover = create_scrape_run(
        db_session, shop_id=shop_b.id, phase="discover_sitemap"
    )
    completed = create_scrape_run(db_session, shop_id=shop_a.id, phase="scan")
    finish_scrape_run(db_session, run_id=completed.id, status="completed")
    db_session.flush()

    orphans = mark_orphan_runs_failed(db_session)
    assert len(orphans) == 2

    db_session.refresh(orphan_scan)
    db_session.refresh(orphan_discover)
    db_session.refresh(completed)
    assert orphan_scan.status == "failed"
    assert orphan_scan.finished_at is not None
    assert orphan_scan.close_reason == "orphan_on_boot"
    assert orphan_discover.status == "failed"
    assert orphan_discover.finished_at is not None
    assert orphan_discover.close_reason == "orphan_on_boot"
    assert completed.status == "completed"


def test_mark_orphan_runs_failed_noop_when_none_running(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    run = create_scrape_run(db_session, shop_id=shop.id, phase="scan")
    finish_scrape_run(db_session, run_id=run.id, status="completed")
    db_session.flush()

    assert len(mark_orphan_runs_failed(db_session)) == 0


def test_update_scrape_run_progress(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()
    run = create_scrape_run(db_session, shop_id=shop.id, phase="scan", urls_total=100)
    update_scrape_run_progress(db_session, run_id=run.id, urls_processed=50)
    db_session.refresh(run)
    assert run.urls_processed == 50
    assert run.urls_total == 100


class TestUpsertValidationIssues:
    def test_creates_new_issue_on_first_detection(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        issues = [{"url": shop_book.url, "field": "isbn", "issue": "missing_isbn", "raw_value": None}]
        upsert_validation_issues(session, issues, shop_id=shop.id, run_id=scrape_run.id)
        session.flush()

        rows = session.execute(select(ValidationIssue)).scalars().all()
        assert len(rows) == 1
        vi = rows[0]
        assert vi.lifecycle_state == "new"
        assert vi.run_count == 1
        assert vi.first_seen_run_id == scrape_run.id
        assert vi.last_seen_run_id == scrape_run.id
        assert vi.shop_id == shop.id

    def test_increments_run_count_on_re_detection(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        issues = [{"url": shop_book.url, "field": "isbn", "issue": "missing_isbn"}]
        upsert_validation_issues(session, issues, shop_id=shop.id, run_id=scrape_run.id)
        session.flush()

        run2 = ScrapeRun(shop_id=shop.id, phase="validate", started_at=datetime.now(UTC), status="completed")
        session.add(run2)
        session.flush()

        upsert_validation_issues(session, issues, shop_id=shop.id, run_id=run2.id)
        session.flush()

        rows = session.execute(select(ValidationIssue)).scalars().all()
        assert len(rows) == 1, "upsert must not insert a second row"
        assert rows[0].run_count == 2
        assert rows[0].first_seen_run_id == scrape_run.id
        assert rows[0].last_seen_run_id == run2.id

    def test_resets_resolved_to_new_when_issue_reappears(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        vi = ValidationIssue(
            shop_id=shop.id, shop_book_id=shop_book.id, field="isbn",
            issue="missing_isbn", url=shop_book.url, lifecycle_state="resolved",
            last_seen_run_id=scrape_run.id, first_seen_run_id=scrape_run.id,
            resolved_at=datetime.now(UTC),
        )
        session.add(vi)
        session.flush()

        run2 = ScrapeRun(shop_id=shop.id, phase="validate", started_at=datetime.now(UTC), status="completed")
        session.add(run2)
        session.flush()

        issues = [{"url": shop_book.url, "field": "isbn", "issue": "missing_isbn"}]
        upsert_validation_issues(session, issues, shop_id=shop.id, run_id=run2.id)
        session.flush()

        session.refresh(vi)
        assert vi.lifecycle_state == "new"
        assert vi.resolved_at is None
        assert vi.run_count == 2

    def test_leaves_acknowledged_state_on_re_detection(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        vi = ValidationIssue(
            shop_id=shop.id, shop_book_id=shop_book.id, field="isbn",
            issue="missing_isbn", url=shop_book.url, lifecycle_state="acknowledged",
            acknowledged_at=datetime.now(UTC),
            last_seen_run_id=scrape_run.id, first_seen_run_id=scrape_run.id,
        )
        session.add(vi)
        session.flush()

        run2 = ScrapeRun(shop_id=shop.id, phase="validate", started_at=datetime.now(UTC), status="completed")
        session.add(run2)
        session.flush()

        issues = [{"url": shop_book.url, "field": "isbn", "issue": "missing_isbn"}]
        upsert_validation_issues(session, issues, shop_id=shop.id, run_id=run2.id)
        session.flush()

        session.refresh(vi)
        assert vi.lifecycle_state == "acknowledged"
        assert vi.run_count == 2


class TestResolveGoneIssues:
    def test_marks_open_issues_resolved_when_not_detected(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        vi = ValidationIssue(
            shop_id=shop.id, shop_book_id=shop_book.id, field="isbn",
            issue="missing_isbn", url=shop_book.url, lifecycle_state="new",
            last_seen_run_id=scrape_run.id, first_seen_run_id=scrape_run.id,
        )
        session.add(vi)
        session.flush()

        run2 = ScrapeRun(shop_id=shop.id, phase="validate", started_at=datetime.now(UTC), status="completed")
        session.add(run2)
        session.flush()

        resolve_gone_issues(session, shop_id=shop.id, run_id=run2.id)
        session.flush()

        session.refresh(vi)
        assert vi.lifecycle_state == "resolved"
        assert vi.resolved_at is not None

    def test_does_not_touch_already_resolved(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        vi = ValidationIssue(
            shop_id=shop.id, shop_book_id=shop_book.id, field="isbn",
            issue="missing_isbn", url=shop_book.url, lifecycle_state="resolved",
            resolved_at=datetime.now(UTC),
            last_seen_run_id=scrape_run.id, first_seen_run_id=scrape_run.id,
        )
        session.add(vi)
        session.flush()

        run2 = ScrapeRun(shop_id=shop.id, phase="validate", started_at=datetime.now(UTC), status="completed")
        session.add(run2)
        session.flush()

        resolve_gone_issues(session, shop_id=shop.id, run_id=run2.id)
        session.flush()

        session.refresh(vi)
        assert vi.lifecycle_state == "resolved"

    def test_does_not_affect_other_shops(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        other_shop = Shop(name="other_shop_resolve", base_url="https://other-vi.lt")
        session.add(other_shop)
        session.flush()
        other_run = ScrapeRun(shop_id=other_shop.id, phase="validate", started_at=datetime.now(UTC), status="completed")
        session.add(other_run)
        session.flush()

        vi = ValidationIssue(
            shop_id=other_shop.id, shop_book_id=None, discovered_url_id=None,
            field="isbn", issue="missing_isbn",
            url="http://other.example.com/book",
            lifecycle_state="new",
            last_seen_run_id=other_run.id, first_seen_run_id=other_run.id,
        )
        session.add(vi)
        session.flush()

        run2 = ScrapeRun(shop_id=shop.id, phase="validate", started_at=datetime.now(UTC), status="completed")
        session.add(run2)
        session.flush()

        resolve_gone_issues(session, shop_id=shop.id, run_id=run2.id)
        session.flush()

        session.refresh(vi)
        assert vi.lifecycle_state == "new"


class TestAcknowledgeIssues:
    def test_acknowledge_sets_acknowledged_state(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        vi = ValidationIssue(
            shop_id=shop.id, shop_book_id=shop_book.id, field="isbn",
            issue="missing_isbn", url=shop_book.url, lifecycle_state="new",
            last_seen_run_id=scrape_run.id, first_seen_run_id=scrape_run.id,
        )
        session.add(vi)
        session.flush()

        result = acknowledge_validation_issue(session, vi.id)
        session.flush()

        assert result is True
        session.refresh(vi)
        assert vi.lifecycle_state == "acknowledged"
        assert vi.acknowledged_at is not None

    def test_bulk_acknowledge_marks_all_new_for_issue_type(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        books = []
        for i in range(3):
            sb = ShopBook(shop_id=shop.id, sku=f"sku-bulk-{i}", title=f"Book {i}",
                          url=f"http://shop.lt/book-bulk-{i}")
            session.add(sb)
            books.append(sb)
        session.flush()

        for b in books:
            vi = ValidationIssue(
                shop_id=shop.id, shop_book_id=b.id, field="isbn",
                issue="missing_isbn", url=b.url, lifecycle_state="new",
                last_seen_run_id=scrape_run.id, first_seen_run_id=scrape_run.id,
            )
            session.add(vi)
        session.flush()

        count = bulk_acknowledge_issues(session, issue_type="missing_isbn", shop_id=shop.id)
        session.flush()

        assert count == len(books)
        rows = session.execute(
            select(ValidationIssue).where(ValidationIssue.shop_id == shop.id, ValidationIssue.issue == "missing_isbn")
        ).scalars().all()
        assert all(r.lifecycle_state == "acknowledged" for r in rows)

    def test_bulk_acknowledge_scoped_to_shop(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        other_shop = Shop(name="other_ack_shop", base_url="https://other-ack.lt")
        session.add(other_shop)
        session.flush()
        other_run = ScrapeRun(shop_id=other_shop.id, phase="validate", started_at=datetime.now(UTC), status="completed")
        session.add(other_run)
        session.flush()

        vi_mine = ValidationIssue(
            shop_id=shop.id, shop_book_id=shop_book.id, field="isbn",
            issue="missing_isbn_scope", url=shop_book.url, lifecycle_state="new",
            last_seen_run_id=scrape_run.id, first_seen_run_id=scrape_run.id,
        )
        other_sb = ShopBook(shop_id=other_shop.id, sku="x-scope", title="X", url="http://x.lt/b-scope")
        session.add_all([vi_mine, other_sb])
        session.flush()

        vi_other = ValidationIssue(
            shop_id=other_shop.id, shop_book_id=other_sb.id, field="isbn",
            issue="missing_isbn_scope", url=other_sb.url, lifecycle_state="new",
            last_seen_run_id=other_run.id, first_seen_run_id=other_run.id,
        )
        session.add(vi_other)
        session.flush()

        bulk_acknowledge_issues(session, issue_type="missing_isbn_scope", shop_id=shop.id)
        session.flush()

        session.refresh(vi_mine)
        session.refresh(vi_other)
        assert vi_mine.lifecycle_state == "acknowledged"
        assert vi_other.lifecycle_state == "new"


class TestGetIssuesGroups:
    def _make_vi(
        self,
        session: Session,
        shop: Shop,
        run: ScrapeRun,
        shop_book: ShopBook,
        issue: str,
        state: str,
    ) -> ValidationIssue:
        vi = ValidationIssue(
            shop_id=shop.id,
            shop_book_id=shop_book.id,
            field="isbn",
            issue=issue,
            url=shop_book.url,
            lifecycle_state=state,
            last_seen_run_id=run.id,
            first_seen_run_id=run.id,
        )
        session.add(vi)
        session.flush()
        return vi

    def test_group_by_type_aggregates(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        from book_scraper.dashboard.queries import get_issues_groups

        # Create a second shop_book for the same shop
        sb2 = ShopBook(shop_id=shop.id, sku="grp-sb2", url="http://s.lt/b2", title="B2")
        session.add(sb2)
        session.flush()
        self._make_vi(session, shop, scrape_run, shop_book, "missing_isbn", "new")
        self._make_vi(session, shop, scrape_run, sb2, "missing_isbn", "acknowledged")
        session.flush()

        groups = get_issues_groups(session, group_by="type")
        assert len(groups) == 1
        g = groups[0]
        assert g["issue_type"] == "missing_isbn"
        assert g["total"] == 2
        assert g["by_state"]["new"] == 1
        assert g["by_state"]["acknowledged"] == 1
        assert g["shop_name"] is None

    def test_group_by_type_shop_splits_shops(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        from book_scraper.dashboard.queries import get_issues_groups

        # Create a second shop
        other = Shop(name="other_grp", base_url="https://other-grp.lt")
        session.add(other)
        session.flush()
        other_run = ScrapeRun(shop_id=other.id, started_at=datetime.now(UTC), status="completed", phase="scan")
        session.add(other_run)
        session.flush()
        other_sb = ShopBook(shop_id=other.id, sku="o1", url="http://o.lt/b", title="O")
        session.add(other_sb)
        session.flush()

        self._make_vi(session, shop, scrape_run, shop_book, "missing_isbn", "new")
        self._make_vi(session, other, other_run, other_sb, "missing_isbn", "new")

        groups = get_issues_groups(session, group_by="type_shop")
        assert len(groups) == 2
        shops = {g["shop_name"] for g in groups}
        assert shops == {shop.name, "other_grp"}
        assert all(g["total"] == 1 for g in groups)

    def test_state_filter(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        from book_scraper.dashboard.queries import get_issues_groups

        sb2 = ShopBook(shop_id=shop.id, sku="sf-sb2", url="http://s.lt/b-sf2", title="B2-sf")
        session.add(sb2)
        session.flush()
        self._make_vi(session, shop, scrape_run, shop_book, "missing_isbn", "new")
        self._make_vi(session, shop, scrape_run, sb2, "missing_isbn", "resolved")

        groups = get_issues_groups(session, group_by="type", state="new")
        assert len(groups) == 1
        assert groups[0]["total"] == 1
