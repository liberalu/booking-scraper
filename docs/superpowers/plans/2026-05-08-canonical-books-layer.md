# Canonical Books Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a canonical `books` layer separate from commercial `shop_books`. Populate it from ibiblioteka.lt (LIBIS) authoritatively, link existing shop_books via ISBN, and synthesize `shop_inferred` rows for ISBNs that appear on multiple shops without LIBIS coverage.

**Architecture:** Two layers — canonical (books, book_isbns, book_authors, authors, publishers, series) populated by the ibiblioteka spider; commercial (shop_books) gets a `book_id` FK set by a new match phase. Match runs as a per-shop spider via the existing `scrapy crawl` launcher. UI gets a Books list + detail page.

**Tech Stack:** Python 3.12, Scrapy with asyncio reactor, SQLAlchemy 2.0, Alembic, PostgreSQL, FastAPI + Jinja2 + React-via-CDN (HFShell pattern), Docker compose. Tests: pytest with real Postgres on port 5433.

**Spec:** [docs/superpowers/specs/2026-05-08-canonical-books-layer-design.md](../specs/2026-05-08-canonical-books-layer-design.md)

**Migration state at plan authoring:** `c5d8e2f3a9b1` (canonical layer schema) is already at head. Do NOT re-apply.

---

## Task 0: Worktree audit and stash

**Files:** none modified — diagnostic only.

The working tree contains uncommitted ibiblioteka work. Inspect each modified file before any task touches it. Engineer must understand what already exists vs what to create.

- [ ] **Step 0.1: Run git status**

```bash
git status
```

Expected: a list including `book_scraper/spiders/ibiblioteka/`, modifications to `book_scraper/spiders/discover.py`, `book_scraper/config_models.py`, `book_scraper/dashboard/static/hifi/*`, untracked `tests/fixtures/ibiblioteka/`, and the migration file `alembic/versions/c5d8e2f3a9b1_create_canonical_books_layer.py`.

- [ ] **Step 0.2: Verify migration head**

```bash
PYTHONPATH=. uv run alembic current
```

Expected: `c5d8e2f3a9b1 (head)`.

- [ ] **Step 0.3: Snapshot current state**

```bash
git stash push -u -m "pre-canonical-books-layer-impl"
git stash list
```

Expected: one stash entry. Tasks below restore individual files from this stash as needed via `git checkout stash@{0} -- <path>`.

- [ ] **Step 0.4: Verify clean tree before starting Task 1**

```bash
git status
```

Expected: `working tree clean` (everything is in stash@{0}).

---

## Task 1: SQLAlchemy models for canonical layer

**Files:**
- Modify: `book_scraper/db/models.py` — add 6 new model classes
- Test: `tests/integration/test_canonical_models.py` (new)

The migration `c5d8e2f3a9b1` already created the tables. This task only adds the ORM mapping so application code can query them.

- [ ] **Step 1.1: Write failing integration test**

Create `tests/integration/test_canonical_models.py`:

```python
"""Integration tests for canonical book layer ORM models."""
from datetime import datetime
import pytest
from sqlalchemy import select

from book_scraper.db.models import (
    Author, Book, BookAuthor, BookIsbn, Publisher, Series,
)


def test_publisher_round_trip(test_session):
    pub = Publisher(name="Šviesa", country="LT")
    test_session.add(pub)
    test_session.flush()
    assert pub.id is not None
    found = test_session.execute(select(Publisher).where(Publisher.name == "Šviesa")).scalar_one()
    assert found.country == "LT"


def test_book_with_publisher_and_series(test_session):
    pub = Publisher(name="Tyto Alba")
    series = Series(title="Tylioji srovė")
    test_session.add_all([pub, series])
    test_session.flush()

    book = Book(
        data_source="ibiblioteka",
        libis_code="LIBIS000000123456",
        title="Test Book",
        year=2024,
        publisher_id=pub.id,
        series_id=series.id,
    )
    test_session.add(book)
    test_session.flush()
    assert book.id is not None


def test_book_isbn_unique(test_session):
    book = Book(data_source="ibiblioteka", libis_code="LIBIS000000999999", title="X")
    test_session.add(book)
    test_session.flush()
    test_session.add(BookIsbn(book_id=book.id, isbn="9789876543210", isbn_type="isbn13"))
    test_session.flush()
    test_session.add(BookIsbn(book_id=book.id, isbn="9789876543210", isbn_type="isbn13"))
    with pytest.raises(Exception):
        test_session.flush()


def test_book_author_with_role(test_session):
    book = Book(data_source="ibiblioteka", libis_code="LIBIS000000888888", title="Y")
    author = Author(name="Mildažytė, Edita", normalized_name="mildazyte edita")
    test_session.add_all([book, author])
    test_session.flush()
    test_session.add(BookAuthor(book_id=book.id, author_id=author.id, role="author", position=0))
    test_session.flush()


def test_libis_code_required_for_ibiblioteka(test_session):
    """CHECK constraint enforces libis_code when data_source='ibiblioteka'."""
    book = Book(data_source="ibiblioteka", libis_code=None, title="Bad")
    test_session.add(book)
    with pytest.raises(Exception):
        test_session.flush()


def test_shop_inferred_libis_code_optional(test_session):
    book = Book(data_source="shop_inferred", libis_code=None, title="Inferred")
    test_session.add(book)
    test_session.flush()
    assert book.id is not None
```

- [ ] **Step 1.2: Run test, expect import error**

```bash
uv run pytest tests/integration/test_canonical_models.py -v
```

Expected: `ImportError: cannot import name 'Author' from 'book_scraper.db.models'`.

- [ ] **Step 1.3: Add ORM models to `book_scraper/db/models.py`**

Find the end of the file (after `class CronJob` or similar terminal model). Add:

```python
# ── Canonical book layer ──────────────────────────────────────────────────
# Tables created by Alembic c5d8e2f3a9b1; ORM mappings only here.

book_data_source_enum = Enum(
    "ibiblioteka", "shop_inferred", "manual",
    name="book_data_source", create_type=False,
)

book_isbn_type_enum = Enum(
    "isbn10", "isbn13", "ebook", "audio", "unknown",
    name="book_isbn_type", create_type=False,
)

book_author_role_enum = Enum(
    "author", "translator", "narrator", "illustrator", "editor", "compiler",
    name="book_author_role", create_type=False,
)


class Publisher(Base):
    __tablename__ = "publishers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    libis_codes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_text("now()")
    )


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    libis_code: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_text("now()")
    )


class Author(Base):
    """Canonical author with international authority codes.

    Distinct from `shop_authors` (raw shop dedup). The matcher links
    `shop_authors.canonical_author_id` to `authors.id` after a book
    matches by ISBN — no name-based heuristics.
    """

    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    libis_code: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    viaf_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    isni: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    wikidata_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_text("now()")
    )


class Book(Base):
    """Canonical book record. data_source='ibiblioteka' requires libis_code
    (enforced by CHECK constraint on the table).
    """

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_source: Mapped[str] = mapped_column(book_data_source_enum, nullable=False)
    libis_code: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_full: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publisher_id: Mapped[int | None] = mapped_column(
        ForeignKey("publishers.id", ondelete="SET NULL"), nullable=True
    )
    series_id: Mapped[int | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), nullable=True
    )
    release_place: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    format: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimensions: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated_from: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    upcoming_release: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa_text("false")
    )
    udc_codes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    subjects: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    libis_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    libis_review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_text("now()")
    )

    publisher: Mapped["Publisher | None"] = relationship()
    series_rel: Mapped["Series | None"] = relationship()
    isbns: Mapped[list["BookIsbn"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )
    authors_join: Mapped[list["BookAuthor"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )


class BookIsbn(Base):
    __tablename__ = "book_isbns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    isbn: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    isbn_type: Mapped[str] = mapped_column(
        book_isbn_type_enum, nullable=False, server_default="unknown"
    )

    book: Mapped["Book"] = relationship(back_populates="isbns")


class BookAuthor(Base):
    __tablename__ = "book_authors"

    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        book_author_role_enum, primary_key=True, server_default="author"
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    book: Mapped["Book"] = relationship(back_populates="authors_join")
    author: Mapped["Author"] = relationship()
```

- [ ] **Step 1.3b: Add `book_id` and `canonical_author_id` to existing models**

In the same file, find `class ShopBook` and add to its columns (alongside other `match_*` fields):

```python
    book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL"), nullable=True, index=True
    )
```

Find `class ShopAuthor` and add:

```python
    canonical_author_id: Mapped[int | None] = mapped_column(
        ForeignKey("authors.id", ondelete="SET NULL"), nullable=True, index=True
    )
```

- [ ] **Step 1.4: Run test, expect pass**

```bash
uv run pytest tests/integration/test_canonical_models.py -v
```

Expected: 6 PASSED.

- [ ] **Step 1.5: Run full test suite for regression**

```bash
uv run pytest tests/unit/ tests/integration/test_db_repo.py -q 2>&1 | tail -3
```

Expected: same pass count as before Task 1 (no regressions from new ORM imports).

- [ ] **Step 1.6: Commit**

```bash
git add book_scraper/db/models.py tests/integration/test_canonical_models.py
git commit -m "feat(db): add SQLAlchemy models for canonical book layer

Adds Publisher, Series, Author, Book, BookIsbn, BookAuthor ORM mappings
over the tables created in migration c5d8e2f3a9b1. Adds book_id FK to
ShopBook and canonical_author_id FK to ShopAuthor for matcher use.

No behavior change — pure mapping layer."
```

---

## Task 2: BookItem, ISBN utilities, and pipeline

**Files:**
- Modify: `book_scraper/isbn.py` — add converters
- Modify: `book_scraper/items.py` — add `BookItem`
- Modify: `book_scraper/pipelines.py` — normalize on store, add `BookItem` branch
- Test: `tests/unit/test_isbn_converters.py` (new)
- Test: `tests/integration/test_book_pipeline.py` (new)

### Sub-task 2A: ISBN-10 ↔ ISBN-13 converters

- [ ] **Step 2A.1: Write failing test**

Create `tests/unit/test_isbn_converters.py`:

```python
import pytest
from book_scraper.isbn import to_isbn10, to_isbn13, normalize_isbn


def test_to_isbn13_from_isbn10():
    assert to_isbn13("0306406152") == "9780306406157"


def test_to_isbn13_from_already_13():
    assert to_isbn13("9780306406157") == "9780306406157"


def test_to_isbn13_strips_dashes():
    assert to_isbn13("0-306-40615-2") == "9780306406157"


def test_to_isbn10_from_isbn13_with_978_prefix():
    assert to_isbn10("9780306406157") == "0306406152"


def test_to_isbn10_returns_none_for_979_prefix():
    """ISBN-13s starting with 979 have no ISBN-10 equivalent."""
    assert to_isbn10("9791234567896") is None


def test_to_isbn10_from_already_10_returns_normalized():
    assert to_isbn10("0306406152") == "0306406152"


def test_to_isbn10_handles_x_check_digit():
    assert to_isbn10("9780306406201") == "030640620X"


def test_normalize_isbn_strips_dashes_and_spaces():
    assert normalize_isbn("978-0-306-40615-7") == "9780306406157"
    assert normalize_isbn("978 0 306 40615 7") == "9780306406157"
```

- [ ] **Step 2A.2: Run test, expect failure**

```bash
uv run pytest tests/unit/test_isbn_converters.py -v
```

