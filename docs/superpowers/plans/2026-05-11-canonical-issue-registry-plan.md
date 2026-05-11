# Canonical Issue Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the append-only `validation_issues` log with a single-row-per-issue canonical registry that auto-resolves gone issues, deduplicates floods, and adds a grouped view with bulk-acknowledge.

**Architecture:** Alembic migration deduplicates existing rows and alters the enum. `upsert_validation_issues` + `resolve_gone_issues` replace `bulk_insert_validation_issues`. The dashboard gains a shop filter and a view-mode toggle (List / By type / By type × shop) backed by a new `/api/issues/groups` endpoint.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, PostgreSQL, Alembic, FastAPI, React (CDN, no build step)

---

## File Map

| File | Change |
|------|--------|
| `alembic/versions/XXXXXX_canonical_issue_registry.py` | New migration: schema + enum + data dedup |
| `book_scraper/db/models.py` | `ValidationIssue` model + `validation_lifecycle` enum |
| `book_scraper/db/repo.py` | Add `upsert_validation_issues`, `resolve_gone_issues`, `bulk_acknowledge_issues`; remove `bulk_insert_validation_issues`, `_assign_lifecycle_states`; update `acknowledge_validation_issue` |
| `book_scraper/services/validate.py` | Call `upsert_validation_issues` + `resolve_gone_issues` |
| `book_scraper/dashboard/queries.py` | Update `get_issues_page` (new column names + states); add `get_issues_groups`; update `get_issue_counts` |
| `book_scraper/dashboard/routes/api.py` | Update `GET /issues`; add `GET /issues/groups`, `POST /issues/bulk-acknowledge` |
| `book_scraper/dashboard/static/hifi/hf-other.jsx` | Update `HFIssues` tabs; add shop filter, view-mode toggle, grouped rows, Ack-all |
| `tests/integration/test_scrape_runs_repo.py` | Replace `bulk_insert` tests with upsert + resolve tests |
| `tests/unit/test_validate_spider.py` | Update lifecycle state references |

---

## Task 1: Alembic Migration

**Files:**
- Create: `alembic/versions/XXXXXX_canonical_issue_registry.py`

- [ ] **Step 1: Generate the migration stub**

```bash
cd /Users/evaldas/Projects/book-scraper
PYTHONPATH=. uv run alembic revision --autogenerate -m "canonical_issue_registry"
```

Note the generated filename (e.g. `abc123_canonical_issue_registry.py`) — replace `XXXXXX` below.

- [ ] **Step 2: Replace the generated upgrade() with the full migration**

Open the generated file and replace its entire content with:

```python
"""canonical issue registry

Revision ID: <generated>
Revises: d1f2e5b8a9c4
Create Date: 2026-05-11

Transforms validation_issues from append-only log to canonical registry:
one row per (entity, field, issue_type). Adds shop_id, first/last_seen_run_id,
run_count, resolved_at, snoozed_until. Alters enum: drops recurring/already_seen,
adds acknowledged/snoozed/resolved. Deduplicates existing rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "<generated>"
down_revision: Union[str, Sequence[str], None] = "d1f2e5b8a9c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add new columns (all nullable initially for safe backfill)
    op.add_column("validation_issues", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.add_column("validation_issues", sa.Column("first_seen_run_id", sa.Integer(), nullable=True))
    op.add_column("validation_issues", sa.Column("run_count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("validation_issues", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("validation_issues", sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True))

    # 2. Rename scrape_run_id -> last_seen_run_id
    op.alter_column("validation_issues", "scrape_run_id", new_column_name="last_seen_run_id")

    # 3. Backfill shop_id (shop_book → discovered_url → scrape_run fallback)
    conn.execute(text("""
        UPDATE validation_issues vi
        SET shop_id = sb.shop_id
        FROM shop_books sb
        WHERE vi.shop_book_id = sb.id AND vi.shop_id IS NULL
    """))
    conn.execute(text("""
        UPDATE validation_issues vi
        SET shop_id = du.shop_id
        FROM discovered_urls du
        WHERE vi.discovered_url_id = du.id AND vi.shop_id IS NULL
    """))
    conn.execute(text("""
        UPDATE validation_issues vi
        SET shop_id = sr.shop_id
        FROM scrape_runs sr
        WHERE vi.last_seen_run_id = sr.id AND vi.shop_id IS NULL
    """))

    # 4. Backfill first_seen_run_id = last_seen_run_id (pre-dedup; dedup fixes min later)
    conn.execute(text("UPDATE validation_issues SET first_seen_run_id = last_seen_run_id"))

    # 5. Migrate enum: TEXT intermediate → new type
    #    PostgreSQL does not support DROP VALUE or RENAME VALUE on enums,
    #    so we recreate the type.
    conn.execute(text("ALTER TABLE validation_issues ALTER COLUMN lifecycle_state TYPE TEXT"))
    conn.execute(text("UPDATE validation_issues SET lifecycle_state = 'acknowledged' WHERE lifecycle_state = 'already_seen'"))
    conn.execute(text("UPDATE validation_issues SET lifecycle_state = 'new' WHERE lifecycle_state = 'recurring'"))
    conn.execute(text("ALTER TYPE validation_lifecycle RENAME TO validation_lifecycle_old"))
    conn.execute(text("CREATE TYPE validation_lifecycle AS ENUM ('new', 'acknowledged', 'snoozed', 'resolved')"))
    conn.execute(text("""
        ALTER TABLE validation_issues
        ALTER COLUMN lifecycle_state TYPE validation_lifecycle
        USING lifecycle_state::validation_lifecycle
    """))
    conn.execute(text("DROP TYPE validation_lifecycle_old"))

    # 6. Data deduplication: collapse groups to one canonical row
    #    Keep the row with MAX(id) in each (entity, field, issue) group.
    #    Update it with MIN(first_seen_run_id), COUNT(*), preserve ack state.
    result = conn.execute(text("""
        SELECT
            COALESCE(shop_book_id, -1)    AS sb_id,
            COALESCE(discovered_url_id, -1) AS du_id,
            url, field, issue,
            array_agg(id ORDER BY id DESC) AS ids,
            MIN(first_seen_run_id)         AS min_run_id,
            COUNT(*)                       AS cnt,
            BOOL_OR(acknowledged_at IS NOT NULL) AS was_acked
        FROM validation_issues
        GROUP BY
            COALESCE(shop_book_id, -1),
            COALESCE(discovered_url_id, -1),
            url, field, issue
        HAVING COUNT(*) > 1
    """))
    for row in result:
        keep_id = row.ids[0]
        delete_ids = list(row.ids[1:])
        conn.execute(text("""
            UPDATE validation_issues
            SET first_seen_run_id = :min_run_id,
                run_count         = :cnt,
                lifecycle_state   = CASE
                    WHEN :was_acked THEN 'acknowledged'::validation_lifecycle
                    ELSE lifecycle_state
                END
            WHERE id = :keep_id
        """), {"min_run_id": row.min_run_id, "cnt": int(row.cnt),
               "was_acked": bool(row.was_acked), "keep_id": keep_id})
        if delete_ids:
            conn.execute(
                text("DELETE FROM validation_issues WHERE id = ANY(:ids)"),
                {"ids": delete_ids},
            )

    # 7. Add FK constraints and NOT NULL on shop_id
    op.create_foreign_key("fk_vi_shop_id", "validation_issues", "shops", ["shop_id"], ["id"])
    op.create_foreign_key("fk_vi_first_seen_run_id", "validation_issues", "scrape_runs",
                          ["first_seen_run_id"], ["id"])
    op.alter_column("validation_issues", "shop_id", nullable=False)

    # 8. Partial unique indexes (enforce one canonical row per entity×issue)
    op.create_index(
        "uix_vi_shop_book_field_issue",
        "validation_issues",
        ["shop_book_id", "field", "issue"],
        unique=True,
        postgresql_where=sa.text("shop_book_id IS NOT NULL"),
    )
    op.create_index(
        "uix_vi_discovered_url_field_issue",
        "validation_issues",
        ["discovered_url_id", "field", "issue"],
        unique=True,
        postgresql_where=sa.text("discovered_url_id IS NOT NULL"),
    )
    op.create_index(
        "uix_vi_url_field_issue",
        "validation_issues",
        ["url", "field", "issue"],
        unique=True,
        postgresql_where=sa.text("shop_book_id IS NULL AND discovered_url_id IS NULL"),
    )
    op.create_index("ix_vi_shop_id_lifecycle", "validation_issues",
                    ["shop_id", "lifecycle_state"])


def downgrade() -> None:
    op.drop_index("ix_vi_shop_id_lifecycle", "validation_issues")
    op.drop_index("uix_vi_url_field_issue", "validation_issues")
    op.drop_index("uix_vi_discovered_url_field_issue", "validation_issues")
    op.drop_index("uix_vi_shop_book_field_issue", "validation_issues")
    op.drop_constraint("fk_vi_first_seen_run_id", "validation_issues")
    op.drop_constraint("fk_vi_shop_id", "validation_issues")

    conn = op.get_bind()
    conn.execute(text("ALTER TABLE validation_issues ALTER COLUMN lifecycle_state TYPE TEXT"))
    conn.execute(text("ALTER TYPE validation_lifecycle RENAME TO validation_lifecycle_old"))
    conn.execute(text("CREATE TYPE validation_lifecycle AS ENUM ('new', 'recurring', 'already_seen')"))
    conn.execute(text("""
        ALTER TABLE validation_issues
        ALTER COLUMN lifecycle_state TYPE validation_lifecycle
        USING (CASE lifecycle_state
            WHEN 'acknowledged' THEN 'already_seen'
            WHEN 'snoozed'      THEN 'new'
            WHEN 'resolved'     THEN 'new'
            ELSE lifecycle_state
        END)::validation_lifecycle
    """))
    conn.execute(text("DROP TYPE validation_lifecycle_old"))

    op.alter_column("validation_issues", "last_seen_run_id", new_column_name="scrape_run_id")
    op.drop_column("validation_issues", "snoozed_until")
    op.drop_column("validation_issues", "resolved_at")
    op.drop_column("validation_issues", "run_count")
    op.drop_column("validation_issues", "first_seen_run_id")
    op.drop_column("validation_issues", "shop_id")
```

