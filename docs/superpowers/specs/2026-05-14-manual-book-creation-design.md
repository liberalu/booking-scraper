# Manual Book Creation — Design Spec

**Status:** Implemented
## Goal

Wire the existing `HFAddBookDialog` stub to a new `POST /api/books` endpoint so operators can manually add canonical books with `data_source=manual`. ISBN collision returns a 409 with a link to the conflicting book.

## Scope

- New `create_manual_book(session, ...)` function in `book_scraper/db/repo.py`
- New `POST /api/books` route in `book_scraper/dashboard/routes/api.py`
- Wire `HFAddBookDialog` in `book_scraper/dashboard/static/hifi/hf-overlays.jsx`
- Integration tests in `tests/integration/test_books_api.py`
- No schema migrations

## Non-Goals

- Editing existing books (separate feature)
- Attaching shop_book links from the create form (Phase 4)
- Duplicate title detection (title is not unique in the schema)
- Publisher/author autocomplete (plain text input, find-or-create on backend)

---

## Backend

### `create_manual_book` in `book_scraper/db/repo.py`

```python
def create_manual_book(
    session: Session,
    *,
    title: str,
    isbn: str | None = None,
    author: str | None = None,
    publisher: str | None = None,
    year: int | None = None,
) -> Book:
    """Create a canonical book with data_source='manual'.

    ISBN must already be normalized (digits only, uppercase X).
    Raises ValueError("isbn_collision:<existing_book_id>") if the ISBN
    already exists on another book — caller maps this to HTTP 409.
    """
    from sqlalchemy import select

    from book_scraper.db.models import (
        Author, Book, BookAuthor, BookIsbn, Publisher
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
        name = publisher.strip()
        pub = session.execute(
            select(Publisher).where(Publisher.name == name)
        ).scalar_one_or_none()
        if pub is None:
            pub = Publisher(name=name)
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

    # Author: find-or-create by normalized name
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

Note: `_normalize_author` is a private function already in `repo.py` (line 54). Reuse it.

### `POST /api/books` in `book_scraper/dashboard/routes/api.py`

Add near the other `/books` routes:

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
            raise HTTPException(status_code=422,
                                detail="Invalid ISBN format (expected 10 or 13 digits)")

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
                    "message": f"ISBN already belongs to another book.",
                    "existing_book_id": existing_id,
                },
            )
        raise HTTPException(status_code=422, detail=msg)

    return {"id": book.id, "title": book.title}
```

---

## Frontend — wire `HFAddBookDialog`

Replace the stub body of `HFAddBookDialog` in `hf-overlays.jsx` with:

```jsx
function HFAddBookDialog({ open, onClose }) {
  const HF = getHF();
  const [isbn, setIsbn]         = React.useState('');
  const [title, setTitle]       = React.useState('');
  const [author, setAuthor]     = React.useState('');
  const [publisher, setPublisher] = React.useState('');
  const [year, setYear]         = React.useState('');
  const [saving, setSaving]     = React.useState(false);
  const [error, setError]       = React.useState(null);

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
        setError({ type: 'generic', message: body?.detail || `Error ${resp.status}` });
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
          <HFInput value={title} onChange={setTitle} placeholder="Book title" autoFocus/>
        </HFField>
        <HFField label="ISBN" hint="ISBN-10 or ISBN-13 — leave blank if unknown">
          <HFInput value={isbn} onChange={v => { setIsbn(v); setError(null); }}
                   placeholder="9780062316097" mono/>
        </HFField>
        <HFField label="Author">
          <HFInput value={author} onChange={setAuthor} placeholder="Firstname Lastname"/>
        </HFField>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px', gap: 12 }}>
          <HFField label="Publisher">
            <HFInput value={publisher} onChange={setPublisher} placeholder="Publisher name"/>
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

The existing `HFAddBookDialog` export at the bottom of `hf-overlays.jsx` stays unchanged.

**`onClose` contract:** called with `true` on success (triggers list refresh in callers) or `false` on cancel. Existing callers use `onClose={() => setAddBookOpen(false)}` — need to update to `onClose={(_created) => setAddBookOpen(false)}` so the boolean is ignored gracefully. No behavior change needed since books list is not auto-refreshed on dialog close in the current shell.

---

## Testing

### Integration tests (`tests/integration/test_books_api.py`)

```python
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
    # Verify persisted
    detail = client.get(f"/api/books/{data['id']}").json()
    assert detail["publisher"] == "Test Publisher"
    assert any(i["isbn"] == "9780062316097" for i in detail["isbns"])
    assert any(a["name"] == "Test Author" for a in detail["authors"])

def test_create_manual_book_blank_title_rejected(client):
    resp = client.post("/api/books", json={"title": ""})
    assert resp.status_code == 422

def test_create_manual_book_isbn_collision_returns_409(client, db_session):
    from book_scraper.db.models import Book, BookIsbn
    existing = Book(data_source="shop_inferred", title="Existing Book", year=2020)
    db_session.add(existing); db_session.flush()
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

---

## Notes

- `_looks_like_isbn` is already in `book_scraper/dashboard/queries.py` (added in Phase 1). Import it for ISBN normalization in the route.
- `_normalize_author` is private to `repo.py` (line 54). `create_manual_book` lives in the same file so can call it directly.
- `Publisher.name` has a UNIQUE constraint — `session.flush()` after adding a new Publisher to catch DB errors before the Book insert.
- On success, the dialog navigates to the new book's detail page via `window.HF_APP?.goto?.('book-detail', { id: data.id })`. `goto` is registered on `window.HF_APP` in `index.html` (see `app.py` handler or App component).
