# Books + Schedules Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt the new canonical Book detail page (`HFBook`), add server-side smart search to `/api/books`, wire schedule deletion (with strict 409 block on chained dependents), and validate cron expressions at the API edge.

**Architecture:** Backend changes are additive to existing FastAPI routes in `book_scraper/dashboard/routes/api.py` and the `list_books` query in `book_scraper/dashboard/queries.py`. Frontend changes swap one component on the `/books/:id` route, polish that component, replace a client-side filter with a server-side query parameter, and add a delete flow to the schedule detail page. No DB migrations.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 / PostgreSQL — `croniter` (already a dep, `>=6.0`). Frontend: React 18 via Babel CDN (no build step), tokens + `HFModal` + `HFToastHost` already in place.

**Spec:** `docs/superpowers/specs/2026-05-09-books-schedules-polish-design.md`

---

## Phase A — Backend (TDD)

### Task 1: `_validate_cron` helper + unit tests

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py` (add helper near other private helpers)
- Test: `tests/unit/test_cron_validation.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cron_validation.py`:

```python
"""Unit tests for the _validate_cron helper."""
import pytest
from fastapi import HTTPException

from book_scraper.dashboard.routes.api import _validate_cron


def test_valid_5field_passes():
    _validate_cron("0 2 * * *")
    _validate_cron("*/5 * * * *")
    _validate_cron("0 0 1 1 *")


def test_invalid_syntax_raises_422():
    with pytest.raises(HTTPException) as exc:
        _validate_cron("not a cron")
    assert exc.value.status_code == 422
    assert "Invalid cron expression" in exc.value.detail


def test_six_field_rejected():
    """6-field (with seconds) is rejected — we want strict 5-field."""
    with pytest.raises(HTTPException) as exc:
        _validate_cron("0 0 2 * * *")
    assert exc.value.status_code == 422


def test_seven_field_rejected():
    with pytest.raises(HTTPException) as exc:
        _validate_cron("0 0 2 * * * 2025")
    assert exc.value.status_code == 422


def test_extra_whitespace_normalized():
    """Leading/trailing whitespace and double spaces should still parse."""
    _validate_cron("  0 2 * * *  ")
    _validate_cron("0  2  *  *  *")


def test_empty_string_rejected():
    with pytest.raises(HTTPException) as exc:
        _validate_cron("")
    assert exc.value.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cron_validation.py -v
```

Expected: ImportError or AttributeError — `_validate_cron` does not yet exist.

- [ ] **Step 3: Add the helper**

Open `book_scraper/dashboard/routes/api.py`. The existing module already imports `croniter` locally inside two functions (lines 1926 and 1988) using `from croniter import croniter  # type: ignore[import-untyped]`. Match that convention — import inside the helper, do **not** add a top-level import (mypy is strict in this project).

Near the other private helpers in the file (above the cron route block, e.g. just before `def _chain_would_create_cycle` around line 2161), add:

```python
def _validate_cron(expression: str) -> None:
    """Reject cron expressions that aren't valid 5-field cron.

    croniter.is_valid is permissive about 6/7-field forms; we want strict
    5-field so the value round-trips cleanly through scripts/generate_crontab.py.
    """
    from croniter import croniter  # type: ignore[import-untyped]

    parts = expression.strip().split()
    if len(parts) != 5 or not croniter.is_valid(expression.strip()):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid cron expression: {expression!r} (expected 5 fields)",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cron_validation.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```
git add book_scraper/dashboard/routes/api.py tests/unit/test_cron_validation.py
git commit -m "feat(api): add _validate_cron helper (5-field strict)"
```

---

### Task 2: Wire `_validate_cron` into `POST /api/cron`

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py` (`api_cron_create` around line 2192)
- Test: `tests/integration/test_dashboard_routes.py` (append to file)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_dashboard_routes.py`:

```python
def test_cron_create_rejects_invalid_expression(client, db_session):
    from book_scraper.db.repo import upsert_shop

    upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    resp = client.post(
        "/api/cron",
        json={
            "shop": "vaga",
            "phase": "discover",
            "strategy": "sitemap",
            "cron_expression": "not a cron",
        },
    )
    assert resp.status_code == 422
    assert "Invalid cron expression" in resp.json()["detail"]