- [ ] **Step 3: Run the migration**

```bash
PYTHONPATH=. uv run alembic upgrade head
```

Expected: no errors. If it fails on the enum step, check that `d1f2e5b8a9c4` is the current head: `PYTHONPATH=. uv run alembic current`.

- [ ] **Step 4: Verify migration applied correctly**

```bash
PYTHONPATH=. uv run python -c "
from book_scraper.db.session import get_session
from sqlalchemy import inspect, text
with get_session() as s:
    cols = {c['name'] for c in inspect(s.bind).get_columns('validation_issues')}
    print('columns:', cols)
    row = s.execute(text(\"SELECT enum_range(NULL::validation_lifecycle)\")).scalar()
    print('enum values:', row)
"
```

Expected output contains: `shop_id`, `first_seen_run_id`, `last_seen_run_id`, `run_count`, `resolved_at`, `snoozed_until` in columns; enum shows `(new,acknowledged,snoozed,resolved)`.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat: canonical issue registry migration — schema, enum, dedup"
```

---

## Task 2: Update ValidationIssue Model

**Files:**
- Modify: `book_scraper/db/models.py`

- [ ] **Step 1: Update the enum definition**

Find this block in `models.py` (around line 367):
```python
validation_lifecycle_enum = Enum(
    "new",
    "recurring",
    "already_seen",
    name="validation_lifecycle",
    create_type=False,
)
```

Replace with:
```python
validation_lifecycle_enum = Enum(
    "new",
    "acknowledged",
    "snoozed",
    "resolved",
    name="validation_lifecycle",
    create_type=False,
)
```

- [ ] **Step 2: Update the ValidationIssue model**

Find the `ValidationIssue` class (around line 603). Replace the entire class with:

```python
class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(
        ForeignKey("shops.id"), nullable=False, index=True
    )
    last_seen_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=False, index=True
    )
    first_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[str] = mapped_column(String, nullable=False)
    issue: Mapped[str] = mapped_column(String, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    shop_book_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_books.id"), nullable=True, index=True
    )
    discovered_url_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovered_urls.id"), nullable=True, index=True
    )
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lifecycle_state: Mapped[str] = mapped_column(
        validation_lifecycle_enum,
        nullable=False,
        server_default="new",
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    snoozed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "NOT (shop_book_id IS NOT NULL AND discovered_url_id IS NOT NULL)",
            name="ck_validation_issues_single_entity",
        ),
        Index("ix_validation_issues_lifecycle_state", "lifecycle_state"),
        Index("ix_vi_shop_id_lifecycle", "shop_id", "lifecycle_state"),
    )

    last_seen_run: Mapped["ScrapeRun"] = relationship(
        foreign_keys=[last_seen_run_id], back_populates="validation_issues"
    )
    first_seen_run: Mapped["ScrapeRun | None"] = relationship(
        foreign_keys=[first_seen_run_id]
    )
    shop: Mapped["Shop"] = relationship(foreign_keys=[shop_id])
    shop_book: Mapped["ShopBook | None"] = relationship()
    discovered_url: Mapped["DiscoveredUrl | None"] = relationship()
