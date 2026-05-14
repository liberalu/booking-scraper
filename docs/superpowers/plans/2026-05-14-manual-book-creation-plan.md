# Manual Book Creation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/books` and wire the existing `HFAddBookDialog` stub so operators can manually create canonical books with ISBN collision detection.

**Architecture:** `create_manual_book()` in `repo.py` handles the DB work (find-or-create publisher/author, ISBN uniqueness, raises `ValueError("isbn_collision:{id}")` on collision). The API route normalises the ISBN via `_looks_like_isbn` (already in `queries.py`), calls the repo function, maps the `ValueError` to HTTP 409. `HFAddBookDialog` in `hf-overlays.jsx` is wired to the endpoint with loading state, inline error, and 409 collision link.

**Tech Stack:** Python/SQLAlchemy/FastAPI (backend); React 18 Babel CDN (frontend). No migrations.

**Spec:** `docs/superpowers/specs/2026-05-14-manual-book-creation-design.md`

---

## File Structure

| File | Change |
|---|---|
| `book_scraper/db/repo.py` | Add `create_manual_book(session, *, title, isbn, author, publisher, year)` after `get_price_history` area (end of file is fine) |
| `book_scraper/dashboard/routes/api.py` | Add `_CreateBookBody` + `POST /api/books` after `api_book_prices` |
| `tests/integration/test_books_api.py` | Append 6 new integration tests |
| `book_scraper/dashboard/static/hifi/hf-overlays.jsx` | Replace stub `HFAddBookDialog` (line ~978) with wired version |

---

## Task 1: `create_manual_book` + integration tests (TDD)

**Files:**
- Modify: `book_scraper/db/repo.py` (append near end of file)
- Test: `tests/integration/test_books_api.py` (append)

- [ ] **Step 1: Append integration tests**

Open `tests/integration/test_books_api.py` and append at the end:

```python
# ----- Manual book creation (Phase 3) -------------------------------------


def test_create_manual_book_minimal(client, db_session):
    resp = client.post("/api/books", json={"title": "My Manual Book"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "My Manual Book"
    assert "id" in data


def test_create_manual_book_with_all_fields(client, db_session):
    resp = client.post("/api/books", json={
        "title": "Full Manual Book",
        "isbn": "9780062316097",
        "author": "Test Author",
        "publisher": "Test Publisher",
        "year": 2024,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Full Manual Book"

    detail = client.get(f"/api/books/{data['id']}").json()
    assert detail["publisher"] == "Test Publisher"
    assert any(i["isbn"] == "9780062316097" for i in detail["isbns"])
    assert any(a["name"] == "Test Author" for a in detail["authors"])


def test_create_manual_book_blank_title_rejected(client):
    resp = client.post("/api/books", json={"title": ""})
    assert resp.status_code == 422


def test_create_manual_book_isbn_collision_returns_409(client, db_session):
    from book_scraper.db.models import Book, BookIsbn

    existing = Book(data_source="shop_inferred", title="Existing Book Coll", year=2020)
    db_session.add(existing)
    db_session.flush()
    db_session.add(BookIsbn(book_id=existing.id, isbn="9780062316010", isbn_type="isbn13"))
    db_session.commit()

    resp = client.post("/api/books", json={
        "title": "Duplicate ISBN Book",
        "isbn": "9780062316010",
    })
    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["existing_book_id"] == existing.id


def test_create_manual_book_isbn_with_dashes_normalized(client, db_session):
    resp = client.post("/api/books", json={
        "title": "Dash ISBN Book",
        "isbn": "978-0-06-231601-0",
    })
    assert resp.status_code == 200
    detail = client.get(f"/api/books/{resp.json()['id']}").json()
    assert any(i["isbn"] == "9780062316010" for i in detail["isbns"])


def test_create_manual_book_invalid_isbn_rejected(client):
    resp = client.post("/api/books", json={"title": "Bad ISBN", "isbn": "notanisbn"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to confirm failure**

```
uv run pytest tests/integration/test_books_api.py -k "create_manual" -v 2>&1 | tail -12
```

Expected: all 6 fail — endpoint doesn't exist yet.

- [ ] **Step 3: Add `create_manual_book` to `repo.py`**

Open `book_scraper/db/repo.py`. Note that `select`, `func`, `or_` are already imported at the top from `sqlalchemy`. `_normalize_author` is already defined at line ~54 as:
```python
def _normalize_author(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())
```

Append this function **at the end of the file** (after the last existing function):

```python
def create_manual_book(
    session: Session,
    *,
    title: str,
    isbn: str | None = None,
    author: str | None = None,
    publisher: str | None = None,
    year: int | None = None,
) -> "Book":
    """Create a canonical book with data_source='manual'.

    `isbn` must already be normalised (digits only, uppercase X).
    Raises ValueError("isbn_collision:<existing_book_id>") if the ISBN
    already exists on another book — the caller maps this to HTTP 409.
    """
    from book_scraper.db.models import (
        Author,
        Book,
        BookAuthor,
        BookIsbn,
        Publisher,
    )

    # ISBN uniqueness check
    if isbn:
        existing = session.execute(
            select(BookIsbn).where(BookIsbn.isbn == isbn)
        ).scalar_one_or_none()
        if existing:
            raise ValueError(f"isbn_collision:{existing.book_id}")

    # Publisher: find-or-create by name
    pub_id = None
    if publisher and publisher.strip():
        pub_name = publisher.strip()
        pub = session.execute(
            select(Publisher).where(Publisher.name == pub_name)
        ).scalar_one_or_none()
        if pub is None:
            pub = Publisher(name=pub_name)
            session.add(pub)
            session.flush()
        pub_id = pub.id

    # Create Book
    book = Book(
        data_source="manual",
        title=title.strip(),
        year=year,
        publisher_id=pub_id,
    )
    session.add(book)
    session.flush()

    # ISBN
    if isbn:
        isbn_type = "isbn13" if len(isbn) == 13 else "isbn10"
        session.add(BookIsbn(book_id=book.id, isbn=isbn, isbn_type=isbn_type))

    # Author: find-or-create by normalised name
    if author and author.strip():
        norm = _normalize_author(author.strip())
        au = session.execute(
            select(Author).where(Author.normalized_name == norm)
        ).scalar_one_or_none()
        if au is None:
            au = Author(name=author.strip(), normalized_name=norm)
            session.add(au)
            session.flush()
        session.add(BookAuthor(book_id=book.id, author_id=au.id,
                               role="author", position=0))

    return book
```

- [ ] **Step 4: Add `POST /api/books` to `api.py`**

Open `book_scraper/dashboard/routes/api.py`. Find where `api_book_prices` ends (after `return {"book_id": book_id, "series": series}`). Insert the following immediately after that function and before `@router.get("/shops")`:

```python
class _CreateBookBody(BaseModel):
    title: str
    isbn: str | None = None
    author: str | None = None
    publisher: str | None = None
    year: int | None = None


@router.post("/books")
def api_create_book(
    body: _CreateBookBody, session: Session = Depends(get_db)
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import _looks_like_isbn
    from book_scraper.db.repo import create_manual_book

    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required")

    isbn: str | None = None
    if body.isbn and body.isbn.strip():
        isbn = _looks_like_isbn(body.isbn.strip())
        if isbn is None:
            raise HTTPException(
                status_code=422,
                detail="Invalid ISBN format (expected 10 or 13 digits)",
            )

    try:
        book = create_manual_book(
            session,
            title=title,
            isbn=isbn,
            author=body.author,
            publisher=body.publisher,
            year=body.year,
        )
        session.commit()
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("isbn_collision:"):
            existing_id = int(msg.split(":")[1])
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "ISBN already belongs to another book.",
                    "existing_book_id": existing_id,
                },
            )
        raise HTTPException(status_code=422, detail=msg)

    return {"id": book.id, "title": book.title}
```

- [ ] **Step 5: Run the 6 tests**

```
uv run pytest tests/integration/test_books_api.py -k "create_manual" -v 2>&1 | tail -15
```

Expected: 6 passed.

- [ ] **Step 6: Full books_api suite — no regressions**

```
uv run pytest tests/integration/test_books_api.py -q 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 7: Ruff check**