def test_cron_create_rejects_six_field(client, db_session):
    from book_scraper.db.repo import upsert_shop

    upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    resp = client.post(
        "/api/cron",
        json={
            "shop": "vaga",
            "phase": "discover",
            "strategy": "sitemap",
            "cron_expression": "0 0 2 * * *",
        },
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/integration/test_dashboard_routes.py::test_cron_create_rejects_invalid_expression tests/integration/test_dashboard_routes.py::test_cron_create_rejects_six_field -v
```

Expected: FAIL — both currently return 200 (no validation).

- [ ] **Step 3: Wire validation into `api_cron_create`**

In `book_scraper/dashboard/routes/api.py`, locate `api_cron_create` (around line 2192). Add a single line right after the `phase` check:

```python
@router.post("/cron")
def api_cron_create(
    body: _CronJobBody, session: Session = Depends(get_db)
) -> dict[str, Any]:
    shop = get_shop_by_name(session, body.shop)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    if body.phase not in ("discover", "scan"):
        raise HTTPException(
            status_code=422, detail="phase must be 'discover' or 'scan'"
        )
    _validate_cron(body.cron_expression)  # <-- ADD THIS LINE
    if body.chain_to_id is not None:
        ...
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/integration/test_dashboard_routes.py::test_cron_create_rejects_invalid_expression tests/integration/test_dashboard_routes.py::test_cron_create_rejects_six_field -v
```

Expected: 2 passed.

Then run the existing cron tests to confirm no regression:

```
uv run pytest tests/integration/test_dashboard_routes.py -k cron -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add book_scraper/dashboard/routes/api.py tests/integration/test_dashboard_routes.py
git commit -m "feat(api): validate cron expression on POST /api/cron"
```

---

### Task 3: Wire `_validate_cron` into `PATCH /api/cron/{id}`

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py` (`api_cron_update` around line 2234)
- Test: `tests/integration/test_dashboard_routes.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_dashboard_routes.py`:

```python
def test_cron_update_rejects_invalid_expression(client, db_session):
    from book_scraper.db.repo import create_cron_job, get_cron_job, upsert_shop

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *",
    )
    db_session.commit()

    resp = client.patch(
        f"/api/cron/{job.id}",
        json={"cron_expression": "definitely not cron"},
    )
    assert resp.status_code == 422

    db_session.expire_all()
    saved = get_cron_job(db_session, job.id)
    assert saved.cron_expression == "0 2 * * *"  # unchanged


def test_cron_update_without_cron_expression_skips_validation(client, db_session):
    """PATCH should not require cron_expression — only validate when present."""
    from book_scraper.db.repo import create_cron_job, upsert_shop

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *",
    )
    db_session.commit()

    resp = client.patch(f"/api/cron/{job.id}", json={"strategy": "categories"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify the first fails**

```
uv run pytest tests/integration/test_dashboard_routes.py::test_cron_update_rejects_invalid_expression -v
```

Expected: FAIL — currently returns 200 with the bad value persisted.

- [ ] **Step 3: Wire validation into `api_cron_update`**

In `book_scraper/dashboard/routes/api.py`, locate `api_cron_update` (around line 2234). Add validation conditioned on `body.cron_expression is not None`:

```python
@router.patch("/cron/{job_id}")
def api_cron_update(
    job_id: int, body: _CronJobPatch, session: Session = Depends(get_db)
) -> dict[str, Any]:
    job = get_cron_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if body.cron_expression is not None:
        _validate_cron(body.cron_expression)  # <-- ADD THIS BLOCK
    # ... rest unchanged
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/integration/test_dashboard_routes.py::test_cron_update_rejects_invalid_expression tests/integration/test_dashboard_routes.py::test_cron_update_without_cron_expression_skips_validation -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add book_scraper/dashboard/routes/api.py tests/integration/test_dashboard_routes.py
git commit -m "feat(api): validate cron expression on PATCH /api/cron/{id}"
```

---

### Task 4: Dependent check on `DELETE /api/cron/{id}`

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py` (`api_cron_delete` around line 2273)
- Test: `tests/integration/test_dashboard_routes.py` (append)

- [ ] **Step 1: Read the existing `api_cron_delete`**

```
grep -n -A 12 "def api_cron_delete" book_scraper/dashboard/routes/api.py
```

Note its current shape so the modification preserves return contract.

- [ ] **Step 2: Write the failing tests**

Append to `tests/integration/test_dashboard_routes.py`:

```python
def test_cron_delete_with_dependents_returns_409(client, db_session):
    from book_scraper.db.repo import create_cron_job, get_cron_job, upsert_shop

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    parent = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *",
    )
    db_session.flush()
    child = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 4 * * *", chain_to_job_id=parent.id,
    )
    db_session.commit()

    resp = client.delete(f"/api/cron/{parent.id}")
    assert resp.status_code == 409

    body = resp.json()["detail"]
    assert "dependents" in body
    assert len(body["dependents"]) == 1
    assert body["dependents"][0]["id"] == child.id
    assert body["dependents"][0]["name"] == "vaga.scan.default"

    # Both jobs still present
    db_session.expire_all()
    assert get_cron_job(db_session, parent.id) is not None
    assert get_cron_job(db_session, child.id) is not None


def test_cron_delete_without_dependents_succeeds(client, db_session):
    from book_scraper.db.repo import create_cron_job, get_cron_job, upsert_shop

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    job = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *",
    )
    db_session.commit()

    resp = client.delete(f"/api/cron/{job.id}")
    assert resp.status_code == 200

    db_session.expire_all()
    assert get_cron_job(db_session, job.id) is None


def test_cron_delete_succeeds_after_dependent_unlinked(client, db_session):
    """Operator-flow regression: PATCH clear_chain then DELETE works."""
    from book_scraper.db.repo import create_cron_job, get_cron_job, upsert_shop

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    parent = create_cron_job(
        db_session, shop_id=shop.id, phase="discover", strategy="sitemap",
        args="", cron_expression="0 2 * * *",
    )
    db_session.flush()
    child = create_cron_job(
        db_session, shop_id=shop.id, phase="scan", strategy=None,
        args="", cron_expression="0 4 * * *", chain_to_job_id=parent.id,
    )
    db_session.commit()

    # Unlink
    resp = client.patch(f"/api/cron/{child.id}", json={"clear_chain": True})
    assert resp.status_code == 200

    # Now delete succeeds
    resp = client.delete(f"/api/cron/{parent.id}")
    assert resp.status_code == 200

    db_session.expire_all()
    assert get_cron_job(db_session, parent.id) is None
```

- [ ] **Step 3: Run tests to verify the first fails**

```
uv run pytest tests/integration/test_dashboard_routes.py::test_cron_delete_with_dependents_returns_409 -v
```

Expected: FAIL — currently the parent gets deleted and child's `chain_to_job_id` is silently SET NULL by the FK constraint.

- [ ] **Step 4: Modify `api_cron_delete`**

In `book_scraper/dashboard/routes/api.py`, locate `api_cron_delete` (around line 2273). Replace the body so it checks for dependents before deletion. Add the necessary imports at the top of the file if not already present (`CronJob` and `Shop` are likely already imported via `book_scraper.db.models`).

```python
@router.delete("/cron/{job_id}")
def api_cron_delete(
    job_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
    job = get_cron_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    dependents = session.execute(
        select(CronJob.id, CronJob.phase, CronJob.strategy, Shop.name)
        .join(Shop, Shop.id == CronJob.shop_id)
        .where(CronJob.chain_to_job_id == job_id)
    ).all()
    if dependents:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Cannot delete: other schedules chain to this one.",
                "dependents": [
                    {
                        "id": d.id,
                        "name": f"{d.name}.{d.phase}.{d.strategy or 'default'}",
                    }
                    for d in dependents
                ],
            },
        )

    delete_cron_job(session, job_id)
    session.commit()
    return {"id": job_id}
```

If `select`, `CronJob`, `Shop`, or `delete_cron_job` are not yet imported in this file, add them. Run the file's lint check to confirm:

```
uv run ruff check book_scraper/dashboard/routes/api.py
```

Fix any unresolved-name errors by adding to the imports block.

- [ ] **Step 5: Run all three new tests**

```
uv run pytest tests/integration/test_dashboard_routes.py::test_cron_delete_with_dependents_returns_409 tests/integration/test_dashboard_routes.py::test_cron_delete_without_dependents_succeeds tests/integration/test_dashboard_routes.py::test_cron_delete_succeeds_after_dependent_unlinked -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```
git add book_scraper/dashboard/routes/api.py tests/integration/test_dashboard_routes.py
git commit -m "feat(api): block DELETE /api/cron/{id} with chained dependents (409)"
```

---

### Task 5: ISBN detection helper + extend `list_books` with `search` param

**Files:**
- Modify: `book_scraper/dashboard/queries.py` (`list_books` around line 2382)
- Test: `tests/unit/test_books_search_isbn.py` (create) — for the regex
- Test: `tests/integration/test_books_api.py` (append) — for the query behavior

- [ ] **Step 1: Write the unit test for ISBN detection**

Create `tests/unit/test_books_search_isbn.py`:

```python
"""Unit tests for the ISBN-shape detection used by the books search."""
from book_scraper.dashboard.queries import _looks_like_isbn


def test_isbn13_plain():
    assert _looks_like_isbn("9786094661099") == "9786094661099"


def test_isbn13_with_dashes():
    assert _looks_like_isbn("978-609-466-1099") == "9786094661099"


def test_isbn13_with_spaces():
    assert _looks_like_isbn("978 609 466 1099") == "9786094661099"


def test_isbn10_plain():
    assert _looks_like_isbn("0316769487") == "0316769487"


def test_isbn10_with_x_check_digit():
    assert _looks_like_isbn("097522980X") == "097522980X"


def test_isbn10_with_lowercase_x_uppercased():
    assert _looks_like_isbn("097522980x") == "097522980X"


def test_too_short_returns_none():
    assert _looks_like_isbn("123456") is None


def test_too_long_returns_none():
    assert _looks_like_isbn("12345678901234") is None


def test_alpha_returns_none():
    assert _looks_like_isbn("Tolkien") is None


def test_mixed_alpha_digits_returns_none():
    assert _looks_like_isbn("abc12345678") is None


def test_empty_returns_none():
    assert _looks_like_isbn("") is None


def test_whitespace_only_returns_none():
    assert _looks_like_isbn("   ") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_books_search_isbn.py -v
```

Expected: ImportError on `_looks_like_isbn`.

- [ ] **Step 3: Add `_looks_like_isbn` and extend `list_books`**

Open `book_scraper/dashboard/queries.py`. Add this helper near the top of the file, just under the imports block:

```python
import re

_ISBN_RE = re.compile(r"^(?:\d{9}[\dX]|\d{13})$")


def _looks_like_isbn(value: str) -> str | None:
    """Return the normalized ISBN if the input looks like one, else None.

    Strips dashes/spaces, uppercases X. Accepts ISBN-10 (with optional
    trailing X) and ISBN-13. Used by /api/books?search= to choose between
    exact ISBN match and substring title/author match.
    """
    if not value:
        return None
    normalized = value.replace("-", "").replace(" ", "").upper()
    if not normalized:
        return None
    return normalized if _ISBN_RE.fullmatch(normalized) else None
```

(The existing `queries.py` may already import `re` — check before adding the duplicate.)

Then modify `list_books` to accept and apply `search`. The function currently builds `base = select(Book)` then applies filters; insert the search branch after the existing filter block, before the count/order/limit:

Locate the function signature (around line 2382) and update it:

```python
def list_books(
    session: Session,
    *,
    data_source: str | None = None,
    has_isbn: bool | None = None,
    has_shops: bool | None = None,
    year: int | None = None,
    search: str | None = None,            # <-- add
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
```

Locate the existing imports inside the function:

```python
    from book_scraper.db.models import (
        Author,
        Book,
        BookAuthor,
        BookIsbn,
        Publisher,
        ShopBook,
    )
```

These are already what we need — no changes to the inline import block.

After the existing `has_shops` block and before the `total = ...` count, add:

```python
    if search and search.strip():
        as_isbn = _looks_like_isbn(search)
        if as_isbn:
            base = base.where(
                Book.id.in_(
                    select(BookIsbn.book_id).where(BookIsbn.isbn == as_isbn)
                )
            )
        else:
            like = f"%{search.strip()}%"
            base = base.where(
                or_(
                    Book.title.ilike(like),
                    Book.id.in_(
                        select(BookAuthor.book_id)
                        .join(Author, Author.id == BookAuthor.author_id)
                        .where(Author.name.ilike(like))
                    ),
                )
            )
```

Add `from sqlalchemy import or_` to the function-local imports if not present, or reuse the top-level `or_` already imported in `queries.py` (the existing imports already include `or_` — confirm by `grep "from sqlalchemy" book_scraper/dashboard/queries.py | head`).

- [ ] **Step 4: Run unit tests**

```
uv run pytest tests/unit/test_books_search_isbn.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Write integration tests for the search behavior**

Append to `tests/integration/test_books_api.py`:

```python
def test_books_search_by_isbn_exact_match(client, db_session):
    from book_scraper.db.models import Book, BookIsbn

    # Two books, one with the target ISBN
    target = Book(data_source="ibiblioteka", title="Hobitas", year=2020)
    other = Book(data_source="ibiblioteka", title="Žiedų valdovas", year=2021)
    db_session.add_all([target, other])
    db_session.flush()
    db_session.add(BookIsbn(book_id=target.id, isbn="9786094661099", isbn_type="isbn13"))
    db_session.commit()

    resp = client.get("/api/books?search=9786094661099")
    assert resp.status_code == 200
    titles = [b["title"] for b in resp.json()["books"]]
    assert "Hobitas" in titles
    assert "Žiedų valdovas" not in titles


def test_books_search_by_isbn_with_dashes(client, db_session):
    from book_scraper.db.models import Book, BookIsbn

    book = Book(data_source="ibiblioteka", title="Test Dash ISBN", year=2020)
    db_session.add(book)
    db_session.flush()
    db_session.add(BookIsbn(book_id=book.id, isbn="9786094661080", isbn_type="isbn13"))
    db_session.commit()

    resp = client.get("/api/books?search=978-609-466-1080")
    assert resp.status_code == 200
    titles = [b["title"] for b in resp.json()["books"]]
    assert "Test Dash ISBN" in titles


def test_books_search_by_title_substring(client, db_session):
    from book_scraper.db.models import Book

    db_session.add(Book(data_source="ibiblioteka", title="Tolkien biography", year=2020))
    db_session.add(Book(data_source="ibiblioteka", title="Unrelated", year=2020))
    db_session.commit()

    resp = client.get("/api/books?search=Tolkien")
    assert resp.status_code == 200
    titles = [b["title"] for b in resp.json()["books"]]
    assert "Tolkien biography" in titles
    assert "Unrelated" not in titles


def test_books_search_by_author_name(client, db_session):
    from book_scraper.db.models import Author, Book, BookAuthor

    book = Book(data_source="ibiblioteka", title="A title nothing like the author", year=2020)
    db_session.add(book)
    db_session.flush()
    author = Author(name="J.R.R. Tolkien Searchable", normalized_name="j.r.r. tolkien searchable")
    db_session.add(author)
    db_session.flush()
    db_session.add(BookAuthor(book_id=book.id, author_id=author.id, role="author", position=0))
    db_session.commit()

    resp = client.get("/api/books?search=Tolkien Searchable")
    assert resp.status_code == 200
    titles = [b["title"] for b in resp.json()["books"]]
    assert "A title nothing like the author" in titles


def test_books_search_empty_string_acts_like_no_filter(client, db_session):
    from book_scraper.db.models import Book

    db_session.add(Book(data_source="ibiblioteka", title="Some Book", year=2020))
    db_session.commit()

    resp_with = client.get("/api/books?search=")
    resp_without = client.get("/api/books")
    assert resp_with.status_code == 200
    assert resp_without.status_code == 200
    assert resp_with.json()["total"] == resp_without.json()["total"]
```

- [ ] **Step 6: Run integration tests — they will still fail until the route forwards `search`**

```
uv run pytest tests/integration/test_books_api.py -k search -v
```

Expected: all 5 fail because `/api/books` doesn't yet accept `search`. Continues in Task 6.

- [ ] **Step 7: Commit (test-first)**

```
git add book_scraper/dashboard/queries.py tests/unit/test_books_search_isbn.py tests/integration/test_books_api.py
git commit -m "feat(queries): list_books accepts search (smart ISBN/title/author)"
```

---

### Task 6: Wire `search` query parameter into `GET /api/books`

**Files:**
- Modify: `book_scraper/dashboard/routes/api.py` (`api_books` around line 1765)

- [ ] **Step 1: Add the parameter to the route**

In `book_scraper/dashboard/routes/api.py`, update `api_books`:

```python
@router.get("/books")
def api_books(
    data_source: str | None = None,
    has_isbn: bool | None = None,
    has_shops: bool | None = None,
    year: int | None = None,
    search: str | None = None,            # <-- add
    page: int = 1,
    per_page: int = 50,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import list_books
    return list_books(
        session,
        data_source=data_source, has_isbn=has_isbn, has_shops=has_shops,
        year=year, search=search,         # <-- add
        page=page, per_page=per_page,
    )
```

- [ ] **Step 2: Run integration tests**

```
uv run pytest tests/integration/test_books_api.py -k search -v
```

Expected: 5 passed.

Run the full books integration suite to confirm no regressions:

```
uv run pytest tests/integration/test_books_api.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```
git add book_scraper/dashboard/routes/api.py
git commit -m "feat(api): /api/books accepts ?search= (smart ISBN or title/author)"
```

---

## Phase B — Frontend

Frontend work has no JS test framework here, so steps are: edit, rebuild dashboard container, manually verify in browser, commit.

### Task 7: Wire `HFBook` into production routes (replace `HFBookDetail`)

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/index.html` (script list + route map)
- Modify: `book_scraper/dashboard/static/hifi/hf-books.jsx` (delete `HFBookDetail`)

- [ ] **Step 1: Add the `hf-book.jsx` script tag**

Open `book_scraper/dashboard/static/hifi/index.html`. After the line:

```html
<script type="text/babel" src="/static/hifi/hf-books.jsx"></script>
```

(line 28) insert immediately after:

```html
<script type="text/babel" src="/static/hifi/hf-book.jsx"></script>
```

- [ ] **Step 2: Update the route map**

In the same file, locate the `pages` object inside the App component (around line 158-176). Change:

```jsx
'book-detail':      () => <HFBookDetail nav={nav} goto={goto} params={params} />,
```

to:

```jsx
'book-detail':      () => <HFBook nav={nav} goto={goto} params={params} />,
```

- [ ] **Step 3: Delete the obsolete `HFBookDetail` from `hf-books.jsx`**

Open `book_scraper/dashboard/static/hifi/hf-books.jsx`. Delete the entire `HFBookDetail` function (starts around line 111 with `function HFBookDetail({ nav, goto, params }) {` and ends at the closing brace at line ~197). Keep `HFBooks` (the list) and the `DataSourceBadge` definition above it (still used by `HFBooks` rows).

- [ ] **Step 3b: Update the stale top-of-file comment in `hf-book.jsx`**

The current comment at the top of `book_scraper/dashboard/static/hifi/hf-book.jsx` says:

```jsx
// Canonical Book detail page.
// Used in the design prototype (HFBook fetches the first available book when no params.id).
// In the production dashboard, HFBookDetail (hf-books.jsx) handles the routed case with params.id.
```

After this task that's false — `HFBook` IS the production routed page. Replace those three lines with:

```jsx
// Canonical Book detail page — the routed component for /books/:id.
// The fallback "fetch the first book when no params.id" path remains for the
// design prototype's pager (Test design/Book Hifi.html), which renders this
// component without a route.
```

- [ ] **Step 4: Rebuild dashboard and restart**

```
docker compose build dashboard && docker compose up -d dashboard
```

- [ ] **Step 5: Verify in browser**

Open http://localhost:8000/books, click any row to land on `/books/:id`. Confirm:
- The new `HFBook` layout renders (cover on the left, breadcrumb at top, monospace ISBN chips, "Available at" card with shop count subtitle).
- No console errors.
- The old `HFBookDetail` text "← Books" button is gone (the breadcrumb replaces it).

If the page is blank, run:

```
docker exec book-scraper-dashboard-1 grep -c "HFBook[^D]" /app/book_scraper/dashboard/static/hifi/index.html
```

Expected: 1+ (the route map line). If not, the build cached a stale layer — rebuild with `--no-cache`:

```
docker compose build --no-cache dashboard && docker compose up -d dashboard
```

- [ ] **Step 6: Smoke test**

```
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all pass (this is the routes smoke suite).

- [ ] **Step 7: Commit**

```
git add book_scraper/dashboard/static/hifi/index.html book_scraper/dashboard/static/hifi/hf-books.jsx book_scraper/dashboard/static/hifi/hf-book.jsx
git commit -m "feat(dashboard): adopt HFBook on /books/:id, remove HFBookDetail"
```

(`hf-book.jsx` is already a tracked file; the commit only updates its top comment in this task. Task 8 will modify its body further.)

---

### Task 8: Apply UX review fixes to `hf-book.jsx`

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-book.jsx`

- [ ] **Step 1: Add helper functions at top of file**

Open `book_scraper/dashboard/static/hifi/hf-book.jsx`. Add helpers above `DataSourceBadge`:

```jsx
// Locale-correct EUR formatting for Lithuanian price display.
const _eurFormatter = new Intl.NumberFormat('lt-LT', {
  style: 'currency', currency: 'EUR',
});
function formatEur(value) {
  if (value == null || value === '') return '—';
  const n = Number(value);
  return Number.isFinite(n) ? _eurFormatter.format(n) : '—';
}

// "Last seen" relative formatting. Falls back to the raw ISO if input is unusable.
function formatRelative(iso) {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return iso;
  const diffSec = Math.round((Date.now() - t) / 1000);
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 86400 * 30) return `${Math.floor(diffSec / 86400)}d ago`;
  return new Date(iso).toLocaleDateString('lt-LT');
}
```

- [ ] **Step 2: Update `DataSourceBadge` fallback**

Replace:

```jsx
const cfg = map[value] || { label: value || '—', tone: 'neutral' };
```

with:

```jsx
const cfg = map[value] || { label: 'Unknown', tone: 'neutral' };
```

- [ ] **Step 3: Fix cover image (CLS + lazy)**

Locate the `<img>` for the cover (around line 113-123). Replace with:

```jsx
{book.cover_url && (
  <img
    src={book.cover_url}
    alt={book.title}
    loading="lazy"
    style={{
      width: 108, aspectRatio: '2 / 3', objectFit: 'contain',
      flexShrink: 0, borderRadius: 6,
      border: '1px solid var(--hf-border)',
      boxShadow: '0 2px 8px rgba(16,24,40,.08)',
      background: 'var(--hf-subtle)',
    }}
  />
)}
```

- [ ] **Step 4: Add `language` to the meta line**

Locate the `meta` array (around line 85-91). Update:

```jsx
const meta = [
  book.year,
  book.publisher,
  book.format,
  book.language,                           // <-- add
  book.pages && `${book.pages} p.`,
  book.duration,
].filter(Boolean).join(' · ');
```

- [ ] **Step 5: Cap description line length**

Locate the description block (around line 191-199). Wrap with `maxWidth: '70ch'`:

```jsx
{book.description && (
  <div style={{
    marginTop: 14, paddingTop: 14,
    borderTop: (book.subjects || []).length > 0 ? 'none' : '1px solid var(--hf-border-faint)',
    lineHeight: 1.65, fontSize: 13, color: 'var(--hf-ink2)',
    maxWidth: '70ch',
  }}>
    {book.description}
  </div>
)}
```

- [ ] **Step 6: ISBN chips — copy on click + accessible**

Locate the ISBN chip render (around line 162-169). Replace with:

```jsx
{isbns.map(i => (
  <button
    key={i.isbn}
    type="button"
    aria-label={`Copy ISBN ${i.isbn}`}
    onClick={() => {
      navigator.clipboard.writeText(i.isbn).then(
        () => window.HF_APP?.toast?.({ tone: 'ok', message: `Copied ${i.isbn}` }),
        () => window.HF_APP?.toast?.({ tone: 'err', message: 'Copy failed' }),
      );
    }}
    style={{
      fontFamily: 'var(--hf-mono)', fontSize: 11,
      padding: '3px 8px', borderRadius: 4,
      background: 'var(--hf-subtle)', border: '1px solid var(--hf-border)',
      color: 'var(--hf-ink2)', cursor: 'pointer',
    }}
  >{i.isbn}</button>
))}
```

- [ ] **Step 7: Shop table — locale prices, accessible URL link, relative timestamps**

Locate the `HFTable` rows mapping (around line 222-232). Replace with:

```jsx
rows={(book.shops || []).map(s => ({
  ...s,
  price: formatEur(s.price),
  in_stock: s.in_stock
    ? <HFPill tone="ok" soft>In stock</HFPill>
    : <HFPill tone="warn" soft>Out</HFPill>,
  last_seen_at: s.last_seen_at
    ? <time dateTime={s.last_seen_at}>{formatRelative(s.last_seen_at)}</time>
    : '—',
  url: s.url
    ? <a
        href={s.url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Open at ${s.shop} (new tab)`}
        title={`Open at ${s.shop}`}
        style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          minWidth: 32, minHeight: 32, padding: '0 8px',
          color: 'var(--hf-accent-ink)', fontFamily: 'var(--hf-mono)', fontSize: 11,
          textDecoration: 'none',
        }}
      >Visit ↗</a>
    : '—',
}))}
```

- [ ] **Step 8: Rebuild + verify in browser**

```
docker compose build dashboard && docker compose up -d dashboard
```

Open http://localhost:8000/books/<id-of-a-book-with-shops-and-isbns>. Verify:
- Price shows like `1,99 €` (Lithuanian locale).
- Cover loads without layout jump (reload to confirm).
- Clicking an ISBN chip shows a "Copied …" toast.
- Hovering "Visit ↗" shows the tooltip; the link target area is wider than a single character.
- `last_seen_at` reads "5h ago" / "2d ago" rather than raw ISO.
- Description wraps at a narrower measure on a wide screen (compare with browser zoom 80%).
- Subject pills still render.
- A book with `data_source` set to an unmapped value would render as "Unknown" (force this temporarily by editing the API response or skip if no such row exists).

- [ ] **Step 9: Commit**

```
git add book_scraper/dashboard/static/hifi/hf-book.jsx
git commit -m "fix(dashboard): UX polish on HFBook (CLS, locale, a11y, copy)"
```

---

### Task 9: Replace client-side filter with server-side `?search=` in `HFBooks`

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-books.jsx`