```

- [ ] **Step 3: Update the ScrapeRun back-reference**

Find the `ScrapeRun.validation_issues` relationship (search for `back_populates="validation_issues"`). It currently references `scrape_run_id`. Update the `foreign_keys` kwarg to use `last_seen_run_id`:

```python
validation_issues: Mapped[list["ValidationIssue"]] = relationship(
    back_populates="last_seen_run",
    foreign_keys="ValidationIssue.last_seen_run_id",
)
```

- [ ] **Step 4: Verify model loads**

```bash
PYTHONPATH=. uv run python -c "from book_scraper.db.models import ValidationIssue; print('OK')"
```

Expected: `OK` with no errors.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/db/models.py
git commit -m "feat: update ValidationIssue model for canonical registry"
```

---

## Task 3: upsert_validation_issues + resolve_gone_issues

**Files:**
- Modify: `book_scraper/db/repo.py`
- Modify: `tests/integration/test_scrape_runs_repo.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_scrape_runs_repo.py`. Find the existing `bulk_insert` tests and add these after them (keep old tests for now — we'll delete them in Step 5):

```python
from book_scraper.db.repo import upsert_validation_issues, resolve_gone_issues

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

        run2 = ScrapeRun(shop_id=shop.id, started_at=datetime.now(UTC), status="completed")
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

        run2 = ScrapeRun(shop_id=shop.id, started_at=datetime.now(UTC), status="completed")
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

        run2 = ScrapeRun(shop_id=shop.id, started_at=datetime.now(UTC), status="completed")
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

        run2 = ScrapeRun(shop_id=shop.id, started_at=datetime.now(UTC), status="completed")
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

        run2 = ScrapeRun(shop_id=shop.id, started_at=datetime.now(UTC), status="completed")
        session.add(run2)
        session.flush()

        resolve_gone_issues(session, shop_id=shop.id, run_id=run2.id)
        session.flush()

        session.refresh(vi)
        assert vi.lifecycle_state == "resolved"  # unchanged

    def test_does_not_affect_other_shops(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        other_shop = Shop(name="other_shop", scrape_interval_days=1)
        session.add(other_shop)
        session.flush()
        other_run = ScrapeRun(shop_id=other_shop.id, started_at=datetime.now(UTC), status="completed")
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

        run2 = ScrapeRun(shop_id=shop.id, started_at=datetime.now(UTC), status="completed")
        session.add(run2)
        session.flush()

        resolve_gone_issues(session, shop_id=shop.id, run_id=run2.id)
        session.flush()

        session.refresh(vi)
        assert vi.lifecycle_state == "new"  # not touched
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/integration/test_scrape_runs_repo.py::TestUpsertValidationIssues tests/integration/test_scrape_runs_repo.py::TestResolveGoneIssues -v
```

Expected: all fail with `ImportError: cannot import name 'upsert_validation_issues'`.

- [ ] **Step 3: Implement upsert_validation_issues in repo.py**

In `repo.py`, add these imports near the top of the file (with other SQLAlchemy imports):
```python
from sqlalchemy.dialects.postgresql import insert as pg_insert
```

Add the URL-resolution helper (extracted from `bulk_insert_validation_issues`) — find the section that builds `shop_book_by_url` / `du_by_url` and extract it:

```python
def _resolve_entity_fks(
    session: Session,
    issues: list[dict[str, str | int | None]],
    shop_id: int,
) -> None:
    """Resolve url strings to shop_book_id / discovered_url_id FKs in-place."""
    urls: set[str] = {str(i["url"]) for i in issues if i.get("url") and not i.get("shop_book_id") and not i.get("discovered_url_id")}
    if not urls:
        return
    sb_rows = session.execute(
        select(ShopBook.url, ShopBook.id).where(
            ShopBook.shop_id == shop_id, ShopBook.url.in_(urls)
        )
    ).all()
    shop_book_by_url = {url: sid for url, sid in sb_rows}
    leftover = urls - shop_book_by_url.keys()
    du_by_url: dict[str, int] = {}
    if leftover:
        norm_map = {url: normalize_url(str(url)) for url in leftover}
        rev = {v: k for k, v in norm_map.items()}
        du_rows = session.execute(
            select(DiscoveredUrl.normalized_url, DiscoveredUrl.id).where(
                DiscoveredUrl.shop_id == shop_id,
                DiscoveredUrl.normalized_url.in_(norm_map.values()),
            )
        ).all()
        for normalized, du_id in du_rows:
            raw = rev.get(normalized)
            if raw is not None:
                du_by_url[raw] = du_id
    for issue in issues:
        if issue.get("shop_book_id") or issue.get("discovered_url_id"):
            continue
        url = issue.get("url")
        if url and url in shop_book_by_url:
            issue["shop_book_id"] = shop_book_by_url[str(url)]
        elif url and url in du_by_url:
            issue["discovered_url_id"] = du_by_url[str(url)]
```

Then add the upsert function:

```python
def upsert_validation_issues(
    session: Session,
    issues: list[dict[str, str | int | None]],
    shop_id: int,
    run_id: int,
) -> None:
    """Upsert detected issues as canonical rows (one per entity×field×issue_type).

    On first detection: INSERT with lifecycle_state='new', run_count=1.
    On re-detection of open/ack/snoozed: UPDATE last_seen_run_id, run_count++.
    On re-detection of resolved: reset to 'new', clear resolved_at.
    Snoozed issues whose snoozed_until has passed are reset to 'new'.
    """
    if not issues:
        return
    _resolve_entity_fks(session, issues, shop_id)

    # Split by entity type — each needs a distinct ON CONFLICT target
    sb_issues = [i for i in issues if i.get("shop_book_id")]
    du_issues = [i for i in issues if i.get("discovered_url_id") and not i.get("shop_book_id")]
    url_issues = [i for i in issues if not i.get("shop_book_id") and not i.get("discovered_url_id")]

    def _make_values(batch: list[dict[str, str | int | None]]) -> list[dict[str, object]]:
        return [
            {
                "shop_id": shop_id,
                "last_seen_run_id": run_id,
                "first_seen_run_id": run_id,
                "url": str(i.get("url") or ""),
                "field": str(i.get("field") or ""),
                "issue": str(i.get("issue") or ""),
                "raw_value": i.get("raw_value"),
                "shop_book_id": i.get("shop_book_id"),
                "discovered_url_id": i.get("discovered_url_id"),
                "lifecycle_state": "new",
                "run_count": 1,
            }
            for i in batch
        ]

    _on_conflict_set = {
        "last_seen_run_id": pg_insert(ValidationIssue).excluded.last_seen_run_id,
        "run_count": ValidationIssue.run_count + 1,
        "raw_value": pg_insert(ValidationIssue).excluded.raw_value,
        "lifecycle_state": sa.case(
            (ValidationIssue.lifecycle_state == "resolved", sa.literal("new")),
            (
                sa.and_(
                    ValidationIssue.lifecycle_state == "snoozed",
                    ValidationIssue.snoozed_until <= sa.func.now(),
                ),
                sa.literal("new"),
            ),
            else_=ValidationIssue.lifecycle_state,
        ),
        "resolved_at": sa.case(
            (ValidationIssue.lifecycle_state == "resolved", sa.null()),
            else_=ValidationIssue.resolved_at,
        ),
    }

    if sb_issues:
        stmt = pg_insert(ValidationIssue).values(_make_values(sb_issues))
        stmt = stmt.on_conflict_do_update(
            index_elements=["shop_book_id", "field", "issue"],
            index_where=ValidationIssue.shop_book_id.isnot(None),
            set_=_on_conflict_set,
        )
        session.execute(stmt)

    if du_issues:
        stmt = pg_insert(ValidationIssue).values(_make_values(du_issues))
        stmt = stmt.on_conflict_do_update(
            index_elements=["discovered_url_id", "field", "issue"],
            index_where=ValidationIssue.discovered_url_id.isnot(None),
            set_=_on_conflict_set,
        )
        session.execute(stmt)

    if url_issues:
        stmt = pg_insert(ValidationIssue).values(_make_values(url_issues))
        stmt = stmt.on_conflict_do_update(
            index_elements=["url", "field", "issue"],
            index_where=sa.and_(
                ValidationIssue.shop_book_id.is_(None),
                ValidationIssue.discovered_url_id.is_(None),
            ),
            set_=_on_conflict_set,
        )
        session.execute(stmt)
```

Note: `sa` here is `sqlalchemy` — add `import sqlalchemy as sa` if not already present at the top of `repo.py`.

- [ ] **Step 4: Implement resolve_gone_issues in repo.py**

```python
def resolve_gone_issues(session: Session, shop_id: int, run_id: int) -> int:
    """Mark open issues not detected in run_id as resolved.

    Called after upsert_validation_issues for the same run. Any canonical
    issue for this shop whose last_seen_run_id is not the current run was
    absent from the validation and is considered resolved.

    Returns the number of rows updated.
    """
    now = datetime.now(UTC)
    result = session.execute(
        sa.update(ValidationIssue)
        .where(
            ValidationIssue.shop_id == shop_id,
            ValidationIssue.last_seen_run_id != run_id,
            ValidationIssue.lifecycle_state.in_(["new", "acknowledged", "snoozed"]),
        )
        .values(lifecycle_state="resolved", resolved_at=now)
    )
    return result.rowcount  # type: ignore[return-value]
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/integration/test_scrape_runs_repo.py::TestUpsertValidationIssues tests/integration/test_scrape_runs_repo.py::TestResolveGoneIssues -v
```

Expected: all pass.

- [ ] **Step 6: Remove old functions**

Delete `bulk_insert_validation_issues` and `_assign_lifecycle_states` from `repo.py`. Run the full test suite to confirm nothing else breaks:

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```

Fix any remaining references to `bulk_insert_validation_issues` in test files (replace with `upsert_validation_issues` using the same signature: `upsert_validation_issues(session, issues, shop_id=shop.id, run_id=scrape_run.id)`).

- [ ] **Step 7: Commit**

```bash
git add book_scraper/db/repo.py tests/integration/test_scrape_runs_repo.py
git commit -m "feat: add upsert_validation_issues + resolve_gone_issues; remove bulk_insert"
```

---

## Task 4: Update ValidateService Write Path

**Files:**
- Modify: `book_scraper/services/validate.py`
- Modify: `tests/unit/test_validate_spider.py`

- [ ] **Step 1: Update the import in validate.py**

Find the import of `bulk_insert_validation_issues` in `validate.py`. Replace it:

```python
# Before:
from book_scraper.db.repo import bulk_insert_validation_issues
# After:
from book_scraper.db.repo import resolve_gone_issues, upsert_validation_issues
```

- [ ] **Step 2: Update ValidateService.run()**

Replace the `bulk_insert_validation_issues` call:

```python
def run(self, shop_id: int, run_id: int) -> dict[str, int]:
    issues: list[dict[str, str | int | None]] = []
    issues.extend(self.check_structural_duplicates(shop_id, run_id))
    issues.extend(self.check_slug_title_mismatch(shop_id, run_id))
    issues.extend(self.check_data_completeness(shop_id, run_id))
    issues.extend(self.check_data_correctness(shop_id, run_id))
    issues.extend(self.check_classification_consistency(shop_id, run_id))
    issues.extend(self.check_staleness(shop_id, run_id))
    issues.extend(self.check_match_readiness(shop_id, run_id))
    issues.extend(self.check_relationship_integrity(shop_id, run_id))

    upsert_validation_issues(self._session, issues, shop_id=shop_id, run_id=run_id)
    resolve_gone_issues(self._session, shop_id=shop_id, run_id=run_id)

    counters: dict[str, int] = {}
    for issue in issues:
        key = str(issue["issue"])
        counters[key] = counters.get(key, 0) + 1
    return counters
```

- [ ] **Step 3: Fix test_validate_spider.py**

Open `tests/unit/test_validate_spider.py`. Find any references to:
- `lifecycle_state == "recurring"` → change to `"new"`
- `lifecycle_state == "already_seen"` → change to `"acknowledged"`
- `bulk_insert_validation_issues` import → change to `upsert_validation_issues`

Run to verify:
```bash
uv run pytest tests/unit/test_validate_spider.py -v
```

Expected: all pass.

- [ ] **Step 4: Run integration tests**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/services/validate.py tests/unit/test_validate_spider.py
git commit -m "feat: ValidateService uses upsert + resolve_gone_issues"
```

---

## Task 5: bulk_acknowledge_issues + acknowledge_validation_issue Fix

**Files:**
- Modify: `book_scraper/db/repo.py`
- Modify: `tests/integration/test_scrape_runs_repo.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/integration/test_scrape_runs_repo.py`:

```python
from book_scraper.db.repo import acknowledge_validation_issue, bulk_acknowledge_issues

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
        for i in range(3):
            sb = ShopBook(shop_id=shop.id, shop_sku=f"sku-{i}", title=f"Book {i}",
                          url=f"http://shop.lt/book-{i}")
            session.add(sb)
        session.flush()

        books = session.execute(select(ShopBook).where(ShopBook.shop_id == shop.id)).scalars().all()
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
        rows = session.execute(select(ValidationIssue)).scalars().all()
        assert all(r.lifecycle_state == "acknowledged" for r in rows)

    def test_bulk_acknowledge_scoped_to_shop(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        other_shop = Shop(name="other", scrape_interval_days=1)
        session.add(other_shop)
        session.flush()
        other_run = ScrapeRun(shop_id=other_shop.id, started_at=datetime.now(UTC), status="completed")
        session.add(other_run)
        session.flush()

        vi_mine = ValidationIssue(
            shop_id=shop.id, shop_book_id=shop_book.id, field="isbn",
            issue="missing_isbn", url=shop_book.url, lifecycle_state="new",
            last_seen_run_id=scrape_run.id, first_seen_run_id=scrape_run.id,
        )
        other_sb = ShopBook(shop_id=other_shop.id, shop_sku="x", title="X", url="http://x.lt/b")
        session.add_all([vi_mine, other_sb])
        session.flush()

        vi_other = ValidationIssue(
            shop_id=other_shop.id, shop_book_id=other_sb.id, field="isbn",
            issue="missing_isbn", url=other_sb.url, lifecycle_state="new",
            last_seen_run_id=other_run.id, first_seen_run_id=other_run.id,
        )
        session.add(vi_other)
        session.flush()

        bulk_acknowledge_issues(session, issue_type="missing_isbn", shop_id=shop.id)
        session.flush()

        session.refresh(vi_mine)
        session.refresh(vi_other)
        assert vi_mine.lifecycle_state == "acknowledged"
        assert vi_other.lifecycle_state == "new"  # not touched
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/integration/test_scrape_runs_repo.py::TestAcknowledgeIssues -v
```

Expected: fail on `ImportError` for `bulk_acknowledge_issues`.

- [ ] **Step 3: Update acknowledge_validation_issue in repo.py**

Find the existing `acknowledge_validation_issue` function and update the lifecycle state value:

```python
def acknowledge_validation_issue(session: Session, issue_id: int) -> bool:
    """Mark an issue as acknowledged. Returns True if updated."""
    issue = session.get(ValidationIssue, issue_id)
    if issue is None:
        return False
    issue.lifecycle_state = "acknowledged"
    issue.acknowledged_at = datetime.now(UTC)
    session.flush()
    return True
```

- [ ] **Step 4: Add bulk_acknowledge_issues to repo.py**

```python
def bulk_acknowledge_issues(
    session: Session,
    issue_type: str,
    shop_id: int | None = None,
) -> int:
    """Acknowledge all 'new' issues of a given type, optionally scoped to a shop.

    Returns the count of rows updated.
    """
    stmt = (
        sa.update(ValidationIssue)
        .where(
            ValidationIssue.issue == issue_type,
            ValidationIssue.lifecycle_state == "new",
        )
        .values(lifecycle_state="acknowledged", acknowledged_at=datetime.now(UTC))
    )
    if shop_id is not None:
        stmt = stmt.where(ValidationIssue.shop_id == shop_id)
    result = session.execute(stmt)
    return result.rowcount  # type: ignore[return-value]
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/integration/test_scrape_runs_repo.py::TestAcknowledgeIssues -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add book_scraper/db/repo.py tests/integration/test_scrape_runs_repo.py
git commit -m "feat: add bulk_acknowledge_issues; fix acknowledge state to 'acknowledged'"
```

---

## Task 6: get_issues_groups Query

**Files:**
- Modify: `book_scraper/dashboard/queries.py`
- Modify: `tests/integration/test_scrape_runs_repo.py` (or a new test file)

- [ ] **Step 1: Write failing tests**

Add to `tests/integration/test_scrape_runs_repo.py`:

```python
from book_scraper.dashboard.queries import get_issues_groups

class TestGetIssuesGroups:
    def _make_vi(self, session: Session, shop: Shop, run: ScrapeRun,
                  shop_book: ShopBook, issue: str, state: str) -> ValidationIssue:
        vi = ValidationIssue(
            shop_id=shop.id, shop_book_id=shop_book.id, field="isbn",
            issue=issue, url=shop_book.url, lifecycle_state=state,
            last_seen_run_id=run.id, first_seen_run_id=run.id,
        )
        session.add(vi)
        session.flush()
        return vi

    def test_group_by_type_aggregates_across_shops(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        sb2 = ShopBook(shop_id=shop.id, shop_sku="s2", title="B2", url="http://s.lt/b2")
        session.add(sb2)
        session.flush()
        self._make_vi(session, shop, scrape_run, shop_book, "missing_isbn", "new")
        self._make_vi(session, shop, scrape_run, sb2, "missing_isbn", "acknowledged")

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
        other = Shop(name="other", scrape_interval_days=1)
        session.add(other)
        session.flush()
        other_run = ScrapeRun(shop_id=other.id, started_at=datetime.now(UTC), status="completed")
        session.add(other_run)
        session.flush()
        other_sb = ShopBook(shop_id=other.id, shop_sku="o1", title="O", url="http://o.lt/b")
        session.add(other_sb)
        session.flush()

        self._make_vi(session, shop, scrape_run, shop_book, "missing_isbn", "new")
        self._make_vi(session, other, other_run, other_sb, "missing_isbn", "new")

        groups = get_issues_groups(session, group_by="type_shop")
        assert len(groups) == 2
        shops = {g["shop_name"] for g in groups}
        assert shops == {shop.name, "other"}
        assert all(g["total"] == 1 for g in groups)

    def test_state_filter_scopes_results(
        self, session: Session, shop: Shop, scrape_run: ScrapeRun, shop_book: ShopBook
    ) -> None:
        sb2 = ShopBook(shop_id=shop.id, shop_sku="s2", title="B2", url="http://s.lt/b2")
        session.add(sb2)
        session.flush()
        self._make_vi(session, shop, scrape_run, shop_book, "missing_isbn", "new")
        self._make_vi(session, shop, scrape_run, sb2, "missing_isbn", "resolved")

        groups = get_issues_groups(session, group_by="type", state="new")
        assert len(groups) == 1
        assert groups[0]["total"] == 1
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/integration/test_scrape_runs_repo.py::TestGetIssuesGroups -v
```

Expected: fail on `ImportError`.

- [ ] **Step 3: Add get_issues_groups to queries.py**

Find the `ISSUE_SEVERITY` dict in `queries.py` (or `routes/api.py` — it may live there). Note its location. Then add the function near the end of `queries.py`:

```python
def get_issues_groups(
    session: Session,
    group_by: str = "type",
    state: str | None = None,
    shop_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return grouped issue counts for the grouped-view toggle.

    group_by='type'      → one row per issue_type across all shops.
    group_by='type_shop' → one row per (issue_type, shop).
    state                → optional filter: 'new'|'acknowledged'|'snoozed'|'resolved'.
    shop_id              → optional shop scope (narrows both group_by modes).
    """
    q = (
        select(
            ValidationIssue.issue.label("issue_type"),
            Shop.name.label("shop_name"),
            Shop.id.label("shop_id_val"),
            func.count().label("total"),
            func.count()
            .filter(ValidationIssue.lifecycle_state == "new")
            .label("cnt_new"),
            func.count()
            .filter(ValidationIssue.lifecycle_state == "acknowledged")
            .label("cnt_acknowledged"),
            func.count()
            .filter(ValidationIssue.lifecycle_state == "snoozed")
            .label("cnt_snoozed"),
            func.count()
            .filter(ValidationIssue.lifecycle_state == "resolved")
            .label("cnt_resolved"),
        )
        .outerjoin(Shop, Shop.id == ValidationIssue.shop_id)
    )

    if shop_id is not None:
        q = q.where(ValidationIssue.shop_id == shop_id)
    if state:
        q = q.where(ValidationIssue.lifecycle_state == state)

    if group_by == "type_shop":
        q = q.group_by(ValidationIssue.issue, Shop.name, Shop.id).order_by(
            func.count().desc(), ValidationIssue.issue
        )
    else:
        q = q.group_by(ValidationIssue.issue).order_by(func.count().desc())

    rows = session.execute(q).all()

    # Import ISSUE_SEVERITY from wherever it's defined in this codebase
    # (search for ISSUE_SEVERITY = { in routes/api.py or queries.py)
    from book_scraper.dashboard.routes.api import ISSUE_SEVERITY  # adjust path if needed

    return [
        {
            "issue_type": r.issue_type,
            "shop_name": r.shop_name if group_by == "type_shop" else None,
            "shop_id": r.shop_id_val if group_by == "type_shop" else None,
            "severity": ISSUE_SEVERITY.get(r.issue_type, "warning"),
            "total": r.total,
            "by_state": {
                "new": r.cnt_new,
                "acknowledged": r.cnt_acknowledged,
                "snoozed": r.cnt_snoozed,
                "resolved": r.cnt_resolved,
            },
        }
        for r in rows
    ]
```

Note: if `ISSUE_SEVERITY` lives in `queries.py` already, skip the import. If it's in `routes/api.py`, either move it to `queries.py` or import it as shown.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/integration/test_scrape_runs_repo.py::TestGetIssuesGroups -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/queries.py tests/integration/test_scrape_runs_repo.py
git commit -m "feat: add get_issues_groups query for grouped view"
```

---

## Task 7: Update Dashboard Queries (get_issues_page + get_issue_counts)

**Files:**
- Modify: `book_scraper/dashboard/queries.py`

- [ ] **Step 1: Update get_issues_page**

Find `get_issues_page` in `queries.py`. Make these changes:

*a) Update the join — replace `scrape_run_id` with `last_seen_run_id`:*
```python
# Before:
.outerjoin(ScrapeRun, ValidationIssue.scrape_run_id == ScrapeRun.id)
# After:
.outerjoin(ScrapeRun, ValidationIssue.last_seen_run_id == ScrapeRun.id)
```

*b) Update the state filter block — replace the whole `if state in {...}` section:*
```python
if state in {"new", "acknowledged", "snoozed", "resolved"}:
    query = query.filter(ValidationIssue.lifecycle_state == state)
elif state == "open":
    # Legacy alias: treat as 'new' for backwards compat during transition
    query = query.filter(ValidationIssue.lifecycle_state == "new")
# empty string / None = no filter (show all)
```

*c) Update the response dict construction — find where each issue row is built into a dict and add/rename fields:*

```python
# In the section that builds the response dict for each row, update:
"scrape_run_id": vi.last_seen_run_id,        # was: vi.scrape_run_id
"last_seen_run_id": vi.last_seen_run_id,     # new
"first_seen_run_id": vi.first_seen_run_id,   # new
"run_count": vi.run_count,                   # new
"resolved_at": vi.resolved_at.isoformat() if vi.resolved_at else None,  # new
"snoozed_until": vi.snoozed_until.isoformat() if vi.snoozed_until else None,  # new
"lifecycle_state": vi.lifecycle_state,
# Remove the "recurring" / "already_seen" mappings that may exist
```

- [ ] **Step 2: Update get_issue_counts**

Find `get_issue_counts` in `queries.py` or `routes/api.py`. It currently returns counts keyed by old state names. Update it to return new state names:

```python
def get_issue_counts(session: Session, shop_id: int | None = None) -> dict[str, int]:
    """Return counts by lifecycle state for badge display."""
    q = select(
        ValidationIssue.lifecycle_state,
        func.count().label("cnt"),
    ).group_by(ValidationIssue.lifecycle_state)
    if shop_id is not None:
        q = q.where(ValidationIssue.shop_id == shop_id)
    rows = session.execute(q).all()
    counts = {r.lifecycle_state: r.cnt for r in rows}
    return {
        "new": counts.get("new", 0),
        "acknowledged": counts.get("acknowledged", 0),
        "snoozed": counts.get("snoozed", 0),
        "resolved": counts.get("resolved", 0),
        "total": sum(counts.values()),
    }
```

- [ ] **Step 3: Smoke-test queries compile**

```bash
PYTHONPATH=. uv run python -c "from book_scraper.dashboard.queries import get_issues_page, get_issue_counts, get_issues_groups; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Run integration tests**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/queries.py
git commit -m "feat: update get_issues_page + get_issue_counts for canonical registry"
```

---

## Task 8: Update API Routes + Add New Endpoints

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py`

- [ ] **Step 1: Update GET /issues endpoint**

Find `api_issues` in `routes/api.py`. Change the default `state` parameter from `"open"` to `"new"`:

```python
@router.get("/issues")
def api_issues(
    state: str = "new",   # was "open"
    ...
```

No other changes needed — the query layer already handles the new state names.

- [ ] **Step 2: Add GET /issues/groups endpoint**

Add after the existing `api_issues` function:

```python
@router.get("/issues/groups")
def api_issues_groups(
    group_by: str = "type",
    state: str = "",
    shop: str = "",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """GET /issues/groups — aggregated issue counts for the grouped view.

    group_by: 'type' (default) or 'type_shop'.
    state: optional filter ('new'|'acknowledged'|'snoozed'|'resolved').
    shop: optional shop name filter.
    """
    shop_id: int | None = None
    if shop:
        shop_obj = session.execute(select(Shop).where(Shop.name == shop)).scalar()
        shop_id = shop_obj.id if shop_obj else None

    groups = get_issues_groups(
        session,
        group_by=group_by,
        state=state or None,
        shop_id=shop_id,
    )
    return {"groups": groups, "group_by": group_by}
```

Add `get_issues_groups` to the import from `book_scraper.dashboard.queries`.

- [ ] **Step 3: Add POST /issues/bulk-acknowledge endpoint**

```python
@router.post("/issues/bulk-acknowledge")
def api_bulk_acknowledge_issues(
    payload: dict[str, Any],
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """POST /issues/bulk-acknowledge — acknowledge all new issues of a type.

    Body: { "issue_type": "missing_isbn", "shop": "humanitas" (optional) }
    """
    issue_type = str(payload.get("issue_type") or "")
    if not issue_type:
        raise HTTPException(status_code=422, detail="issue_type is required")

    shop_id: int | None = None
    shop_name = payload.get("shop") or ""
    if shop_name:
        shop_obj = session.execute(select(Shop).where(Shop.name == shop_name)).scalar()
        shop_id = shop_obj.id if shop_obj else None

    count = bulk_acknowledge_issues(session, issue_type=issue_type, shop_id=shop_id)
    session.commit()
    return {"acknowledged": count}
```

Add `bulk_acknowledge_issues` to the import from `book_scraper.db.repo`.

- [ ] **Step 4: Smoke-test all three endpoints**

Start the server (or use the running instance) and test:

```bash
curl -s http://localhost:8000/api/issues?state=new | python3 -m json.tool | head -20
curl -s "http://localhost:8000/api/issues/groups?group_by=type" | python3 -m json.tool | head -20
curl -s -X POST http://localhost:8000/api/issues/bulk-acknowledge \
  -H "Content-Type: application/json" -d '{"issue_type":"__test_nonexistent"}' | python3 -m json.tool
```

Expected: all return valid JSON; bulk-acknowledge returns `{"acknowledged": 0}`.

- [ ] **Step 5: Run dashboard smoke tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add book_scraper/dashboard/routes/api.py
git commit -m "feat: add /issues/groups + /issues/bulk-acknowledge endpoints; default state=new"
```

---

## Task 9: Frontend — Tabs, Shop Filter, View Mode, Groups

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-other.jsx`

- [ ] **Step 1: Update lifecycle state mapping + tabs in HFIssues**

Find the `rows` mapping near line 130 and update `known`:

```javascript
// Before:
known: i.lifecycle_state === 'already_seen',
// After:
known: i.lifecycle_state === 'acknowledged',
```

Find the tabs definition (around line 383). Replace the existing tabs array:

```javascript
HFTabs active={tab} onChange={t => { setTab(t); setFilters(f => ({...f, state: t === 'all' ? '' : t})); }} tabs={[
  { id:'new',          label:'New',          count: counts.new },
  { id:'acknowledged', label:'Acknowledged', count: counts.acknowledged },
  { id:'snoozed',      label:'Snoozed',      count: counts.snoozed },
  { id:'resolved',     label:'Resolved',     count: counts.resolved },
  { id:'all',          label:'All',          count: counts.total },
]}
```

Update the initial `filters` state and `tab` state:

```javascript
const [tab, setTab] = React.useState('new');
const [filters, setFilters] = React.useState({
  state: 'new',
  shop: '',
  issue_type: '',
  severity: '',
  url_type: '',
  book_type: '',
});
```

Update the `counts` reference in the component (it now uses `new`/`acknowledged`/`snoozed`/`resolved`/`total` instead of old keys):

```javascript
const counts = data.counts || { new: 0, acknowledged: 0, snoozed: 0, resolved: 0, total: 0 };
```

- [ ] **Step 2: Add shop filter dropdown**

The issues page has a filter bar. Find the `<select>` or filter row (around line 457). Add a shop filter after the existing severity select. You'll need to fetch shops first — add a `shops` state and effect near the top of the component:

```javascript
const [shops, setShops] = React.useState([]);
React.useEffect(() => {
  fetch('/api/shops')
    .then(r => r.json())
    .then(d => setShops(d.shops || []));
}, []);
```

Then in the filter bar:
```javascript
<select value={filters.shop} onChange={e => setFilters(f => ({...f, shop: e.target.value}))}>
  <option value="">All shops</option>
  {shops.map(s => (
    <option key={s.name} value={s.name}>{s.name}</option>
  ))}
</select>
```

- [ ] **Step 3: Add view-mode toggle state + fetch logic**

Add state near the top of `HFIssues`:

```javascript
const [viewMode, setViewMode] = React.useState('list'); // 'list' | 'by_type' | 'by_type_shop'
const [groups, setGroups] = React.useState([]);
const [groupsLoading, setGroupsLoading] = React.useState(false);
```

Add an effect that fetches groups when `viewMode !== 'list'`:

```javascript
React.useEffect(() => {
  if (viewMode === 'list') return;
  const groupBy = viewMode === 'by_type_shop' ? 'type_shop' : 'type';
  const params = new URLSearchParams();
  params.set('group_by', groupBy);
  if (filters.shop) params.set('shop', filters.shop);
  if (filters.state) params.set('state', filters.state);
  setGroupsLoading(true);
  fetch(`/api/issues/groups?${params}`)
    .then(r => r.json())
    .then(d => { setGroups(d.groups || []); setGroupsLoading(false); })
    .catch(() => setGroupsLoading(false));
}, [viewMode, filters.shop, filters.state]);
```

- [ ] **Step 4: Add view-mode toggle buttons**

In the render, above the issue list, add:

```javascript
<div style={{display:'flex', gap:'8px', marginBottom:'12px', alignItems:'center'}}>
  {[
    {id:'list',         label:'List'},
    {id:'by_type',      label:'By type'},
    {id:'by_type_shop', label:'By type × shop'},
  ].map(m => (
    <button
      key={m.id}
      onClick={() => setViewMode(m.id)}
      style={{
        padding:'4px 12px', borderRadius:'6px', border:'1px solid',
        cursor:'pointer',
        background: viewMode === m.id ? 'var(--pico-primary)' : 'transparent',
        color: viewMode === m.id ? '#fff' : 'inherit',
        borderColor: viewMode === m.id ? 'var(--pico-primary)' : 'var(--pico-muted-border-color)',
      }}
    >{m.label}</button>
  ))}
</div>
```

- [ ] **Step 5: Add grouped view rendering**

In the render, replace the current list render with a conditional:

```javascript
{viewMode === 'list' ? (
  /* existing flat list render — no change needed */
  <ExistingIssueList ... />
) : (
  <div>
    {groupsLoading && <div>Loading groups…</div>}
    {groups.map(g => {
      const key = viewMode === 'by_type_shop'
        ? `${g.shop_name}/${g.issue_type}`
        : g.issue_type;
      const severityColor = g.severity === 'critical' ? '#e53e3e'
        : g.severity === 'warning' ? '#d69e2e' : '#718096';
      return (
        <div key={key} style={{
          display:'flex', alignItems:'center', gap:'12px',
          padding:'10px 14px', marginBottom:'6px',
          border:'1px solid var(--pico-muted-border-color)',
          borderRadius:'8px', background:'var(--pico-card-background-color)',
        }}>
          <span style={{
            width:'10px', height:'10px', borderRadius:'50%',
            background: severityColor, flexShrink:0,
          }} />
          {viewMode === 'by_type_shop' && (
            <span style={{fontWeight:500, color:'var(--pico-muted-color)', fontSize:'0.85em'}}>
              {g.shop_name}
            </span>
          )}
          <span style={{flex:1, fontWeight:500}}>{g.issue_type}</span>
          {g.by_state.new > 0 && (
            <span style={{
              background:'#e53e3e', color:'#fff', borderRadius:'12px',
              padding:'1px 8px', fontSize:'0.8em', fontWeight:600,
            }}>{g.by_state.new} new</span>
          )}
          <span style={{color:'var(--pico-muted-color)', fontSize:'0.85em'}}>
            {g.total} total
          </span>
          <button
            onClick={() => {
              fetch('/api/issues/bulk-acknowledge', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({
                  issue_type: g.issue_type,
                  shop: viewMode === 'by_type_shop' ? g.shop_name : (filters.shop || undefined),
                }),
              }).then(() => {
                // Re-fetch groups and list counts
                setFilters(f => ({...f}));
              });
            }}
            style={{
              padding:'3px 10px', borderRadius:'5px', border:'1px solid',
              cursor:'pointer', fontSize:'0.8em',
              borderColor:'var(--pico-muted-border-color)',
            }}
          >Ack all</button>
          <button
            onClick={() => setFilters(f => ({
              ...f,
              issue_type: g.issue_type,
              ...(viewMode === 'by_type_shop' ? {shop: g.shop_name || ''} : {}),
            })) || setViewMode('list')}
            style={{
              padding:'3px 10px', borderRadius:'5px', border:'1px solid',
              cursor:'pointer', fontSize:'0.8em',
              borderColor:'var(--pico-muted-border-color)',
            }}
          >View</button>
        </div>
      );
    })}
    {!groupsLoading && groups.length === 0 && (
      <div style={{textAlign:'center', color:'var(--pico-muted-color)', padding:'40px'}}>
        No issues in this view.
      </div>
    )}
  </div>
)}
```

- [ ] **Step 6: Verify in browser**

Open http://localhost:8000/issues. Check:
1. Default tab is "New" (not "Open")
2. Shop filter dropdown appears and works
3. Toggle buttons "List / By type / By type × shop" appear
4. Clicking "By type" loads group rows with counts
5. "Ack all" button on a group row triggers the API call and refreshes
6. "View" button on a group row switches back to List filtered to that issue type
7. "By type × shop" splits by shop

- [ ] **Step 7: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-other.jsx
git commit -m "feat: issues page — new tabs, shop filter, grouped view with bulk-ack"
```

---

## Task 10: Rebuild and Final Smoke Test

- [ ] **Step 1: Rebuild dashboard image**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

- [ ] **Step 2: Verify migration ran in the DB**

```bash
PYTHONPATH=. uv run alembic current
```

Expected: `head`.

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all pass.

- [ ] **Step 4: Run dashboard route smoke tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all pass.

- [ ] **Step 5: Manual verification**

Open http://localhost:8000/issues and confirm:
- "New" tab shows only `lifecycle_state='new'` issues
- Shop dropdown filters correctly
- Grouped view shows correct counts per issue type
- Ack all marks issues as acknowledged and they move to "Acknowledged" tab
- Resolved tab shows issues no longer detected in last validation run

- [ ] **Step 6: Final commit**

```bash
git commit --allow-empty -m "chore: canonical issue registry — all tasks complete"
```

---

## Spec Coverage Check

| Spec requirement | Task |
|---|---|
| Single canonical row per entity×field×issue | Task 1 (unique indexes), Task 3 (upsert) |
| shop_id, first/last_seen_run_id, run_count, resolved_at, snoozed_until | Task 1+2 |
| Enum: new/acknowledged/snoozed/resolved | Task 1+2 |
| upsert: UPDATE on re-detection, reset resolved→new | Task 3 |
| resolve_gone_issues auto-resolves absent issues | Task 3 |
| ValidateService calls upsert+resolve | Task 4 |
| bulk_acknowledge_issues | Task 5 |
| acknowledge_validation_issue uses 'acknowledged' | Task 5 |
| get_issues_groups (by type + by type×shop) | Task 6 |
| get_issues_page new field names + state names | Task 7 |
| GET /issues default state=new | Task 8 |
| GET /issues/groups endpoint | Task 8 |
| POST /issues/bulk-acknowledge endpoint | Task 8 |
| UI: New/Acknowledged/Snoozed/Resolved/All tabs | Task 9 |
| UI: shop filter dropdown | Task 9 |
| UI: view-mode toggle List/By type/By type×shop | Task 9 |
| UI: grouped rows with severity, counts, Ack all | Task 9 |
| Ack all navigates to filtered flat list via View btn | Task 9 |
| Data dedup migration for existing rows | Task 1 |