```
uv run ruff check book_scraper/db/repo.py book_scraper/dashboard/routes/api.py --output-format=concise 2>&1 | tail -8
```

Expected: clean on new code (pre-existing errors in other lines are OK).

- [ ] **Step 8: Commit**

```bash
git add book_scraper/db/repo.py book_scraper/dashboard/routes/api.py tests/integration/test_books_api.py
git commit -m "feat(api): POST /api/books — manual book creation with ISBN collision detection"
```

---

## Task 2: Wire `HFAddBookDialog`

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-overlays.jsx` (replace stub at line ~978)

- [ ] **Step 1: Read the file to find `HFAddBookDialog`**

Open `book_scraper/dashboard/static/hifi/hf-overlays.jsx`. Locate `function HFAddBookDialog` (around line 978). Note the closing `}` before `// ══════ Parser picker`. You need to replace the entire function body.

- [ ] **Step 2: Replace the stub with the wired version**

Find the entire `HFAddBookDialog` function (from `function HFAddBookDialog` to its closing `}` before `// ══════ Parser picker`). Replace it with:

```jsx
function HFAddBookDialog({ open, onClose }) {
  const HF = getHF();
  const [isbn, setIsbn]           = React.useState('');
  const [title, setTitle]         = React.useState('');
  const [author, setAuthor]       = React.useState('');
  const [publisher, setPublisher] = React.useState('');
  const [year, setYear]           = React.useState('');
  const [saving, setSaving]       = React.useState(false);
  const [error, setError]         = React.useState(null);

  const reset = () => {
    setIsbn(''); setTitle(''); setAuthor('');
    setPublisher(''); setYear(''); setError(null);
  };

  const handleClose = () => { reset(); onClose(false); };

  const handleCreate = async () => {
    if (!title.trim()) return;
    setSaving(true); setError(null);
    try {
      const resp = await fetch('/api/books', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim(),
          isbn: isbn.trim() || null,
          author: author.trim() || null,
          publisher: publisher.trim() || null,
          year: year ? parseInt(year, 10) : null,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        window.HF_APP?.toast?.({ tone: 'ok', message: `Book "${data.title}" created` });
        reset();
        onClose(true);
        window.HF_APP?.goto?.('book-detail', { id: data.id });
        return;
      }
      const body = await resp.json().catch(() => ({}));
      if (resp.status === 409 && body?.detail?.existing_book_id) {
        setError({
          type: 'collision',
          message: body.detail.message,
          existing_book_id: body.detail.existing_book_id,
        });
      } else {
        setError({
          type: 'generic',
          message: (typeof body?.detail === 'string')
            ? body.detail
            : `Error ${resp.status}`,
        });
      }
    } catch (e) {
      setError({ type: 'generic', message: String(e) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <HFModal open={open} onClose={handleClose} width={520}>
      <HFModalHead title="Add book"
                   sub="Manual entry — books are usually added automatically by scrapes"
                   onClose={handleClose} icon={HF_ICONS.books}/>
      <HFModalBody>
        <HFField label="Title" required>
          <HFInput value={title} onChange={setTitle}
                   placeholder="Book title" autoFocus/>
        </HFField>
        <HFField label="ISBN" hint="ISBN-10 or ISBN-13 — leave blank if unknown">
          <HFInput value={isbn}
                   onChange={v => { setIsbn(v); setError(null); }}
                   placeholder="9780062316097" mono/>
        </HFField>
        <HFField label="Author">
          <HFInput value={author} onChange={setAuthor}
                   placeholder="Firstname Lastname"/>
        </HFField>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px', gap: 12 }}>
          <HFField label="Publisher">
            <HFInput value={publisher} onChange={setPublisher}
                     placeholder="Publisher name"/>
          </HFField>
          <HFField label="Year">
            <HFInput value={year} onChange={setYear} mono placeholder="2024"/>
          </HFField>
        </div>
        {error && (
          <div style={{
            marginTop: 8, padding: '8px 12px', borderRadius: 6,
            background: 'var(--hf-err-soft)', border: '1px solid var(--hf-err-border)',
            fontSize: 13, color: 'var(--hf-err-ink)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <span>{error.message}</span>
            {error.type === 'collision' && (
              <button
                type="button"
                onClick={() => {
                  handleClose();
                  window.HF_APP?.goto?.('book-detail', { id: error.existing_book_id });
                }}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: 'var(--hf-err-ink)', fontWeight: 600, fontSize: 13,
                  whiteSpace: 'nowrap', marginLeft: 12,
                }}>View book →</button>
            )}
          </div>
        )}
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={handleClose}>Cancel</HFButton>
        <HFButton variant="primary" onClick={handleCreate}
                  disabled={!title.trim() || saving}>
          {saving ? 'Creating…' : 'Create book'}
        </HFButton>
      </HFModalFoot>
    </HFModal>
  );
}
```