- [ ] **Step 1: Update `HFBooks` to drive search via the API**

Open `book_scraper/dashboard/static/hifi/hf-books.jsx`. Locate `HFBooks` (now the only component in the file after Task 7).

Replace the existing `useEffect` and the post-fetch client-side filter, and reset `page` directly from the input handlers (not via a separate effect — that races with in-flight fetches).

Replace this block:

```jsx
React.useEffect(() => {
  const params = new URLSearchParams();
  if (dataSource !== 'all') params.set('data_source', dataSource);
  if (hasIsbn !== 'any')    params.set('has_isbn', hasIsbn === 'yes' ? 'true' : 'false');
  if (hasShops !== 'any')   params.set('has_shops', hasShops === 'linked' ? 'true' : 'false');
  if (year)                 params.set('year', year);
  params.set('page', String(page));
  params.set('per_page', String(PER_PAGE));
  setLoading(true);
  fetch(`/api/books?${params}`)
    .then(r => r.json())
    .then(d => { setData(d); setLoading(false); });
}, [dataSource, hasIsbn, hasShops, year, page]);

const visible = q
  ? data.books.filter(b => (b.title || '').toLowerCase().includes(q.toLowerCase()))
  : data.books;
```

with:

```jsx
const [debouncedQ, setDebouncedQ] = React.useState(q);
React.useEffect(() => {
  const id = setTimeout(() => setDebouncedQ(q), 150);
  return () => clearTimeout(id);
}, [q]);

React.useEffect(() => {
  const params = new URLSearchParams();
  if (dataSource !== 'all') params.set('data_source', dataSource);
  if (hasIsbn !== 'any')    params.set('has_isbn', hasIsbn === 'yes' ? 'true' : 'false');
  if (hasShops !== 'any')   params.set('has_shops', hasShops === 'linked' ? 'true' : 'false');
  if (year)                 params.set('year', year);
  if (debouncedQ.trim())    params.set('search', debouncedQ.trim());
  params.set('page', String(page));
  params.set('per_page', String(PER_PAGE));
  setLoading(true);
  fetch(`/api/books?${params}`)
    .then(r => r.json())
    .then(d => { setData(d); setLoading(false); });
}, [dataSource, hasIsbn, hasShops, year, debouncedQ, page]);

const visible = data.books;
```