Expected: ImportError (`to_isbn10` / `to_isbn13` don't exist yet).

- [ ] **Step 2A.3: Implement converters in `book_scraper/isbn.py`**

Append to the existing file:

```python
def to_isbn13(raw: str | None) -> str | None:
    """Return the ISBN-13 form of an ISBN. Returns None on invalid input."""
    cleaned = normalize_isbn(raw)
    if not cleaned:
        return None
    if _ISBN_13_RE.match(cleaned):
        return cleaned
    if _ISBN_10_RE.match(cleaned):
        body = "978" + cleaned[:9]
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(body))
        check = (10 - total % 10) % 10
        return body + str(check)
    return None


def to_isbn10(raw: str | None) -> str | None:
    """Return the ISBN-10 form of an ISBN. Returns None for 979-prefixed
    ISBN-13s (no ISBN-10 equivalent) or invalid input.
    """
    cleaned = normalize_isbn(raw)
    if not cleaned:
        return None
    if _ISBN_10_RE.match(cleaned):
        return cleaned.upper()
    if _ISBN_13_RE.match(cleaned):
        if not cleaned.startswith("978"):
            return None  # 979-prefixed ISBN-13s have no ISBN-10 equivalent
        body = cleaned[3:12]
        total = sum(int(d) * (10 - i) for i, d in enumerate(body))
        check = (11 - total % 11) % 11
        return body + ("X" if check == 10 else str(check))
    return None
```

- [ ] **Step 2A.4: Run test, expect pass**

```bash
uv run pytest tests/unit/test_isbn_converters.py -v
```

Expected: 8 PASSED.

- [ ] **Step 2A.5: Commit (will amend later, but checkpoint here)**

Don't commit yet — combine with the pipeline change in Task 2D.

### Sub-task 2B: ValidationPipeline normalizes stored ISBN

- [ ] **Step 2B.1: Write failing integration test**

Create `tests/integration/test_book_pipeline.py`:

```python
"""Integration tests for ISBN normalization on shop_books store and BookItem upsert."""
from book_scraper.items import ShopBookItem
from book_scraper.pipelines import ValidationPipeline


def test_validation_pipeline_normalizes_dashed_isbn():
    item = ShopBookItem(
        url="https://example.com/p/1",
        shop_name="vaga",
        title="X",
        isbn="978-0-306-40615-7",
        price="10.0",
    )
    p = ValidationPipeline()
    result = p.process_item(item)
    assert result["isbn"] == "9780306406157"


def test_validation_pipeline_keeps_already_normalized_isbn():
    item = ShopBookItem(
        url="https://example.com/p/2",
        shop_name="vaga",
        title="Y",
        isbn="9780306406157",
        price="10.0",
    )
    p = ValidationPipeline()
    result = p.process_item(item)
    assert result["isbn"] == "9780306406157"


def test_validation_pipeline_drops_invalid_isbn_to_none():
    item = ShopBookItem(
        url="https://example.com/p/3",
        shop_name="vaga",
        title="Z",
        isbn="not-an-isbn",
        price="10.0",
    )
    p = ValidationPipeline()
    result = p.process_item(item)
    assert result["isbn"] is None
```

- [ ] **Step 2B.2: Run test, expect first one to fail**

```bash
uv run pytest tests/integration/test_book_pipeline.py::test_validation_pipeline_normalizes_dashed_isbn -v
```

Expected: FAIL — `assert "978-0-306-40615-7" == "9780306406157"`.

- [ ] **Step 2B.3: Modify ValidationPipeline to normalize ISBN**

In `book_scraper/pipelines.py`, find the block around line 275 that currently does:

```python
            isbn = adapter.get("isbn")
            if isbn is not None and not _is_valid_isbn(isbn):
                self._warn("invalid_isbn", "isbn", url, str(isbn))
                adapter["isbn"] = None
```

Replace with (adding normalization on the success path):

```python
            isbn = adapter.get("isbn")
            if isbn is not None:
                if _is_valid_isbn(isbn):
                    from book_scraper.isbn import normalize_isbn
                    adapter["isbn"] = normalize_isbn(isbn)
                else:
                    self._warn("invalid_isbn", "isbn", url, str(isbn))
                    adapter["isbn"] = None
```

- [ ] **Step 2B.4: Run test, expect pass**

```bash
uv run pytest tests/integration/test_book_pipeline.py -v
```

Expected: 3 PASSED.

### Sub-task 2C: BookItem definition

- [ ] **Step 2C.1: Add BookItem to `book_scraper/items.py`**

Append to the file:

```python
class BookItem(scrapy.Item):
    """Canonical bibliographic record. Goes to the books table.

    Distinct from ShopBookItem: no price, no shop, no URL — represents
    a book as it exists in the world (LIBIS catalogue or shop_inferred).
    """

    libis_code = scrapy.Field()       # required when data_source='ibiblioteka'
    data_source = scrapy.Field()      # 'ibiblioteka' | 'shop_inferred' | 'manual'
    title = scrapy.Field()
    title_full = scrapy.Field()
    year = scrapy.Field()
    publisher = scrapy.Field()        # name (str); pipeline upserts into publishers
    series = scrapy.Field()           # title (str); pipeline upserts into series
    isbns = scrapy.Field()            # list[dict]: [{"isbn": str, "type": str}]
    authors = scrapy.Field()          # list[dict]: [{"name": str, "libis_code": str|None,
                                      #               "role": str, "position": int}]
    release_place = scrapy.Field()
    type = scrapy.Field()             # 'book' | 'audio' | 'ebook'
    format = scrapy.Field()           # 'PRINTED' | 'ELECTRONIC'
    pages = scrapy.Field()
    duration = scrapy.Field()
    dimensions = scrapy.Field()
    language = scrapy.Field()
    translated_from = scrapy.Field()
    description = scrapy.Field()
    cover_url = scrapy.Field()
    upcoming_release = scrapy.Field()
    udc_codes = scrapy.Field()
    subjects = scrapy.Field()
    audience = scrapy.Field()
    libis_rating = scrapy.Field()
    libis_review_count = scrapy.Field()
```

- [ ] **Step 2C.2: Verify import**

```bash
uv run python -c "from book_scraper.items import BookItem; b = BookItem(title='X'); print(b)"
```

Expected: `{'title': 'X'}`.

### Sub-task 2D: PostgresPipeline upsert path for BookItem

- [ ] **Step 2D.1: Write failing integration test**

Append to `tests/integration/test_book_pipeline.py`:

```python
import pytest
from sqlalchemy import select

from book_scraper.items import BookItem
from book_scraper.db.models import Book, BookAuthor, BookIsbn, Author, Publisher


@pytest.fixture
def book_pipeline(test_engine):
    """PostgresPipeline configured to write to the test DB."""
    from book_scraper.pipelines import PostgresPipeline
    pipeline = PostgresPipeline()
    pipeline.engine = test_engine  # injected; bypass open_spider for unit-style use
    return pipeline


def test_bookitem_inserts_publishers_series_authors_isbns(test_session, book_pipeline):
    item = BookItem(
        libis_code="LIBIS000000111111",
        data_source="ibiblioteka",
        title="Test Book",
        year=2024,
        publisher="Šviesa",
        series="Maži milžinai",
        isbns=[{"isbn": "9780306406157", "type": "isbn13"}],
        authors=[{"name": "Mildažytė, Edita", "libis_code": "LNB:Hd0;=BC",
                  "role": "author", "position": 0}],
    )
    # process_item writes via its own session; query the test session afterwards
    book_pipeline.process_item(item)

    book = test_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000111111")
    ).scalar_one()
    assert book.title == "Test Book"
    assert book.year == 2024
    pub = test_session.execute(
        select(Publisher).where(Publisher.name == "Šviesa")
    ).scalar_one()
    assert book.publisher_id == pub.id
    assert book.series_id is not None
    isbns = test_session.execute(
        select(BookIsbn.isbn).where(BookIsbn.book_id == book.id)
    ).scalars().all()
    # Original + auto-computed ISBN-10
    assert "9780306406157" in isbns
    assert "0306406152" in isbns
    authors = test_session.execute(
        select(Author).join(BookAuthor).where(BookAuthor.book_id == book.id)
    ).scalars().all()
    assert any(a.libis_code == "LNB:Hd0;=BC" for a in authors)


def test_bookitem_re_upsert_idempotent(test_session, book_pipeline):
    """Same libis_code processed twice updates fields but doesn't duplicate."""
    base = BookItem(
        libis_code="LIBIS000000222222",
        data_source="ibiblioteka",
        title="First Title",
        year=2023,
        isbns=[{"isbn": "9780306406164", "type": "isbn13"}],
    )
    book_pipeline.process_item(base)

    updated = BookItem(
        libis_code="LIBIS000000222222",
        data_source="ibiblioteka",
        title="Updated Title",
        year=2024,
        isbns=[{"isbn": "9780306406164", "type": "isbn13"}],
    )
    book_pipeline.process_item(updated)

    rows = test_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000222222")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "Updated Title"
    assert rows[0].year == 2024


def test_publisher_id_sticky_on_re_upsert(test_session, book_pipeline):
    """Once publisher is set, subsequent upserts don't overwrite it
    even if the incoming publisher differs (sticky publisher rule)."""
    first = BookItem(
        libis_code="LIBIS000000333333",
        data_source="ibiblioteka",
        title="Sticky Test",
        publisher="First Publisher",
        isbns=[],
    )
    book_pipeline.process_item(first)
    book = test_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000333333")
    ).scalar_one()
    first_pub_id = book.publisher_id
    assert first_pub_id is not None

    test_session.expire_all()
    second = BookItem(
        libis_code="LIBIS000000333333",
        data_source="ibiblioteka",
        title="Sticky Test",
        publisher="Second Publisher",
        isbns=[],
    )
    book_pipeline.process_item(second)
    book = test_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000333333")
    ).scalar_one()
    assert book.publisher_id == first_pub_id  # unchanged


def test_lookup_by_isbn_finds_existing_shop_inferred(test_session, book_pipeline):
    """LIBIS upgrade path: shop_inferred row with same ISBN is upgraded in place."""
    inferred = BookItem(
        libis_code=None,
        data_source="shop_inferred",
        title="Inferred",
        publisher="Shop Publisher",
        isbns=[{"isbn": "9780306406171", "type": "isbn13"}],
    )
    book_pipeline.process_item(inferred)

    test_session.expire_all()
    libis = BookItem(
        libis_code="LIBIS000000444444",
        data_source="ibiblioteka",
        title="LIBIS Title",
        publisher="LIBIS Publisher",
        isbns=[{"isbn": "9780306406171", "type": "isbn13"}],
    )
    book_pipeline.process_item(libis)

    rows = test_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000444444")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].data_source == "ibiblioteka"
    assert rows[0].title == "LIBIS Title"  # LIBIS overwrites
    pub = test_session.execute(
        select(Publisher).where(Publisher.id == rows[0].publisher_id)
    ).scalar_one()
    assert pub.name == "Shop Publisher"  # publisher sticky
```

- [ ] **Step 2D.2: Run tests, expect first to fail with `BookItem` not handled**

```bash
uv run pytest tests/integration/test_book_pipeline.py::test_bookitem_inserts_publishers_series_authors_isbns -v
```

Expected: FAIL — pipeline routes to PriceItem branch or no-op.

- [ ] **Step 2D.3: Add `_upsert_book` method and BookItem branch to `PostgresPipeline`**

In `book_scraper/pipelines.py`, find the `PostgresPipeline.process_item` method. Locate the existing `if isinstance(item, ShopBookItem):` / `elif isinstance(item, PriceItem):` chain. Add after the existing branches:

```python
        elif isinstance(item, BookItem):
            self._upsert_book(adapter)
            return item
```

Add the import at the top of the file:

```python
from book_scraper.items import BookItem, DiscoveredUrlItem, PriceItem, ShopBookItem
```

(Replace whatever the existing import line looks like — keep the items already imported and add `BookItem`.)

Now add the `_upsert_book` method to `PostgresPipeline`. Place it near the other `_upsert_*` methods on the class:

```python
    def _upsert_book(self, adapter: ItemAdapter) -> None:
        """Insert or update a Book row with its publisher, series, ISBNs, authors.

        Resolution order to find target books.id:
          1. By any incoming ISBN (normalized) — catches shop_inferred → ibiblioteka upgrade.
          2. By libis_code — for re-scrapes where ISBNs may have changed.
          3. Otherwise INSERT a new books row.

        See spec section "Spider and pipeline changes" for full rules.
        """
        from sqlalchemy import select
        from book_scraper.db.models import (
            Author, Book, BookAuthor, BookIsbn, Publisher, Series,
        )
        from book_scraper.isbn import normalize_isbn, to_isbn10, to_isbn13

        if self.session_factory is None:
            return  # tests bypassing open_spider — skip
        session = self.session_factory()
        try:
            # ── 1. Resolve target Book row ─────────────────────────────────
            incoming_isbns_raw = adapter.get("isbns") or []
            incoming_isbns_norm: list[str] = []
            for entry in incoming_isbns_raw:
                norm = normalize_isbn(entry.get("isbn") or "")
                if norm:
                    incoming_isbns_norm.append(norm)

            target: Book | None = None
            if incoming_isbns_norm:
                target = session.execute(
                    select(Book).join(BookIsbn).where(BookIsbn.isbn.in_(incoming_isbns_norm))
                    .limit(1)
                ).scalar_one_or_none()

            libis_code = adapter.get("libis_code")
            if target is None and libis_code:
                target = session.execute(
                    select(Book).where(Book.libis_code == libis_code)
                ).scalar_one_or_none()

            # ── 2. Upsert publisher ────────────────────────────────────────
            publisher_id: int | None = None
            pub_name = adapter.get("publisher")
            if pub_name:
                pub_name = pub_name.strip()
                pub = session.execute(
                    select(Publisher).where(Publisher.name == pub_name)
                ).scalar_one_or_none()
                if pub is None:
                    pub = Publisher(name=pub_name)
                    session.add(pub)
                    session.flush()
                publisher_id = pub.id

            # ── 3. Upsert series ───────────────────────────────────────────
            series_id: int | None = None
            ser_name = adapter.get("series")
            if ser_name:
                ser_name = ser_name.strip()
                ser = session.execute(
                    select(Series).where(Series.title == ser_name)
                ).scalar_one_or_none()
                if ser is None:
                    ser = Series(title=ser_name)
                    session.add(ser)
                    session.flush()
                series_id = ser.id

            # ── 4. Upsert Book row ─────────────────────────────────────────
            field_map = {
                "title": adapter.get("title"),
                "title_full": adapter.get("title_full"),
                "year": adapter.get("year"),
                "release_place": adapter.get("release_place"),
                "type": adapter.get("type"),
                "format": adapter.get("format"),
                "pages": adapter.get("pages"),
                "duration": adapter.get("duration"),
                "dimensions": adapter.get("dimensions"),
                "language": adapter.get("language"),
                "translated_from": adapter.get("translated_from"),
                "description": adapter.get("description"),
                "cover_url": adapter.get("cover_url"),
                "upcoming_release": adapter.get("upcoming_release", False),
                "udc_codes": adapter.get("udc_codes"),
                "subjects": adapter.get("subjects"),
                "audience": adapter.get("audience"),
                "libis_rating": adapter.get("libis_rating"),
                "libis_review_count": adapter.get("libis_review_count"),
                "series_id": series_id,
            }
            if target is None:
                target = Book(
                    data_source=adapter.get("data_source"),
                    libis_code=libis_code,
                    publisher_id=publisher_id,
                    **{k: v for k, v in field_map.items() if v is not None},
                )
                session.add(target)
                session.flush()
            else:
                # Upgrade path: shop_inferred → ibiblioteka
                if (target.data_source == "shop_inferred"
                        and adapter.get("data_source") == "ibiblioteka"):
                    target.data_source = "ibiblioteka"
                    target.libis_code = libis_code
                # Idempotent overwrite of all fields except publisher_id (sticky)
                for k, v in field_map.items():
                    if v is not None:
                        setattr(target, k, v)
                # Sticky publisher: only set when currently NULL
                if target.publisher_id is None and publisher_id is not None:
                    target.publisher_id = publisher_id
                # libis_code may be filling in from None on the upgrade path
                if libis_code and target.libis_code is None:
                    target.libis_code = libis_code

            # ── 5. ISBN rows: upsert with auto-fill of opposite form ───────
            seen: set[str] = set()
            for entry in incoming_isbns_raw:
                raw = entry.get("isbn") or ""
                norm = normalize_isbn(raw)
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                self._upsert_book_isbn(session, target.id, norm,
                                       entry.get("type") or "unknown")
                # Auto-fill opposite form
                opp = to_isbn10(norm) if len(norm) == 13 else to_isbn13(norm)
                if opp and opp != norm and opp not in seen:
                    seen.add(opp)
                    opp_type = "isbn10" if len(opp) == 10 else "isbn13"
                    self._upsert_book_isbn(session, target.id, opp, opp_type)

            # ── 6. Authors ─────────────────────────────────────────────────
            for entry in adapter.get("authors") or []:
                self._upsert_book_author(session, target.id, entry)

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _upsert_book_isbn(self, session, book_id: int, isbn: str, isbn_type: str) -> None:
        from sqlalchemy.dialects.postgresql import insert
        from book_scraper.db.models import BookIsbn

        stmt = insert(BookIsbn).values(book_id=book_id, isbn=isbn, isbn_type=isbn_type)
        stmt = stmt.on_conflict_do_update(
            index_elements=["isbn"],
            set_={"book_id": book_id, "isbn_type": isbn_type},
        )
        session.execute(stmt)

    def _upsert_book_author(self, session, book_id: int, entry: dict) -> None:
        """Resolve or create the canonical Author row, then ensure book_authors row."""
        from sqlalchemy import select
        from book_scraper.db.models import Author, BookAuthor

        name = (entry.get("name") or "").strip()
        if not name:
            return
        libis_code = entry.get("libis_code")
        normalized = name.lower().replace(",", "").strip()

        author: Author | None = None
        if libis_code:
            author = session.execute(
                select(Author).where(Author.libis_code == libis_code)
            ).scalar_one_or_none()
        if author is None:
            author = session.execute(
                select(Author).where(Author.normalized_name == normalized)
            ).scalar_one_or_none()
        if author is None:
            author = Author(
                name=name, normalized_name=normalized, libis_code=libis_code,
            )
            session.add(author)
            session.flush()
        elif libis_code and not author.libis_code:
            author.libis_code = libis_code

        role = entry.get("role") or "author"
        position = int(entry.get("position") or 0)
        existing = session.execute(
            select(BookAuthor).where(
                BookAuthor.book_id == book_id,
                BookAuthor.author_id == author.id,
                BookAuthor.role == role,
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(BookAuthor(
                book_id=book_id, author_id=author.id, role=role, position=position,
            ))
        else:
            existing.position = position
```

Verify `self.session_factory` exists on PostgresPipeline (it does — used by other upsert methods). If the variable name is different (e.g. `_session_factory`), match the local convention.

- [ ] **Step 2D.4: Run all Task 2 tests, expect pass**

```bash
uv run pytest tests/integration/test_book_pipeline.py tests/unit/test_isbn_converters.py -v
```

Expected: 11 PASSED.

- [ ] **Step 2D.5: Run full unit suite for regressions**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
```

Expected: same pass count as before this task.

- [ ] **Step 2D.6: Commit**

```bash
git add book_scraper/isbn.py book_scraper/items.py book_scraper/pipelines.py \
        tests/unit/test_isbn_converters.py tests/integration/test_book_pipeline.py
git commit -m "feat(pipeline): add BookItem and canonical book upsert path

Adds BookItem to items.py and a _upsert_book branch to PostgresPipeline.
Resolution order: incoming ISBN → libis_code → INSERT, supporting the
shop_inferred → ibiblioteka upgrade path. Publisher_id is sticky.

Also extends isbn.py with to_isbn10/to_isbn13 converters and modifies
ValidationPipeline to normalize stored ISBN values (was validated but
not normalized — shop_books.isbn currently mixes dashed and undashed)."
```

---

## Task 3: Restore ibiblioteka work, rewrite spider for BookItem

**Files:**
- Restore from stash: `book_scraper/spiders/ibiblioteka/`, `book_scraper/spiders/ibiblioteka_api_urls.py`, `book_scraper/spiders/discover.py`, `book_scraper/config_models.py`, `tests/fixtures/ibiblioteka/`, `tests/unit/test_ibiblioteka_parsers.py`, `config/shops/ibiblioteka.toml`
- Modify: `book_scraper/spiders/ibiblioteka/parsers.py` — emit `_emit_as: "book"` from `parse_product_page`
- Modify: `book_scraper/spiders/scan.py` — branch on `_emit_as` to build BookItem
- Modify: `book_scraper/spiders/discover.py` — remove the in-discover ShopBookItem emission for ibiblioteka

- [ ] **Step 3.1: Restore Tasks-1-2-compatible files from stash**

```bash
git checkout stash@{0} -- \
    book_scraper/spiders/ibiblioteka/ \
    book_scraper/spiders/ibiblioteka_api_urls.py \
    book_scraper/spiders/discover.py \
    book_scraper/config_models.py \
    config/shops/ibiblioteka.toml \
    tests/fixtures/ibiblioteka/ \
    tests/unit/test_ibiblioteka_parsers.py
```

- [ ] **Step 3.2: Verify restored files compile**

```bash
uv run python -c "from book_scraper.spiders.ibiblioteka import parsers; from book_scraper.spiders import discover, ibiblioteka_api_urls"
```

Expected: no output (clean import).

- [ ] **Step 3.3: Run existing ibiblioteka tests as a baseline**

```bash
uv run pytest tests/unit/test_ibiblioteka_parsers.py -v 2>&1 | tail -5
```

Expected: 24 PASSED.

- [ ] **Step 3.4: Wipe ibiblioteka shop data**

Run the backfill SQL from the spec (under "Backfill" section). Save as `scripts/wipe_ibiblioteka.sql`:

```bash
mkdir -p scripts/migrations
cat > scripts/migrations/wipe_ibiblioteka.sql <<'EOF'
BEGIN;

UPDATE scrape_runs
   SET status='failed', close_reason='superseded_by_canonical_layer'
 WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka')
   AND status IN ('running','paused');

DELETE FROM prices             WHERE shop_book_id IN (SELECT id FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));
DELETE FROM shop_book_changes  WHERE shop_book_id IN (SELECT id FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));