- [ ] **Step 3: Rebuild dashboard**

```bash
HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" ALL_PROXY="" all_proxy="" docker compose build dashboard && docker compose up -d dashboard
```

- [ ] **Step 4: Verify in container**

```bash
docker exec book-scraper-dashboard-1 grep -c 'handleCreate\|isbn_collision\|View book' /app/book_scraper/dashboard/static/hifi/hf-overlays.jsx
```

Expected: 3+

Confirm old stub gone:
```bash
docker exec book-scraper-dashboard-1 grep -c 'onClick={onClose}.*Create book' /app/book_scraper/dashboard/static/hifi/hf-overlays.jsx
```

Expected: 0

- [ ] **Step 5: Manual smoke in browser**

Open `http://localhost:8000` → click the "+" / "New" book button (or use ⌘K → "Add book").

Test the happy path:
- Enter Title = "Test Manual Book", Year = 2024 → click Create
- Expect: toast "Book 'Test Manual Book' created", navigates to `/books/:id`
- Verify book appears on `/books` list with Source = "Manual" badge

Test the collision path:
- Find a book's ISBN on `/books` (e.g. from the detail page)
- Open Add book dialog, enter that ISBN
- Expect: red error "ISBN already belongs to another book." + "View book →" link
- Click link → navigates to the existing book

Test blank title:
- Leave title empty → Create button should be disabled

- [ ] **Step 6: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-overlays.jsx
git commit -m "feat(dashboard): wire HFAddBookDialog to POST /api/books"
```

---

## Task 3: Final smoke

- [ ] **Step 1: Full test suite**

```bash
uv run pytest tests/ -q --tb=no 2>&1 | tail -4
```

Expected: 820+ passing.

- [ ] **Step 2: API smoke**

```bash
# Create a book
curl -s -X POST http://localhost:8000/api/books \
  -H 'Content-Type: application/json' \
  -d '{"title":"Smoke Test Book","year":2024}' | python3 -c "import json,sys; d=json.load(sys.stdin); print('id:', d.get('id'), 'title:', d.get('title'))"
```

Expected: `id: <N> title: Smoke Test Book`

---

## Notes for the implementer

- **`_normalize_author`** is a private function at line ~54 of `repo.py`. It's in the same file as `create_manual_book` — call it directly.
- **`select`** is already imported at the top of `repo.py` from `sqlalchemy`. Do NOT add a duplicate import.
- **`BookAuthor` role/position:** The `book_author_role_enum` in models.py accepts `"author"` as a valid role. `position=0` is correct for the first (only) author.
- **`_looks_like_isbn`** is in `book_scraper/dashboard/queries.py` (added in Phase 1). Import it inside the route function to keep the module-level import list clean.
- **`window.HF_APP.goto`** is registered in `index.html` (line 147). It accepts `(page, params)` — `goto('book-detail', { id: N })` navigates to the book detail page.
- **Docker BuildKit cache:** if the dialog stub is still showing after rebuild, check with `docker exec book-scraper-dashboard-1 grep -c 'handleCreate' /app/.../hf-overlays.jsx`. If 0, rebuild with `--no-cache`.