Then reset `page` synchronously in each input handler so it lands in the same render as the new filter/search value (the API call dispatched from the effect uses the post-reset `page=1`):

- The search input: `<HFSearch ... value={q} onChange={v => { setQ(v); setPage(1); }} />`
- Each filter:
  - `<HFFilter label="Source"  ... onChange={v => { setDataSource(v); setPage(1); }} ...>`
  - `<HFFilter label="ISBN"    ... onChange={v => { setHasIsbn(v); setPage(1); }} ...>`
  - `<HFFilter label="Shops"   ... onChange={v => { setHasShops(v); setPage(1); }} ...>`
- The year input (if changed): `onChange={v => { setYear(v); setPage(1); }}`

Do NOT add a `React.useEffect(() => setPage(1), [debouncedQ])` — it can fire after a fetch is already in flight with the previous `page`, double-fetching and possibly landing on stale results.

- [ ] **Step 2: Rebuild + verify**

```
docker compose build dashboard && docker compose up -d dashboard
```

Open http://localhost:8000/books. Verify:
- Typing a partial title returns matching books from the server (not just current page).
- Typing a full ISBN (with or without dashes) returns the matching book.
- Typing an author surname returns books by that author.
- Clearing the search returns the full list.
- Pagination resets when search input changes.
- No console errors.