UPDATE discovered_urls SET shop_book_id = NULL
 WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');

UPDATE validation_issues SET shop_book_id = NULL
 WHERE shop_book_id IN (SELECT id FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));

DELETE FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');

DELETE FROM discovered_urls   WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM scrape_url_items  WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM scrape_run_events WHERE run_id IN (SELECT id FROM scrape_runs WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));
DELETE FROM validation_issues WHERE run_id IN (SELECT id FROM scrape_runs WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));
DELETE FROM cron_jobs         WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM scrape_runs       WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM shop_settings     WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM shops             WHERE name='ibiblioteka';

COMMIT;
EOF

docker exec -i book-scraper-postgres-1 psql -U postgres -d book_scraper < scripts/migrations/wipe_ibiblioteka.sql
```

Expected: a series of `DELETE n` and `UPDATE n` lines, ending with `COMMIT`.

- [ ] **Step 3.5: Verify wipe**

```bash
docker exec book-scraper-postgres-1 psql -U postgres -d book_scraper -c "SELECT count(*) FROM shop_books sb JOIN shops s ON s.id=sb.shop_id WHERE s.name='ibiblioteka'; SELECT count(*) FROM shops WHERE name='ibiblioteka';"
```

Expected: both counts = 0.

- [ ] **Step 3.6: Modify ibiblioteka `parse_product_page` to emit `_emit_as: "book"`**

In `book_scraper/spiders/ibiblioteka/parsers.py`, find `parse_product_page`. Currently it returns a flat dict shaped like `ProductPageResult` (with `is_book_product`, `title`, etc., suitable for `ShopBookItem`).

Replace its return value to a BookItem-shaped dict. Append at the bottom of the function (replacing the existing return):

```python
    # Emit as canonical Book, not ShopBook. The scan spider branches
    # on _emit_as and constructs BookItem instead of ShopBookItem.
    return {
        "_emit_as": "book",
        "is_book_product": True,  # keeps scan's "not a book" check happy
        "data_source": "ibiblioteka",
        "libis_code": raw.get("code"),
        "title": raw.get("title"),
        "title_full": raw.get("titleFull"),
        "year": _parse_year(raw.get("publicationDate")),
        "publisher": raw.get("publisher"),
        "series": raw.get("seriesView"),
        "release_place": raw.get("releasePlace"),
        "type": _infer_type(raw),
        "format": raw.get("publicationFormat"),
        "pages": _parse_pages(raw.get("allPhysicalAttributes")),
        "duration": _extract_duration(raw),
        "dimensions": _parse_dimensions(raw.get("allPhysicalAttributes")),
        "language": (raw.get("languages") or [{}])[0].get("code") if raw.get("languages") else None,
        "translated_from": [l.get("code") for l in (raw.get("translatedFromLanguages") or []) if l.get("code")] or None,
        "description": raw.get("summary"),
        "cover_url": _absolute_cover_url(raw.get("coverUrl")),
        "upcoming_release": bool(raw.get("upcomingRelease")),
        "udc_codes": raw.get("udcSubjectsCodes") or None,
        "subjects": raw.get("rubricSubjectView") or None,
        "audience": (raw.get("audience") or [{}])[0].get("nameLt") if raw.get("audience") else None,
        "libis_rating": raw.get("rateAverage"),
        "libis_review_count": raw.get("rateNumber"),
        "isbns": [{"isbn": isbn, "type": "isbn13" if len(isbn.replace("-", "")) == 13 else "isbn10"}
                  for isbn in (raw.get("isbn") or []) if isbn],
        "authors": _extract_authors(raw),
    }
```

Then write helper functions at the top of the same file (above `parse_product_page`):

```python
import re

_YEAR_RE = re.compile(r"\b(\d{4})\b")
_PAGES_RE = re.compile(r"(\d+)\s*p\.?")
_DIMENSIONS_RE = re.compile(r"(\d+)\s*cm")
_DURATION_RE = re.compile(r"\d+\s*val[.,]?\s*\d+\s*min")


def _parse_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    m = _YEAR_RE.search(date_str)
    return int(m.group(1)) if m else None


def _parse_pages(physical: str | None) -> int | None:
    if not physical:
        return None
    m = _PAGES_RE.search(physical)
    return int(m.group(1)) if m else None


def _parse_dimensions(physical: str | None) -> str | None:
    if not physical:
        return None
    m = _DIMENSIONS_RE.search(physical)
    return f"{m.group(1)} cm" if m else None


def _extract_duration(raw: dict) -> str | None:
    physical = raw.get("allPhysicalAttributes") or ""
    m = _DURATION_RE.search(physical)
    return m.group(0) if m else None


def _absolute_cover_url(rel: str | None) -> str | None:
    if not rel:
        return None
    if rel.startswith("http"):
        return rel
    return f"https://ibiblioteka.lt{rel}"