- [ ] **Step 3: Commit**

```
git add book_scraper/dashboard/static/hifi/hf-books.jsx
git commit -m "feat(dashboard): server-side search on Books list (smart ISBN/title/author)"
```

---

### Task 10: Delete schedule (with 409 dependent flow) on `HFScheduleDetail`

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-more-details.jsx`

- [ ] **Step 1: Locate the page-head actions and add a Delete button**

Open `book_scraper/dashboard/static/hifi/hf-more-details.jsx`. Locate `function HFScheduleDetail({ nav, goto, params })` (around line 204). The variables in scope inside this function include `jobId` (int), `name` (string, the schedule's `shop.phase.strategy` form), `shop`, `cron`, and `detail` (the API payload). The existing edit dialog (around line 402) is a landmark — the new Delete button and modal will live near it.

Add a `useState` near the top of the function (after the existing state declarations):

```jsx
const [deleteState, setDeleteState] = React.useState({ open: false, dependents: null, error: null, busy: false });
```

In the actions row (alongside the existing edit/toggle buttons), add:

```jsx
<HFButton
  size="sm"
  variant="danger"
  onClick={() => setDeleteState({ open: true, dependents: null, error: null, busy: false })}
>Delete</HFButton>
```

- [ ] **Step 2: Add the delete confirmation modal**

At the end of the JSX returned by `HFScheduleDetail` (next to the existing `<HFEditScheduleDialog ... />`), add:

```jsx
<HFModal open={deleteState.open} onClose={() => setDeleteState(s => ({ ...s, open: false }))} width={520}>
  <HFModalHead
    title="Delete schedule"
    sub={name ? `Confirm deletion of ${name}` : undefined}
    onClose={() => setDeleteState(s => ({ ...s, open: false }))}
  />
  <HFModalBody>
    {deleteState.dependents && deleteState.dependents.length > 0 ? (
      <>
        <div style={{ fontSize: 13, color: 'var(--hf-ink2)', marginBottom: 10 }}>
          Cannot delete — these schedules chain to this one. Unlink each one first
          (open it, click Edit, clear the chain), then come back to delete.
        </div>
        <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {deleteState.dependents.map(d => (
            <li key={d.id}>
              <button
                type="button"
                onClick={() => goto('schedule-detail', { id: d.id })}
                style={{
                  background: 'var(--hf-subtle)', border: '1px solid var(--hf-border)',
                  borderRadius: 6, padding: '8px 12px', cursor: 'pointer',
                  width: '100%', textAlign: 'left',
                  fontFamily: 'var(--hf-mono)', fontSize: 12, color: 'var(--hf-ink)',
                }}
              >{d.name} →</button>
            </li>
          ))}
        </ul>
      </>
    ) : deleteState.error ? (
      <div style={{ fontSize: 13, color: 'var(--hf-err-ink)' }}>
        {deleteState.error}
      </div>
    ) : (
      <div style={{ fontSize: 13, color: 'var(--hf-ink2)' }}>
        Delete schedule <strong>{name}</strong>? This cannot be undone.
      </div>
    )}
  </HFModalBody>
  <HFModalFoot>
    <HFButton size="sm" variant="ghost"
              onClick={() => setDeleteState(s => ({ ...s, open: false }))}>
      {deleteState.dependents ? 'Close' : 'Cancel'}
    </HFButton>
    {!deleteState.dependents && (
      <HFButton size="sm" variant="danger" disabled={deleteState.busy}
                onClick={async () => {
                  setDeleteState(s => ({ ...s, busy: true, error: null }));
                  try {
                    const resp = await fetch(`/api/cron/${jobId}`, { method: 'DELETE' });
                    if (resp.status === 200) {
                      window.HF_APP?.toast?.({ tone: 'ok', message: 'Schedule deleted' });
                      goto('cron');
                      return;
                    }
                    if (resp.status === 409) {
                      const body = await resp.json().catch(() => ({}));
                      const detail = body?.detail || {};
                      setDeleteState({
                        open: true, busy: false, error: null,
                        dependents: Array.isArray(detail.dependents) ? detail.dependents : [],
                      });
                      return;
                    }
                    const body = await resp.json().catch(() => ({}));
                    setDeleteState(s => ({
                      ...s, busy: false,
                      error: body?.detail || `Error ${resp.status}`,
                    }));
                  } catch (e) {
                    setDeleteState(s => ({ ...s, busy: false, error: String(e) }));
                  }
                }}>
        {deleteState.busy ? 'Deleting…' : 'Delete'}
      </HFButton>
    )}
  </HFModalFoot>