def _infer_type(raw: dict) -> str:
    fmt = (raw.get("publicationFormat") or "").upper()
    physical = (raw.get("allPhysicalAttributes") or "").lower()
    if fmt == "ELECTRONIC" and ("mp3" in physical or "audio" in physical):
        return "audio"
    if fmt == "ELECTRONIC":
        return "ebook"
    return "book"


_AUTHOR_ROLE_CODES = {
    "070": "author",
    "730": "translator",
    "550": "narrator",
    "440": "illustrator",
    "340": "editor",
    "220": "compiler",
}


def _extract_authors(raw: dict) -> list[dict]:
    """Extract authors with role + position from LIBIS persons / authorViews."""
    out: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    role_positions: dict[str, int] = {}

    # authorViews is the canonical primary-author list.
    for av in raw.get("authorViews") or []:
        name = av.get("value")
        code = av.get("code")
        if not name:
            continue
        key = ("author", code or name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        pos = role_positions.get("author", 0)
        out.append({"name": name, "libis_code": code, "role": "author", "position": pos})
        role_positions["author"] = pos + 1

    # persons array carries multi-role contributors.
    for person in raw.get("persons") or []:
        name = person.get("name")
        code = person.get("code")
        types = person.get("types") or []
        if not name:
            continue
        for t in types:
            role_code = t.get("code")
            role = _AUTHOR_ROLE_CODES.get(role_code)
            if not role:
                continue
            key = (role, code or name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            pos = role_positions.get(role, 0)
            out.append({"name": name, "libis_code": code, "role": role, "position": pos})
            role_positions[role] = pos + 1

    return out
```

Adjust existing imports if needed. Remove any conflicting helper definitions in the original file.

- [ ] **Step 3.7: Modify `ScanSpider.parse_product` to branch on `_emit_as`**

In `book_scraper/spiders/scan.py`, find the line that builds `ShopBookItem(...)` (around line 497). Just before it, add:

```python
        if data.get("_emit_as") == "book":
            from book_scraper.items import BookItem
            book = BookItem()
            for k in (
                "libis_code", "data_source", "title", "title_full", "year",
                "publisher", "series", "isbns", "authors", "release_place",
                "type", "format", "pages", "duration", "dimensions",
                "language", "translated_from", "description", "cover_url",
                "upcoming_release", "udc_codes", "subjects", "audience",
                "libis_rating", "libis_review_count",
            ):
                if k in data and data[k] is not None:
                    book[k] = data[k]
            self._mark_response(
                scrape_url_item_id,
                response_url=url,
                success=True,
                http_status=200,
                received_at=received_at,
                response_bytes=response_bytes,
                error_reason=None,
                dispatched_at=dispatched_at,
                url_type="product",
                request_delay_s=request_delay_s,
                delay_source=delay_source,
                retry_count=retry_count,
            )
            self._queue_url_status_update(
                discovered_url_id, http_status=200, url_type="product",
                book_score=data.get("book_score", 5),
                is_book_product=True,
                book_score_reasons=data.get("book_score_reasons", []),
            )
            yield book
            return
```

This branch handles the entire item emission and run-tracking for canonical books. The existing `ShopBookItem` construction below stays unchanged for shop scrapes.

- [ ] **Step 3.8: Modify ibiblioteka discover spider to drop in-discover ShopBookItem emission**

In `book_scraper/spiders/discover.py`, find `parse_ibiblioteka_page`. Currently it yields `ShopBookItem` rows directly (Task added during early development — see spec section "ibiblioteka spider rewrite"). Replace the body's `for product in products:` block so it ONLY yields `DiscoveredUrlItem` rows, removing the inline `ShopBookItem(...)` yield. The detail data now comes from the scan phase via `BookItem`.

Find the block:

```python
        for product in products:
            url = product.get("url")
            if not url:
                continue
            self._urls_processed += 1
            yield DiscoveredUrlItem(
                url=url, shop_name=self.shop_name, source="category"
            )
            if product.get("title"):
                yield ShopBookItem(
                    ...
                )
```

Replace with:

```python
        for product in products:
            url = product.get("url")
            if not url:
                continue
            self._urls_processed += 1
            yield DiscoveredUrlItem(
                url=url, shop_name=self.shop_name, source="category"
            )
            # No ShopBookItem here — ibiblioteka writes via the canonical
            # BookItem path during scan, not as commercial shop_books.
```

Also: the `parse_ibiblioteka_search_response` parser was extended to extract `title`/`year`/`publisher` from listings. That's now dead code. Reduce its return to URL-only:

```python
def parse_ibiblioteka_search_response(json_text: str) -> CategoryPageResult:
    """Parse a POST /detailed-search response.

    Returns one product per book with only the detail-endpoint URL.
    The scan spider's parse_product fetches each URL and emits a
    BookItem from the full LIBIS detail JSON.
    """
    try:
        data: dict[str, Any] = json.loads(json_text)
    except json.JSONDecodeError:
        return {"products": [], "total": None}

    items = data.get("results", {}).get("content") or []
    products = [
        {"url": f"https://ibiblioteka.lt/metis-api/bibliographic-records/public/{i['id']}"}
        for i in items if i.get("id")
    ]
    return {"products": products, "total": None}
```

Update the corresponding test in `tests/unit/test_ibiblioteka_parsers.py` to remove assertions about `title`/`year`/`publisher` on the search response (they used to come from listings; now they come from detail). Find:

```python
def test_parse_search_response_products_have_title_and_year():
```

and delete it.

- [ ] **Step 3.9: Update ibiblioteka detail-page parser tests to assert BookItem shape**

In `tests/unit/test_ibiblioteka_parsers.py`, the existing `test_parse_product_page_translated_book_*` tests check fields like `data["isbn"]`, `data["author"]`. With the new shape they're under `data["isbns"]` and `data["authors"]`. Rewrite each affected test to assert on the new structure. Example:

```python
def test_parse_product_page_translated_book_isbn():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["_emit_as"] == "book"
    assert data["data_source"] == "ibiblioteka"
    isbns = [i["isbn"] for i in data["isbns"]]
    assert "978-9955-717-09-6" in isbns or "9789955717096" in isbns


def test_parse_product_page_translated_book_authors():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    authors = data["authors"]
    translator_names = [a["name"] for a in authors if a["role"] == "translator"]
    assert any("Karpauskaitė" in n for n in translator_names)
    assert any("Kriščiūnas" in n for n in translator_names)


def test_parse_product_page_translated_book_year():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["year"] == 2024
```

Rewrite all 14 ibiblioteka parser-page tests to match the new shape. Audio fixtures: assert `data["type"] == "audio"`, `data["duration"]` is a non-empty string, `data["pages"] is None`, narrator authors present.

- [ ] **Step 3.10: Run ibiblioteka tests, expect pass**

```bash
uv run pytest tests/unit/test_ibiblioteka_parsers.py -v
```

Expected: all PASSED with the rewritten assertions. Count may differ from the prior 24 because of test additions/removals.

- [ ] **Step 3.11: Run full unit suite**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
```

Expected: no regressions in non-ibiblioteka tests.

- [ ] **Step 3.12: Commit**

```bash
git add book_scraper/spiders/ibiblioteka/ \
        book_scraper/spiders/ibiblioteka_api_urls.py \
        book_scraper/spiders/discover.py \
        book_scraper/spiders/scan.py \
        book_scraper/config_models.py \
        config/shops/ibiblioteka.toml \
        scripts/migrations/wipe_ibiblioteka.sql \
        tests/fixtures/ibiblioteka/ \
        tests/unit/test_ibiblioteka_parsers.py
git commit -m "feat(ibiblioteka): emit canonical BookItem from scan phase

The ibiblioteka spider previously wrote thin ShopBookItem rows. Wipes
those (28k rows) and rewrites the spider to emit BookItem instead.
parse_product_page returns a dict tagged '_emit_as: book' which scan.py
routes to BookItem instead of ShopBookItem. Discover yields URLs only.

Also retires the ibiblioteka 'shop' from the shops table — books from
LIBIS are now canonical records, not commercial listings."
```

---

## Task 4: Match phase — service, spider, enum, ISBN backfill, configs

**Files:**
- Create: `alembic/versions/<rev>_add_match_phase.py` (new migration)
- Create: `book_scraper/services/match.py`
- Create: `book_scraper/spiders/match.py`
- Create: `scripts/migrations/normalize_shop_isbns.sql`
- Modify: `book_scraper/db/models.py` — extend `scrape_phase_enum`
- Modify: `book_scraper/dashboard/routes/api.py` — accept `match` phase
- Modify: `book_scraper/config_models.py` — add `match.trust` per-shop
- Modify: each `config/shops/*.toml` — add `[match] trust = N`
- Test: `tests/integration/test_match_service.py` (new)

### Sub-task 4A: Add `match` to scrape_phase enum

- [ ] **Step 4A.1: Generate Alembic migration**

```bash
PYTHONPATH=. uv run alembic revision -m "add_match_phase_enum_value"
```

Expected: file created at `alembic/versions/<random>_add_match_phase_enum_value.py`.

- [ ] **Step 4A.2: Edit migration body**

Open the new file. Replace the empty `upgrade()` / `downgrade()` with:

```python
def upgrade() -> None:
    op.execute("ALTER TYPE scrape_phase ADD VALUE IF NOT EXISTS 'match'")


def downgrade() -> None:
    # Postgres does not support removing enum values; no-op.
    pass
```

- [ ] **Step 4A.3: Apply to main DB**

```bash
PYTHONPATH=. uv run alembic upgrade head
```

Expected: `Running upgrade <prev> -> <new>, add_match_phase_enum_value`.

- [ ] **Step 4A.4: Apply to test DB**

```bash
PYTHONPATH=. uv run alembic -x database_url=postgresql://postgres:postgres@localhost:5433/book_scraper_test upgrade head
```

Expected: same.

- [ ] **Step 4A.5: Update ORM enum literal**

In `book_scraper/db/models.py`, find:

```python
scrape_phase_enum = Enum(
    "discover_sitemap",
    "discover_categories",
    "discover_full_crawl",
    "discover_graphql",
    "discover_lupasearch",
    "discover_ibiblioteka_api",
    "scan",
    name="scrape_phase",
    create_type=False,
)
```

Add `"match"` before `"scan"`:

```python
    "discover_ibiblioteka_api",
    "match",
    "scan",
```

### Sub-task 4B: ISBN normalization back-fill SQL

- [ ] **Step 4B.1: Write the back-fill script**

```bash
cat > scripts/migrations/normalize_shop_isbns.sql <<'EOF'
-- One-shot: strip dashes and spaces from shop_books.isbn so the matcher
-- can join shop_books.isbn = book_isbns.isbn directly.
UPDATE shop_books
   SET isbn = REPLACE(REPLACE(isbn, '-', ''), ' ', '')
 WHERE isbn IS NOT NULL
   AND (isbn LIKE '%-%' OR isbn LIKE '% %');
EOF
```

- [ ] **Step 4B.2: Apply to main DB**

```bash
docker exec -i book-scraper-postgres-1 psql -U postgres -d book_scraper < scripts/migrations/normalize_shop_isbns.sql
```

Expected: `UPDATE n` where n is the number of dashed ISBNs. (Likely several thousand.)

- [ ] **Step 4B.3: Verify no dashed ISBNs remain**

```bash
docker exec book-scraper-postgres-1 psql -U postgres -d book_scraper -c "SELECT count(*) FROM shop_books WHERE isbn ~ '[- ]';"
```

Expected: `0`.

### Sub-task 4C: Per-shop match trust config

- [ ] **Step 4C.1: Extend `IbibliotekaApiConfig` and add `MatchConfig`**

In `book_scraper/config_models.py`, after `IbibliotekaApiConfig` class definition, add:

```python
class MatchConfig(BaseModel):
    """Per-shop match settings.

    `trust` ranks shops when synthesizing shop_inferred books — the
    highest-trust shop's title/year/format/etc. wins. Publisher is
    NOT trust-ranked: it sticks to the first writer.
    """

    trust: int = 50
```

Then find `class ShopConfig` and add `match` field:

```python
class ShopConfig(BaseModel):
    shop: ShopSection
    scraping: ScrapingConfig = ScrapingConfig()
    discover: DiscoverConfig = DiscoverConfig()
    scan: ScanConfig = ScanConfig()
    match: MatchConfig = MatchConfig()
    flaresolverr: FlaresolverrConfig | None = None
    attributes: AttributesConfig | None = None
```

- [ ] **Step 4C.2: Add `[match]` block to each shop TOML**

For each of `config/shops/{vaga,pegasas,humanitas,knygos,patogupirkti,almalittera}.toml`, append:

```toml

[match]
trust = 50
```

with these per-shop trust values:

| Shop | Trust |
|---|---|
| vaga | 100 |
| pegasas | 90 |
| humanitas | 70 |
| knygos | 60 |
| patogupirkti | 50 |
| almalittera | 50 |

- [ ] **Step 4C.3: Verify configs parse**

```bash
uv run python -c "
from book_scraper.config import load_shop_config
for s in ('vaga','pegasas','humanitas','knygos','patogupirkti','almalittera'):
    c = load_shop_config(s)
    print(s, '→ trust =', c.match.trust)
"
```

Expected: each shop with its configured trust value.

### Sub-task 4D: MatchService

- [ ] **Step 4D.1: Write failing integration test**

Create `tests/integration/test_match_service.py`:

```python
"""Integration tests for MatchService steps 1 (ISBN match) and 2 (author backfill)."""
from sqlalchemy import select

from book_scraper.db.models import (
    Author, Book, BookAuthor, BookIsbn, ShopAuthor, ShopBook, ShopBookAuthor, Shop,
)
from book_scraper.services.match import MatchService


def _make_shop(test_session, name: str) -> Shop:
    shop = Shop(name=name, base_url=f"https://{name}.lt")
    test_session.add(shop)
    test_session.flush()
    return shop


def _make_book(test_session, libis_code: str, isbn: str) -> Book:
    book = Book(data_source="ibiblioteka", libis_code=libis_code, title=f"T-{libis_code}")
    test_session.add(book)
    test_session.flush()
    test_session.add(BookIsbn(book_id=book.id, isbn=isbn, isbn_type="isbn13"))
    test_session.flush()
    return book


def test_step1_links_shop_book_by_isbn(test_session):
    shop = _make_shop(test_session, "vaga")
    book = _make_book(test_session, "LIBIS000000000001", "9780000000001")
    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/p/1", title="Same",
        isbn="9780000000001",
    )
    test_session.add(sb)
    test_session.commit()

    MatchService(test_session).run("vaga")

    test_session.expire_all()
    sb = test_session.execute(select(ShopBook).where(ShopBook.id == sb.id)).scalar_one()
    assert sb.book_id == book.id
    assert sb.match_status == "matched"
    assert sb.match_method == "isbn"


def test_step1_skips_already_matched(test_session):
    shop = _make_shop(test_session, "vaga")
    book = _make_book(test_session, "LIBIS000000000002", "9780000000002")
    other_book = _make_book(test_session, "LIBIS000000000003", "9780000000003")
    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/p/2", title="Same",
        isbn="9780000000002", book_id=other_book.id, match_status="matched",
    )
    test_session.add(sb)
    test_session.commit()

    MatchService(test_session).run("vaga")

    test_session.expire_all()
    sb = test_session.execute(select(ShopBook).where(ShopBook.id == sb.id)).scalar_one()
    assert sb.book_id == other_book.id  # not overwritten


def test_step1_only_affects_named_shop(test_session):
    shop_v = _make_shop(test_session, "vaga")
    shop_p = _make_shop(test_session, "pegasas")
    book = _make_book(test_session, "LIBIS000000000004", "9780000000004")
    sb_v = ShopBook(shop_id=shop_v.id, url="https://vaga.lt/p/3", title="V", isbn="9780000000004")
    sb_p = ShopBook(shop_id=shop_p.id, url="https://pegasas.lt/p/3", title="P", isbn="9780000000004")
    test_session.add_all([sb_v, sb_p])
    test_session.commit()

    MatchService(test_session).run("vaga")

    test_session.expire_all()
    assert test_session.execute(select(ShopBook).where(ShopBook.id == sb_v.id)).scalar_one().book_id == book.id
    assert test_session.execute(select(ShopBook).where(ShopBook.id == sb_p.id)).scalar_one().book_id is None


def test_step2_links_shop_authors_to_canonical(test_session):
    shop = _make_shop(test_session, "vaga")
    book = _make_book(test_session, "LIBIS000000000005", "9780000000005")
    canonical = Author(name="Mildažytė, Edita", normalized_name="mildazyte edita",
                       libis_code="LNB:Hd0;=BC")
    test_session.add(canonical)
    test_session.flush()
    test_session.add(BookAuthor(book_id=book.id, author_id=canonical.id, role="author", position=0))
    test_session.flush()

    sb = ShopBook(shop_id=shop.id, url="https://vaga.lt/p/4", title="Same", isbn="9780000000005")
    test_session.add(sb)
    test_session.flush()
    shop_author = ShopAuthor(name="Edita Mildažytė", normalized_name="edita mildažytė")
    test_session.add(shop_author)
    test_session.flush()
    test_session.add(ShopBookAuthor(shop_book_id=sb.id, author_id=shop_author.id, position=0))
    test_session.commit()

    MatchService(test_session).run("vaga")

    test_session.expire_all()
    sa = test_session.execute(select(ShopAuthor).where(ShopAuthor.id == shop_author.id)).scalar_one()
    assert sa.canonical_author_id == canonical.id


def test_step2_does_not_pair_translator_at_position_0(test_session):
    """If book_authors has both author@0 and translator@0, the join must
    only pair the shop_author (always primary) with author@0."""
    shop = _make_shop(test_session, "vaga")
    book = _make_book(test_session, "LIBIS000000000006", "9780000000006")
    primary = Author(name="A, A", normalized_name="a a")
    translator = Author(name="T, T", normalized_name="t t")
    test_session.add_all([primary, translator])
    test_session.flush()
    test_session.add_all([
        BookAuthor(book_id=book.id, author_id=primary.id, role="author", position=0),
        BookAuthor(book_id=book.id, author_id=translator.id, role="translator", position=0),
    ])
    sb = ShopBook(shop_id=shop.id, url="https://vaga.lt/p/5", title="X", isbn="9780000000006")
    test_session.add(sb)
    test_session.flush()
    shop_author = ShopAuthor(name="A A", normalized_name="a a (shop)")
    test_session.add(shop_author)
    test_session.flush()
    test_session.add(ShopBookAuthor(shop_book_id=sb.id, author_id=shop_author.id, position=0))
    test_session.commit()

    MatchService(test_session).run("vaga")

    test_session.expire_all()
    sa = test_session.execute(select(ShopAuthor).where(ShopAuthor.id == shop_author.id)).scalar_one()
    assert sa.canonical_author_id == primary.id
```

- [ ] **Step 4D.2: Run test, expect ImportError**

```bash
uv run pytest tests/integration/test_match_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'book_scraper.services.match'`.

- [ ] **Step 4D.3: Implement `MatchService` (steps 1 + 2 only)**

Create `book_scraper/services/match.py`:

```python
"""Match service: links shop_books to canonical books.

Phases (this commit implements 1 + 2; 3 + 4 added in Task 6):

  1. ISBN match — UPDATE shop_books.book_id where isbn matches.
  2. Author backfill — UPDATE shop_authors.canonical_author_id via
     the matched book's primary authors.
  3. shop_inferred synthesis (Task 6).
  4. shop_inferred upgrade — handled by the BookItem upsert path itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class MatchCounters:
    """Per-run match outcome counters. Returned by MatchService.run()."""
    books_linked: int = 0
    authors_linked: int = 0
    books_synthesized: int = 0

    @property
    def total_updates(self) -> int:
        """Sum suitable for scrape_runs.items_updated."""
        return self.books_linked + self.authors_linked


class MatchService:
    """Per-shop matcher. Steps are SQL-driven and idempotent."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self, shop_name: str) -> MatchCounters:
        """Run all match steps for one shop. Returns counters for the run row."""
        counters = MatchCounters()
        counters.books_linked = self._step1_isbn_match(shop_name)
        counters.authors_linked = self._step2_author_backfill(shop_name)
        return counters

    def _step1_isbn_match(self, shop_name: str) -> int:
        """Link shop_books.book_id by ISBN. Returns rows updated."""
        result = self.session.execute(
            text("""
                UPDATE shop_books sb
                   SET book_id = bi.book_id,
                       match_status = 'matched',
                       match_method = 'isbn'
                  FROM book_isbns bi, shops s
                 WHERE sb.shop_id = s.id
                   AND s.name = :shop_name
                   AND sb.isbn IS NOT NULL
                   AND REPLACE(REPLACE(sb.isbn, '-', ''), ' ', '') = bi.isbn
                   AND sb.book_id IS NULL
            """),
            {"shop_name": shop_name},
        )
        n = result.rowcount or 0
        logger.info("MatchService step 1: %d shop_books linked for %s", n, shop_name)
        return n

    def _step2_author_backfill(self, shop_name: str) -> int:
        """Link shop_authors.canonical_author_id where the underlying
        shop_book matched in step 1. role='author' filter prevents
        position=0 collisions with translator/narrator/illustrator.
        """
        result = self.session.execute(
            text("""
                UPDATE shop_authors sa
                   SET canonical_author_id = ba.author_id
                  FROM shop_book_authors sba
                  JOIN shop_books sb ON sb.id = sba.shop_book_id
                  JOIN book_authors ba ON ba.book_id = sb.book_id
                                      AND ba.position = sba.position
                                      AND ba.role = 'author'
                  JOIN shops s ON s.id = sb.shop_id
                 WHERE sa.id = sba.author_id
                   AND sa.canonical_author_id IS NULL
                   AND sb.match_status = 'matched'
                   AND s.name = :shop_name
            """),
            {"shop_name": shop_name},
        )
        n = result.rowcount or 0
        logger.info("MatchService step 2: %d shop_authors linked for %s", n, shop_name)
        return n
```

Create `book_scraper/services/__init__.py` if it doesn't exist (`touch`).

- [ ] **Step 4D.4: Run tests, expect pass**

```bash
uv run pytest tests/integration/test_match_service.py -v
```

Expected: 5 PASSED.

### Sub-task 4E: Match spider entrypoint

- [ ] **Step 4E.1: Write the spider**

Create `book_scraper/spiders/match.py`:

```python
"""Match phase spider.

Thin wrapper around MatchService so `scrapy crawl match -a shop=…` works
with the existing dashboard / cron launcher. No HTTP — calls the service
synchronously inside start() and closes immediately.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import scrapy

from book_scraper.config import load_shop_config
from book_scraper.db.repo import (
    create_scrape_run,
    finish_scrape_run,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory
from book_scraper.services.match import MatchService


class MatchSpider(scrapy.Spider):
    name = "match"
    custom_settings = {"ITEM_PIPELINES": {}}  # no items, no DB pipelines

    def __init__(self, shop: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not shop:
            raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
        self.shop_name = shop
        self.conf = load_shop_config(shop)

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )
        if not database_url:
            return  # tests / dry-run path
            yield  # unreachable

        session = get_session_factory(database_url)()
        try:
            shop = upsert_shop(session, self.shop_name, self.conf.shop.base_url)
            run = create_scrape_run(
                session, shop.id, "match",
                extra_payload={"shop": self.shop_name},
            )
            session.commit()
            run_id = run.id
        finally:
            session.close()

        # Do the work in a fresh session — keeps SQL UPDATEs in one txn.
        session = get_session_factory(database_url)()
        try:
            counters = MatchService(session).run(self.shop_name)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        # Mark run as completed
        session = get_session_factory(database_url)()
        try:
            finish_scrape_run(
                session, run_id, status="completed",
                items_updated=counters.total_updates,
            )
            session.commit()
        finally:
            session.close()

        return
        yield  # unreachable, satisfies AsyncGenerator typing
```

- [ ] **Step 4E.2: Verify spider can be loaded**

```bash
uv run scrapy list 2>&1 | grep -E "^(match|discover|scan)$"
```

Expected: `match`, `discover`, `scan` all listed.

- [ ] **Step 4E.3: Smoke test against test data**

```bash
docker exec -i book-scraper-postgres-1 psql -U postgres -d book_scraper -c "
INSERT INTO publishers (name) VALUES ('TestPub') ON CONFLICT DO NOTHING;
INSERT INTO books (data_source, libis_code, title) VALUES ('ibiblioteka', 'LIBIS_TEST_999', 'TestBook') ON CONFLICT (libis_code) DO NOTHING;
INSERT INTO book_isbns (book_id, isbn, isbn_type) SELECT id, '9780000099999', 'isbn13' FROM books WHERE libis_code='LIBIS_TEST_999' ON CONFLICT (isbn) DO NOTHING;
INSERT INTO shop_books (shop_id, url, title, isbn) SELECT id, 'http://test/x','x','9780000099999' FROM shops WHERE name='vaga' ON CONFLICT DO NOTHING;
"
docker exec book-scraper-scraper-1 scrapy crawl match -a shop=vaga 2>&1 | tail -20
docker exec book-scraper-postgres-1 psql -U postgres -d book_scraper -c "SELECT match_status, match_method FROM shop_books WHERE isbn='9780000099999';"
```

Expected: smoke run completes; the test row shows `match_status=matched, match_method=isbn`. Clean up the test row afterwards.

### Sub-task 4F: Wire match into dashboard + cron

- [ ] **Step 4F.1: Extend phase whitelist in `api.py`**

In `book_scraper/dashboard/routes/api.py`, find:

```python
    if req.phase not in ("scan", "discover"):
```

Replace with:

```python
    if req.phase not in ("scan", "discover", "match"):
```

Then in the `run_phase` derivation just below, leave the existing logic — `match` already passes through cleanly because it's not `discover` (no strategy suffix needed).

- [ ] **Step 4F.2: Update `_configured_discover_strategies` neighbor — add match phase visibility**

The existing dashboard "New Run" dialog already accepts `phase ∈ {discover, scan}`. The frontend lets the user pick `discover` or `scan`; for `match`, it just needs to be allowed. No frontend strategy work required because match has no strategy variant. Verify by checking that `req.strategy` is allowed to be empty for `match`:

In `api.py`, just below the phase whitelist, find the `run_phase` derivation:

```python
    run_phase = (
        f"discover_{req.strategy}"
        if req.phase == "discover" and req.strategy
        else req.phase
    )
```

This already works correctly: for `req.phase='match'`, `run_phase` becomes `"match"`.

- [ ] **Step 4F.3: Update generate_crontab.py to recognize `match` phase**

In `scripts/generate_crontab.py`, find the function that emits cron lines from `cron_jobs` rows. The phase comes from `cron_jobs.phase`. Verify the existing template line works for `match`:

```python
# Reference template (existing, in `_ENV_PREFIX`):
#   PYTHONPATH=. /app/.venv/bin/python -m scrapy crawl
# Plus row's phase + shop, e.g. "match -a shop=vaga"
```

Likely no change needed because the cron generator already concatenates phase + `-a shop=N`. Verify by adding a `match` cron row and re-running the generator:

```bash
docker exec book-scraper-postgres-1 psql -U postgres -d book_scraper -c "
INSERT INTO cron_jobs (shop_id, phase, schedule, enabled)
SELECT id, 'match', '0 * * * *', true FROM shops WHERE name='vaga'
ON CONFLICT DO NOTHING;
"
docker exec book-scraper-scraper-1 python /app/scripts/generate_crontab.py 2>&1 | grep "match"
```

Expected: a crontab line for `match -a shop=vaga`. If the generator hardcodes a phase whitelist, extend it.

- [ ] **Step 4F.4: Run dashboard route tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v 2>&1 | tail -5
```

Expected: 50 PASSED (no regression).

### Sub-task 4G: End-to-end smoke

- [ ] **Step 4G.1: Run all integration tests**

```bash
uv run pytest tests/integration/ -q 2>&1 | tail -5
```

Expected: pre-existing failures unchanged; new test_match_service.py and test_book_pipeline.py PASS.

- [ ] **Step 4G.2: Commit**

```bash
git add alembic/versions/*add_match_phase_enum_value.py \
        book_scraper/services/match.py book_scraper/services/__init__.py \
        book_scraper/spiders/match.py \
        book_scraper/db/models.py \
        book_scraper/dashboard/routes/api.py \
        book_scraper/config_models.py \
        config/shops/*.toml \
        scripts/migrations/normalize_shop_isbns.sql \
        tests/integration/test_match_service.py
git commit -m "feat(match): add match phase service, spider, enum, ISBN backfill

- Alembic migration adds 'match' to scrape_phase enum
- MatchService runs steps 1 (ISBN match) + 2 (author backfill).
  Step 2 filters book_authors.role='author' to avoid position=0
  collisions with translator/narrator at the same position.
- MatchSpider is a thin wrapper so 'scrapy crawl match -a shop=…' works
  with the existing dashboard + cron launcher unchanged.
- Per-shop trust ranking lives in config/shops/<shop>.toml [match] trust=N.
- One-shot SQL normalises existing dashed shop_books.isbn values so the
  matcher's join works.
- Dashboard /runs API accepts phase=match.

Steps 3 (shop_inferred synth) + 4 (LIBIS upgrade) ship in Task 6."
```

---

## Task 5: Books UI

**Files:**
- Create: `book_scraper/dashboard/static/hifi/hf-books.jsx` (new component file)
- Modify: `book_scraper/dashboard/static/hifi/index.html` — add script tag
- Modify: `book_scraper/dashboard/static/hifi/hf-shell.jsx` — sidebar link, route registration
- Modify: `book_scraper/dashboard/static/hifi/hf-shopbooks.jsx` — add canonical link badge
- Modify: `book_scraper/dashboard/routes/api.py` — `/api/books` and `/api/books/{id}`
- Modify: `book_scraper/dashboard/queries.py` — book query helpers
- Test: `tests/integration/test_books_api.py` (new)

### Sub-task 5A: API endpoints

- [ ] **Step 5A.1: Write failing test**

Create `tests/integration/test_books_api.py`:

```python
"""Integration tests for the canonical books API endpoints."""
from fastapi.testclient import TestClient


def test_books_list_returns_paginated_books(test_client: TestClient, test_session):
    from book_scraper.db.models import Author, Book, BookAuthor, BookIsbn, Publisher

    pub = Publisher(name="Šviesa")
    test_session.add(pub)
    test_session.flush()
    book = Book(
        data_source="ibiblioteka", libis_code="LIBIS000000800001",
        title="API Test Book", year=2024, publisher_id=pub.id,
    )
    test_session.add(book)
    test_session.flush()
    test_session.add(BookIsbn(book_id=book.id, isbn="9789876543099", isbn_type="isbn13"))
    author = Author(name="Foo, Bar", normalized_name="foo bar")
    test_session.add(author)
    test_session.flush()
    test_session.add(BookAuthor(book_id=book.id, author_id=author.id, role="author", position=0))
    test_session.commit()

    response = test_client.get("/api/books")
    assert response.status_code == 200
    data = response.json()
    assert "books" in data
    assert any(b["title"] == "API Test Book" for b in data["books"])
    found = next(b for b in data["books"] if b["title"] == "API Test Book")
    assert found["data_source"] == "ibiblioteka"
    assert found["year"] == 2024
    assert found["publisher"] == "Šviesa"
    assert "Foo, Bar" in (found.get("authors") or [])


def test_books_list_filter_by_data_source(test_client):
    response = test_client.get("/api/books?data_source=ibiblioteka")
    assert response.status_code == 200
    assert all(b["data_source"] == "ibiblioteka" for b in response.json()["books"])


def test_book_detail_returns_full_record_with_shops(test_session, test_client):
    from book_scraper.db.models import Book, BookIsbn, ShopBook, Shop

    book = Book(data_source="ibiblioteka", libis_code="LIBIS000000800002", title="Detail Test")
    test_session.add(book)
    test_session.flush()
    test_session.add(BookIsbn(book_id=book.id, isbn="9789876543098", isbn_type="isbn13"))
    shop = test_session.execute(
        __import__("sqlalchemy").select(Shop).where(Shop.name == "vaga")
    ).scalar_one_or_none()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt")
        test_session.add(shop)
        test_session.flush()
    test_session.add(ShopBook(
        shop_id=shop.id, url="https://vaga.lt/books/test", title="Detail Test",
        price="15.00", in_stock=True, book_id=book.id,
    ))
    test_session.commit()

    response = test_client.get(f"/api/books/{book.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Detail Test"
    assert data["libis_code"] == "LIBIS000000800002"
    assert any(s["shop"] == "vaga" for s in data["shops"])
    assert any(s["price"] == "15.00" for s in data["shops"])


def test_book_detail_404_for_unknown(test_client):
    response = test_client.get("/api/books/999999999")
    assert response.status_code == 404
```

- [ ] **Step 5A.2: Run test, expect 404 (route not registered)**

```bash
uv run pytest tests/integration/test_books_api.py::test_book_detail_404_for_unknown -v
```

Expected: response.status_code is 404 anyway because route doesn't exist — but test passes for the wrong reason. Run the others:

```bash
uv run pytest tests/integration/test_books_api.py -v 2>&1 | tail -10
```

Expected: 3 of 4 fail (the list/detail tests; the 404 test happens to pass).

- [ ] **Step 5A.3: Add query helpers in `queries.py`**

In `book_scraper/dashboard/queries.py`, add:

```python
def list_books(
    session: Session,
    *,
    data_source: str | None = None,
    has_isbn: bool | None = None,
    year: int | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    from sqlalchemy import func, select
    from book_scraper.db.models import (
        Author, Book, BookAuthor, BookIsbn, Publisher, ShopBook,
    )

    base = select(Book)
    if data_source:
        base = base.where(Book.data_source == data_source)
    if year is not None:
        base = base.where(Book.year == year)
    if has_isbn is True:
        base = base.where(Book.id.in_(select(BookIsbn.book_id).distinct()))
    elif has_isbn is False:
        base = base.where(~Book.id.in_(select(BookIsbn.book_id).distinct()))

    total = session.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()

    rows = session.execute(
        base.order_by(Book.created_at.desc())
            .limit(per_page).offset((page - 1) * per_page)
    ).scalars().all()

    out = []
    for b in rows:
        pub_name = None
        if b.publisher_id:
            pub_name = session.execute(
                select(Publisher.name).where(Publisher.id == b.publisher_id)
            ).scalar_one_or_none()
        authors = session.execute(
            select(Author.name)
              .join(BookAuthor)
              .where(BookAuthor.book_id == b.id, BookAuthor.role == "author")
              .order_by(BookAuthor.position)
        ).scalars().all()
        primary_isbn = session.execute(
            select(BookIsbn.isbn).where(BookIsbn.book_id == b.id).limit(1)
        ).scalar_one_or_none()
        shop_count = session.execute(
            select(func.count()).select_from(ShopBook).where(ShopBook.book_id == b.id)
        ).scalar_one()
        out.append({
            "id": b.id,
            "title": b.title,
            "year": b.year,
            "data_source": b.data_source,
            "libis_code": b.libis_code,
            "publisher": pub_name,
            "primary_isbn": primary_isbn,
            "authors": list(authors),
            "shop_count": shop_count,
        })

    return {
        "books": out, "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


def book_detail(session: Session, book_id: int) -> dict[str, Any] | None:
    from sqlalchemy import select
    from book_scraper.db.models import (
        Author, Book, BookAuthor, BookIsbn, Publisher, Series, Shop, ShopBook,
    )

    book = session.execute(select(Book).where(Book.id == book_id)).scalar_one_or_none()
    if book is None:
        return None

    pub_name = None
    if book.publisher_id:
        pub_name = session.execute(
            select(Publisher.name).where(Publisher.id == book.publisher_id)
        ).scalar_one_or_none()
    series_title = None
    if book.series_id:
        series_title = session.execute(
            select(Series.title).where(Series.id == book.series_id)
        ).scalar_one_or_none()

    isbns = session.execute(
        select(BookIsbn.isbn, BookIsbn.isbn_type).where(BookIsbn.book_id == book_id)
    ).all()
    authors = session.execute(
        select(Author.name, BookAuthor.role)
          .join(BookAuthor, BookAuthor.author_id == Author.id)
          .where(BookAuthor.book_id == book_id)
          .order_by(BookAuthor.role, BookAuthor.position)
    ).all()
    shops = session.execute(
        select(Shop.name, ShopBook.url, ShopBook.price, ShopBook.in_stock,
               ShopBook.last_seen_at)
          .join(ShopBook, ShopBook.shop_id == Shop.id)
          .where(ShopBook.book_id == book_id)
          .order_by(Shop.name)
    ).all()

    return {
        "id": book.id,
        "title": book.title,
        "title_full": book.title_full,
        "data_source": book.data_source,
        "libis_code": book.libis_code,
        "year": book.year,
        "publisher": pub_name,
        "series": series_title,
        "release_place": book.release_place,
        "type": book.type,
        "format": book.format,
        "pages": book.pages,
        "duration": book.duration,
        "dimensions": book.dimensions,
        "language": book.language,
        "translated_from": book.translated_from,
        "description": book.description,
        "cover_url": book.cover_url,
        "udc_codes": book.udc_codes,
        "subjects": book.subjects,
        "audience": book.audience,
        "isbns": [{"isbn": isbn, "type": typ} for isbn, typ in isbns],
        "authors": [{"name": n, "role": r} for n, r in authors],
        "shops": [
            {
                "shop": shop, "url": url,
                "price": str(price) if price is not None else None,
                "in_stock": in_stock,
                "last_seen_at": last_seen.isoformat() if last_seen else None,
            }
            for shop, url, price, in_stock, last_seen in shops
        ],
    }
```

- [ ] **Step 5A.4: Add API routes in `api.py`**

In `book_scraper/dashboard/routes/api.py`, add near the existing `@router.get("/shops")`:

```python
@router.get("/books")
def api_books(
    data_source: str | None = None,
    has_isbn: bool | None = None,
    year: int | None = None,
    page: int = 1,
    per_page: int = 50,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import list_books
    return list_books(
        session,
        data_source=data_source, has_isbn=has_isbn, year=year,
        page=page, per_page=per_page,
    )


@router.get("/books/{book_id}")
def api_book_detail(
    book_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import book_detail
    detail = book_detail(session, book_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return detail
```

- [ ] **Step 5A.5: Run tests, expect pass**

```bash
uv run pytest tests/integration/test_books_api.py -v
```

Expected: 4 PASSED.

### Sub-task 5B: Frontend Books page

- [ ] **Step 5B.1: Create `hf-books.jsx`**

Create `book_scraper/dashboard/static/hifi/hf-books.jsx`:

```jsx
// Books page — canonical book list + detail.

function HFBooks({ nav, goto }) {
  const HF = getHF();
  const shopNames = useShopNames();

  const _sp = new URLSearchParams(window.location.search);
  const [q, setQ]                 = React.useState(_sp.get('q') || '');
  const [dataSource, setDataSource] = React.useState(_sp.get('data_source') || 'all');
  const [hasIsbn, setHasIsbn]     = React.useState(_sp.get('has_isbn') || 'any');
  const [year, setYear]           = React.useState(_sp.get('year') || '');
  const [page, setPage]           = React.useState(1);
  const PER_PAGE = 50;

  const [data, setData] = React.useState({ books: [], total: 0, pages: 1 });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    const params = new URLSearchParams();
    if (dataSource !== 'all') params.set('data_source', dataSource);
    if (hasIsbn !== 'any')    params.set('has_isbn', hasIsbn === 'yes' ? 'true' : 'false');
    if (year)                 params.set('year', year);
    params.set('page', String(page));
    params.set('per_page', String(PER_PAGE));
    setLoading(true);
    fetch(`/api/books?${params}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); });
  }, [dataSource, hasIsbn, year, page]);

  // Client-side title filter on the loaded page (server search comes later).
  const visible = q
    ? data.books.filter(b => (b.title || '').toLowerCase().includes(q.toLowerCase()))
    : data.books;

  return (
    <HFShell {...nav} activePage="books" goto={goto}>
      <HFCard style={{marginBottom:'var(--hf-gap)', overflow:'visible'}} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:12, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)'}}>
            {data.total.toLocaleString()} books
          </span>
        </>}>
          <HFSearch placeholder="Title, ISBN…" width={260} value={q} onChange={setQ}/>
          <HFFilter label="Source"   value={dataSource} options={['all','ibiblioteka','shop_inferred','manual']} onChange={setDataSource}/>
          <HFFilter label="ISBN"     value={hasIsbn} options={['any','yes','no']} onChange={setHasIsbn} allLabel="any"/>
          <HFInput placeholder="Year (e.g. 2024)" width={100} value={year} onChange={setYear}/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {loading
          ? <HFTableSkeleton columns={['Title','Authors','Year','Publisher','ISBN','Source','Shops']} rows={6}/>
          : visible.length === 0
            ? <HFEmptyState
                title="No books"
                sub={data.total === 0
                  ? "No canonical books yet. Run an ibiblioteka discovery + scan to populate the catalogue."
                  : "No books match the current filters."}/>
            : <HFTable
                columns={[
                  {key:'title',     label:'Title',    flex:2},
                  {key:'authors',   label:'Authors'},
                  {key:'year',      label:'Year', width:60},
                  {key:'publisher', label:'Publisher'},
                  {key:'primary_isbn', label:'ISBN', width:140, mono:true},
                  {key:'data_source', label:'Source', width:120},
                  {key:'shop_count', label:'Shops', width:60},
                ]}
                rows={visible.map(b => ({
                  ...b,
                  authors: (b.authors || []).join('; '),
                  data_source: <DataSourceBadge value={b.data_source}/>,
                  shop_count: b.shop_count > 0
                    ? <HFPill tone="ok">{b.shop_count}</HFPill>
                    : <span style={{color:'var(--hf-ink4)'}}>—</span>,
                }))}
                onRowClick={r => goto('book-detail', { id: r.id })}/>
        }
      </HFCard>

      {data.pages > 1 && !loading &&
        <div style={{display:'flex', gap:8, marginTop:12, justifyContent:'center'}}>
          <HFButton size="sm" variant="subtle" disabled={page<=1} onClick={() => setPage(page-1)}>Prev</HFButton>
          <span style={{fontSize:12, alignSelf:'center', color:'var(--hf-ink4)'}}>
            Page {data.page} of {data.pages}
          </span>
          <HFButton size="sm" variant="subtle" disabled={page>=data.pages} onClick={() => setPage(page+1)}>Next</HFButton>
        </div>}
    </HFShell>
  );
}


function DataSourceBadge({ value }) {
  const map = {
    ibiblioteka: { label: 'National Library', tone: 'info' },
    shop_inferred: { label: 'From shops', tone: 'neutral' },
    manual: { label: 'Manual', tone: 'accent' },
  };
  const cfg = map[value] || { label: value, tone: 'neutral' };
  return <HFPill tone={cfg.tone} soft>{cfg.label}</HFPill>;
}


function HFBookDetail({ nav, goto, params }) {
  const HF = getHF();
  const [book, setBook] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    fetch(`/api/books/${params.id}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { setBook(d); setLoading(false); })
      .catch(s => { setError(s); setLoading(false); });
  }, [params.id]);

  if (loading) return <HFShell {...nav} goto={goto}><HFCard><HFSkeleton h={200}/></HFCard></HFShell>;
  if (error) return <HFShell {...nav} goto={goto}><HFCard><HFEmptyState title="Book not found" sub={`HTTP ${error}`}/></HFCard></HFShell>;

  const authorsByRole = {};
  for (const a of book.authors || []) {
    (authorsByRole[a.role] = authorsByRole[a.role] || []).push(a.name);
  }

  return (
    <HFShell {...nav} goto={goto} activePage="books">
      <HFCard padding={20}>
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start'}}>
          <div>
            <button onClick={() => goto('books')} style={{background:'none', border:'none', cursor:'pointer', color:'var(--hf-accent-ink)'}}>← Books</button>
            <h2 style={{margin:'8px 0', fontSize:24}}>{book.title}</h2>
            {book.title_full && book.title_full !== book.title &&
              <div style={{color:'var(--hf-ink3)', marginBottom:8}}>{book.title_full}</div>}
            {(authorsByRole.author || []).length > 0 &&
              <div>By {(authorsByRole.author).join(', ')}</div>}
            {(authorsByRole.translator || []).length > 0 &&
              <div style={{color:'var(--hf-ink3)'}}>Translated by {(authorsByRole.translator).join(', ')}</div>}
            <div style={{color:'var(--hf-ink3)', fontSize:13, marginTop:8}}>
              {[book.year, book.publisher, book.format, book.pages && `${book.pages} p.`, book.duration].filter(Boolean).join(' · ')}
            </div>
          </div>
          <DataSourceBadge value={book.data_source}/>
        </div>

        {book.cover_url &&
          <div style={{marginTop:16}}><img src={book.cover_url} alt={book.title} style={{maxHeight:240}}/></div>}

        <div style={{marginTop:16, fontSize:13, color:'var(--hf-ink3)'}}>
          {book.isbns?.length > 0 && <div>ISBN: {book.isbns.map(i => i.isbn).join(', ')}</div>}
          {book.libis_code && <div>LIBIS: {book.libis_code}</div>}
          {book.subjects?.length > 0 && <div>Subjects: {book.subjects.join(' · ')}</div>}
        </div>

        {book.description &&
          <div style={{marginTop:16, lineHeight:1.6}}>{book.description}</div>}
      </HFCard>

      <HFCard style={{marginTop:'var(--hf-gap)'}}>
        <h3 style={{margin:'12px 16px', fontSize:14, color:'var(--hf-ink3)'}}>Available at</h3>
        {(book.shops || []).length === 0
          ? <HFEmptyState title="Not sold anywhere we track" sub="No shop listings linked to this canonical book yet."/>
          : <HFTable
              columns={[
                {key:'shop',  label:'Shop'},
                {key:'price', label:'Price', width:80},
                {key:'in_stock', label:'Stock', width:80},
                {key:'url',  label:'URL',  flex:2},
                {key:'last_seen_at', label:'Last seen', width:140},
              ]}
              rows={book.shops.map(s => ({
                ...s,
                price: s.price ? `€${s.price}` : '—',
                in_stock: s.in_stock ? <HFPill tone="ok" soft>ok</HFPill>
                                     : <HFPill tone="warn" soft>out</HFPill>,
              }))}/>
        }
      </HFCard>
    </HFShell>
  );
}
```

- [ ] **Step 5B.2: Register routes + sidebar entry in `hf-shell.jsx`**

In `book_scraper/dashboard/static/hifi/hf-shell.jsx`, find the sidebar nav definition (search for `'shop-books'` or `'urls'`). Add a `'books'` entry placed before `'shop-books'` per UX feedback:

```jsx
{ id:'books',      label:'Books',      icon:HF_ICONS.books,    page:'books' },
```

If `HF_ICONS.books` doesn't exist, add a sensible icon export to `hf-icons.jsx` (look at how `HF_ICONS.shopBooks` is defined and copy the pattern).

Find the route registry / page renderer (`switch(page)` or similar). Add cases:

```jsx
case 'books':       return <HFBooks {...common}/>;
case 'book-detail': return <HFBookDetail {...common} params={params}/>;
```

- [ ] **Step 5B.3: Add script tag in `index.html`**

Find the existing `<script>` tags loading `hf-shopbooks.jsx` etc. Add:

```html
<script type="text/babel" src="/static/hifi/hf-books.jsx"></script>
```

Place it before `hf-shell.jsx` (which depends on it).

- [ ] **Step 5B.4: Add canonical-book badge on shop_book detail**

In `book_scraper/dashboard/static/hifi/hf-shopbooks.jsx`, find `HFShopBookDetail`. After fetching the shop_book record, render a small badge near the title:

```jsx
{shopBook.book_id ? (
  <HFPill tone="ok" soft style={{cursor:'pointer'}} onClick={() => goto('book-detail', {id: shopBook.book_id})}>
    Linked: {shopBook.book_title || `book #${shopBook.book_id}`} →
  </HFPill>
) : (
  <HFPill tone="neutral" soft>
    Unmatched
  </HFPill>
)}
```

For the `book_title` lookup: extend `/api/shop_books/{id}` (or whichever endpoint backs the detail) to join through `book_id` and return `book_title`. If that's invasive, leave it as `book #${id}` for now.

- [ ] **Step 5B.5: Rebuild and verify**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Then check:

```bash
curl -s http://localhost:8000/api/books?per_page=5 | python3 -m json.tool | head -20
```

Expected: a `books` array (likely empty until ibiblioteka runs).

- [ ] **Step 5B.6: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-books.jsx \
        book_scraper/dashboard/static/hifi/hf-shell.jsx \
        book_scraper/dashboard/static/hifi/hf-shopbooks.jsx \
        book_scraper/dashboard/static/hifi/index.html \
        book_scraper/dashboard/routes/api.py \
        book_scraper/dashboard/queries.py \
        tests/integration/test_books_api.py
git commit -m "feat(dashboard): add Books list + detail pages, link badge on shop_books

New /api/books and /api/books/{id} endpoints. New Books sidebar entry
(placed before Shop Books per UX). Detail page shows canonical record +
'Available at' table joining shop_books with prices. Shop_book detail
gets a 'Linked: <title>' or 'Unmatched' badge."
```

---

## Task 6: shop_inferred synthesis + LIBIS upgrade

**Files:**
- Modify: `book_scraper/services/match.py` — add steps 3 + 4
- Test: extend `tests/integration/test_match_service.py`

The LIBIS upgrade path (step 4) is already covered by the BookItem upsert from Task 2 (it resolves by ISBN first, finds the shop_inferred row, upgrades in place). This task adds step 3 (synthesis) only and a regression test for step 4.

- [ ] **Step 6.1: Write failing test for shop_inferred synthesis**

Append to `tests/integration/test_match_service.py`:

```python
def test_step3_synthesizes_shop_inferred_after_two_shops(test_session):
    """Two shops carry the same ISBN, no canonical match → create shop_inferred book."""
    from book_scraper.config_models import MatchConfig

    sv = _make_shop(test_session, "vaga")
    sp = _make_shop(test_session, "pegasas")
    isbn = "9780000000007"

    sb_v = ShopBook(
        shop_id=sv.id, url="https://vaga.lt/p/sa", title="Vaga Title",
        isbn=isbn, publisher="Vaga Publisher", year=2024,
    )
    sb_p = ShopBook(
        shop_id=sp.id, url="https://pegasas.lt/p/sa", title="Pegasas Title",
        isbn=isbn, publisher="Pegasas Publisher", year=2024,
    )
    test_session.add_all([sb_v, sb_p])
    test_session.commit()

    svc = MatchService(test_session)
    svc.shop_trust = {"vaga": 100, "pegasas": 90}
    svc.run("vaga")

    test_session.expire_all()
    rows = test_session.execute(
        select(Book).join(BookIsbn).where(BookIsbn.isbn == isbn)
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].data_source == "shop_inferred"
    assert rows[0].title == "Vaga Title"  # higher trust


def test_step3_publisher_is_first_writer_not_highest_trust(test_session):
    """Sticky publisher: the FIRST shop's publisher persists even when
    a higher-trust shop also has the ISBN."""
    sp = _make_shop(test_session, "pegasas")  # lower trust, but inserted first
    sv = _make_shop(test_session, "vaga")
    isbn = "9780000000008"

    # pegasas first → its publisher should stick
    import datetime
    sb_p = ShopBook(
        shop_id=sp.id, url="https://pegasas.lt/p/sb", title="P",
        isbn=isbn, publisher="Pegasas Publisher",
        first_seen_at=datetime.datetime(2024, 1, 1),
    )
    test_session.add(sb_p)
    test_session.commit()
    sb_v = ShopBook(
        shop_id=sv.id, url="https://vaga.lt/p/sb", title="V",
        isbn=isbn, publisher="Vaga Publisher",
        first_seen_at=datetime.datetime(2024, 6, 1),
    )
    test_session.add(sb_v)
    test_session.commit()

    svc = MatchService(test_session)
    svc.shop_trust = {"vaga": 100, "pegasas": 90}
    svc.run("vaga")

    test_session.expire_all()
    book = test_session.execute(
        select(Book).join(BookIsbn).where(BookIsbn.isbn == isbn)
    ).scalar_one()
    pub = test_session.execute(
        select(Publisher).where(Publisher.id == book.publisher_id)
    ).scalar_one()
    assert pub.name == "Pegasas Publisher"  # first writer wins
```

- [ ] **Step 6.2: Run tests, expect failure**

```bash
uv run pytest tests/integration/test_match_service.py::test_step3_synthesizes_shop_inferred_after_two_shops -v
```

Expected: FAIL — no `Book` row exists.

- [ ] **Step 6.3: Add steps 3 + 4 to MatchService**

In `book_scraper/services/match.py`, modify the class:

```python
    def __init__(self, session: Session) -> None:
        self.session = session
        self.shop_trust = self._load_shop_trust()  # {shop_name: int}

    @staticmethod
    def _load_shop_trust() -> dict[str, int]:
        """Load per-shop trust from config/shops/*.toml [match] trust=N.

        Broken / missing TOMLs are logged but don't kill the matcher —
        a single shop with an unreadable config falls back to default
        trust (50) elsewhere; the rest of the catalogue still matches.
        """
        import logging
        from pathlib import Path
        from book_scraper.config import load_shop_config

        logger = logging.getLogger(__name__)
        out: dict[str, int] = {}
        cfg_dir = Path("config/shops")
        if not cfg_dir.exists():
            return out
        for toml in cfg_dir.glob("*.toml"):
            try:
                cfg = load_shop_config(toml.stem)
                out[toml.stem] = cfg.match.trust
            except FileNotFoundError:
                continue
            except Exception:
                logger.exception("Failed to load match.trust from %s", toml)
                continue
        return out

    def run(self, shop_name: str) -> "MatchCounters":
        counters = MatchCounters()
        counters.books_linked = self._step1_isbn_match(shop_name)
        counters.authors_linked = self._step2_author_backfill(shop_name)
        counters.books_synthesized = self._step3_shop_inferred_synthesis()
        # Step 4 (LIBIS upgrade) is performed inside _upsert_book; nothing here.
        # Re-run step 1 so newly synthesised books pick up matches.
        counters.books_linked += self._step1_isbn_match(shop_name)
        return counters

    def _step3_shop_inferred_synthesis(self) -> int:
        """Find ISBNs on ≥2 shops with no canonical book; create shop_inferred rows."""
        from sqlalchemy import select
        from book_scraper.db.models import (
            Author, Book, BookAuthor, BookIsbn, Publisher, ShopBook, Shop,
        )

        # Candidate ISBNs: ≥2 distinct shops, not yet in book_isbns.
        rows = self.session.execute(text("""
            SELECT REPLACE(REPLACE(sb.isbn, '-', ''), ' ', '') AS isbn,
                   COUNT(DISTINCT sb.shop_id) AS shop_count
              FROM shop_books sb
             WHERE sb.isbn IS NOT NULL
               AND sb.book_id IS NULL
             GROUP BY 1
            HAVING COUNT(DISTINCT sb.shop_id) >= 2
               AND NOT EXISTS (SELECT 1 FROM book_isbns bi WHERE bi.isbn = REPLACE(REPLACE(sb.isbn, '-', ''), ' ', ''))
        """)).all()

        synthesised = 0
        for isbn_norm, _shop_count in rows:
            self._synthesise_one(isbn_norm)
            synthesised += 1

        logger.info("MatchService step 3: %d shop_inferred books synthesised", synthesised)
        return synthesised

    def _synthesise_one(self, isbn_norm: str) -> None:
        """Build a shop_inferred Book from the highest-trust shop's data,
        with the FIRST writer's publisher (sticky)."""
        from datetime import datetime, timezone
        from sqlalchemy import select
        from book_scraper.db.models import Book, BookIsbn, Publisher, ShopBook, Shop

        # Sentinel for NULL first_seen_at — sorts NULL rows last so they
        # don't accidentally win the "first writer" tiebreak.
        _FAR_FUTURE = datetime(9999, 1, 1, tzinfo=timezone.utc)

        # All shop_books carrying this ISBN, ordered by trust desc, then first_seen asc.
        candidates = self.session.execute(text("""
            SELECT sb.id, sb.shop_id, s.name AS shop_name, sb.title, sb.year,
                   sb.format, sb.type, sb.publisher, sb.first_seen_at
              FROM shop_books sb
              JOIN shops s ON s.id = sb.shop_id
             WHERE REPLACE(REPLACE(sb.isbn, '-', ''), ' ', '') = :isbn
        """), {"isbn": isbn_norm}).all()

        if len(candidates) < 2:
            return

        # Highest-trust shop wins for most fields.
        scored = sorted(
            candidates,
            key=lambda r: (-(self.shop_trust.get(r.shop_name, 50)),),
        )
        winner = scored[0]

        # First-writer wins for publisher. NULL first_seen_at -> sorts last.
        first_with_pub = sorted(
            [c for c in candidates if c.publisher],
            key=lambda r: r.first_seen_at or _FAR_FUTURE,
        )
        publisher_name = first_with_pub[0].publisher if first_with_pub else None

        publisher_id = None
        if publisher_name:
            pub = self.session.execute(
                select(Publisher).where(Publisher.name == publisher_name)
            ).scalar_one_or_none()
            if pub is None:
                pub = Publisher(name=publisher_name)
                self.session.add(pub)
                self.session.flush()
            publisher_id = pub.id

        book = Book(
            data_source="shop_inferred",
            libis_code=None,
            title=winner.title or "(untitled)",
            year=winner.year,
            publisher_id=publisher_id,
            type=winner.type,
            format=winner.format,
        )
        self.session.add(book)
        self.session.flush()
        self.session.add(BookIsbn(book_id=book.id, isbn=isbn_norm, isbn_type="isbn13" if len(isbn_norm) == 13 else "isbn10"))
        self.session.flush()
```

- [ ] **Step 6.4: Run synthesis tests, expect pass**

```bash
uv run pytest tests/integration/test_match_service.py -v
```

Expected: 7 PASSED (5 from Task 4 + 2 new).

- [ ] **Step 6.5: Add regression test for LIBIS upgrade preserving sticky publisher**

Append to `tests/integration/test_book_pipeline.py`:

```python
def test_libis_upgrade_preserves_inferred_publisher(test_session, book_pipeline):
    """A shop_inferred book gets upgraded to ibiblioteka by ISBN; LIBIS
    overwrites everything except publisher_id (sticky)."""
    inferred = BookItem(
        libis_code=None,
        data_source="shop_inferred",
        title="Inferred Title",
        publisher="Shop Publisher",
        isbns=[{"isbn": "9780000000099", "type": "isbn13"}],
    )
    book_pipeline.process_item(inferred)

    test_session.expire_all()
    upgrade = BookItem(
        libis_code="LIBIS000000999900",
        data_source="ibiblioteka",
        title="LIBIS Title",
        publisher="LIBIS Publisher",  # different — must NOT overwrite
        isbns=[{"isbn": "9780000000099", "type": "isbn13"}],
    )
    book_pipeline.process_item(upgrade)

    rows = test_session.execute(
        select(Book).where(Book.libis_code == "LIBIS000000999900")
    ).scalars().all()
    assert len(rows) == 1
    book = rows[0]
    assert book.data_source == "ibiblioteka"
    assert book.title == "LIBIS Title"
    pub = test_session.execute(
        select(Publisher).where(Publisher.id == book.publisher_id)
    ).scalar_one()
    assert pub.name == "Shop Publisher"  # sticky
```

- [ ] **Step 6.6: Run all tests**

```bash
uv run pytest tests/integration/test_book_pipeline.py tests/integration/test_match_service.py -v
```

Expected: all PASSED.

- [ ] **Step 6.7: Commit**

```bash
git add book_scraper/services/match.py \
        tests/integration/test_match_service.py \
        tests/integration/test_book_pipeline.py
git commit -m "feat(match): add shop_inferred synthesis + LIBIS upgrade regression test

Step 3: identifies ISBNs on ≥2 distinct shops with no canonical match
and synthesises shop_inferred Book rows. Highest-trust shop's title /
year / format wins. Publisher is sticky to the FIRST writer (sorted by
first_seen_at), regardless of trust.

Step 4 (LIBIS upgrade) was already implemented in the BookItem upsert
path (Task 2's resolution-by-ISBN-first). This commit adds a regression
test confirming sticky publisher survives the upgrade."
```

---

## Final verification

- [ ] **Step F.1: Full test suite**

```bash
uv run pytest tests/ -q 2>&1 | tail -5
```

Expected: same number of pre-existing failures as before this plan started (none introduced).

- [ ] **Step F.2: Smoke tests on dashboard**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -q 2>&1 | tail -3
```

Expected: all 50 PASSED.

- [ ] **Step F.3: End-to-end ibiblioteka run (small)**

```bash
docker compose up -d
docker exec book-scraper-scraper-1 scrapy crawl discover -a shop=ibiblioteka -a strategy=ibiblioteka_api -a max_pages=2 2>&1 | tail -10
docker exec book-scraper-scraper-1 scrapy crawl scan -a shop=ibiblioteka -a max_urls=10 2>&1 | tail -10
docker exec book-scraper-postgres-1 psql -U postgres -d book_scraper -c "SELECT data_source, count(*) FROM books GROUP BY 1; SELECT count(*) FROM book_isbns; SELECT count(*) FROM book_authors;"
```

Expected: small `books` count (~10), some `book_isbns` and `book_authors`.

- [ ] **Step F.4: End-to-end match run**

```bash
docker exec book-scraper-scraper-1 scrapy crawl match -a shop=vaga 2>&1 | tail -5
docker exec book-scraper-postgres-1 psql -U postgres -d book_scraper -c "SELECT count(*) FROM shop_books WHERE book_id IS NOT NULL;"
```

Expected: positive count of linked shop_books.

- [ ] **Step F.5: Visual check of Books page**

Open `http://localhost:8000`, navigate to Books in the sidebar. Verify:
- Books page loads
- Filters work (data_source, year)
- Clicking a book opens detail
- Detail page shows the canonical record + linked shops (if any)
- Shop book detail page shows "Linked: …" badge or "Unmatched"

---

## Self-review

**1. Spec coverage:** Every section of the spec has at least one task that implements it.
- Schema (Section "Schema") → Task 1
- Spider rewrite (Section "Spider and pipeline changes") → Tasks 2 + 3
- Match phase (Section "Match phase") → Task 4 (steps 1+2) + Task 6 (steps 3+4)
- UI (Section "UI changes") → Task 5
- Backfill (Section "Backfill") → Step 3.4
- Implementation order (Section "Implementation order") → mirrored as Tasks 1–6

**2. Placeholder scan:** No "TBD", no "implement later", no "similar to Task N" without code, no "add appropriate error handling" without specifics.

**3. Type consistency:**
- `Author`, `Book`, `BookIsbn`, `BookAuthor`, `Publisher`, `Series` ORM classes used consistently across Tasks 1, 2, 4, 5, 6
- `BookItem` field names match between definition (Task 2C), upsert reader (Task 2D), parser writer (Task 3), scan branch (Task 3)
- `_upsert_book`, `_upsert_book_isbn`, `_upsert_book_author` are defined in Task 2D and used nowhere else (no naming drift)
- `MatchService.run(shop_name)` signature consistent across Tasks 4D and 6
- `MatchService.shop_trust` is `dict[str, int]` consistently

**4. Worktree handling:** Task 0 stashes existing work, Task 3 selectively restores. Engineer is told what's modified vs new.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-08-canonical-books-layer.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