</HFModal>
```

Note: `jobId`, `name`, and `goto` are already in scope inside `HFScheduleDetail` (confirmed by inspecting lines 204–406). No renaming needed.

- [ ] **Step 3: Rebuild + verify the success path**

```
docker compose build dashboard && docker compose up -d dashboard
```

In the browser, navigate to a schedule detail page that has **no dependents**. Click Delete → Confirm. Expected:
- Modal closes.
- Page navigates to `/cron`.
- A green toast "Schedule deleted" appears.
- The deleted schedule is gone from the list.

- [ ] **Step 4: Verify the 409 dependent path**

Create or pick a chained pair: `humanitas.discover` → chained-to → `humanitas.scan`. Navigate to the parent (the one being chained to), click Delete → Confirm. Expected:
- Modal stays open.
- Body switches to "Cannot delete — these schedules chain to this one." with a clickable list.
- Cancel/Close still works.
- Clicking the dependent's button navigates to that schedule's detail page (so the operator can edit-and-clear the chain).

After unlinking the dependent (Edit → clear chain → Save), return to the parent and Delete → Confirm. Expected: success path as in Step 3.

- [ ] **Step 5: Commit**

```
git add book_scraper/dashboard/static/hifi/hf-more-details.jsx
git commit -m "feat(dashboard): delete schedule with 409 dependent-list flow"
```

---

## Phase C — Verify & ship

### Task 11: Verify "Run history" tab + final smoke

**Files:** none new — verification only.

- [ ] **Step 1: Verify the existing Run history tab on `HFScheduleDetail`**

In the browser, open any schedule that has past runs. Click the "Run history" tab. Confirm:
- Past runs render with status, started_at, duration, and click-to-open run detail.
- Empty state appears for schedules with no history.

If the tab is missing data or broken, that's out of scope for this plan — open a separate task.

- [ ] **Step 2: Run the full integration suite**

```
uv run pytest tests/integration/test_dashboard_routes.py tests/integration/test_books_api.py -v
```

Expected: all pass.

- [ ] **Step 3: Run the full unit suite**

```
uv run pytest tests/unit/ -v
```

Expected: all pass (including the new `test_cron_validation.py` and `test_books_search_isbn.py`).

- [ ] **Step 4: Lint + type check**

```
uv run ruff check book_scraper/ tests/
uv run mypy book_scraper/
```

Expected: clean.

- [ ] **Step 5: Manual click-through smoke**

In the browser, walk through:
- `/books` — type partial title → server search returns matches; clear → full list.
- `/books` — type a known ISBN (with dashes) → exact match.
- `/books/<id>` — verify HFBook layout (cover, breadcrumb, locale price, copy ISBN).
- `/cron` — pick a schedule with dependents → Delete → see 409 dependent list → click dependent → unlink → return → Delete succeeds.
- `/cron` — invalid cron in New schedule dialog → 422 error surfaces inline.

- [ ] **Step 6: No final commit needed** (verification only).

---

## Notes for the implementer

- **Docker rebuild gotcha:** if a frontend change doesn't appear after `docker compose build dashboard`, suspect the BuildKit cache. Confirm with `docker exec book-scraper-dashboard-1 grep <new-symbol> /app/book_scraper/dashboard/static/hifi/<file>`. If missing, rebuild with `--no-cache` (mentioned in CLAUDE.md).
- **Don't `kill -9` scrapy:** unrelated but worth knowing — see CLAUDE.md.
- **`croniter` is already a dep** (`>=6.0`), no `pyproject.toml` change needed.
- **Frontend has no JS test framework**; verification is browser-based plus Python integration tests against the FastAPI app.
- **No Alembic migration needed**; this plan only touches existing tables.
