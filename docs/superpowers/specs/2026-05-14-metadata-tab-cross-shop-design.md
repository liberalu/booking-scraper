# Metadata Tab Cross-Shop Comparison — Design Spec

**Status:** Implemented
## Goal

Upgrade the Metadata tab on the canonical Book detail page from showing only canonical field values to showing a full cross-shop comparison matrix: per-shop Contributors table (Author row uses raw `ShopBook.author`; other roles use canonical data with `—` for shops) and per-field per-shop metadata matrix with conflict detection.

## Scope

- Extend `book_detail` query in `book_scraper/dashboard/queries.py` to include per-shop metadata fields (`title`, `author`, `isbn`, `publisher`, `year`, `format`, `match_method`, `shop_book_id`)
- Replace the current `HFBookMetadata` component body in `book_scraper/dashboard/static/hifi/hf-book.jsx` with the cross-shop matrix version
- Integration test: verify the new shop fields are present in `/api/books/:id` response
- No new endpoints. No schema changes.

## Non-Goals

- Per-shop Translator/Editor/Cover artist data (shops don't provide role-separated contributors)
- `ShopBookAuthor → ShopAuthor` join (expensive, sparse data)
- Merge or unlink actions from this view (Phase 4)
- Pages comparison (not a direct `ShopBook` column)

---

## Backend

### Extend `book_detail` shops SELECT in `queries.py`

Replace the current minimal SELECT with a richer one that also returns per-shop metadata:

```python
shops = session.execute(
    select(
        Shop.name,
        ShopBook.id.label("shop_book_id"),
        ShopBook.url,
        ShopBook.price,
        ShopBook.in_stock,
        ShopBook.last_seen_at,
        ShopBook.title.label("shop_title"),
        ShopBook.author.label("shop_author"),
        ShopBook.year.label("shop_year"),
        ShopBook.isbn.label("shop_isbn"),
        ShopBook.publisher.label("shop_publisher"),
        ShopBook.format.label("shop_format"),
        ShopBook.match_method,
    )
    .join(ShopBook, ShopBook.shop_id == Shop.id)
    .where(ShopBook.book_id == book_id)
    .order_by(Shop.name)
).all()
```

Map each row to a dict in the response:

```python
{
    "shop":         row.name,
    "shop_book_id": row.shop_book_id,
    "url":          row.url,
    "price":        str(row.price) if row.price else None,
    "in_stock":     row.in_stock,
    "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
    "title":        row.shop_title,
    "author":       row.shop_author,
    "year":         row.shop_year,
    "isbn":         row.shop_isbn,
    "publisher":    row.shop_publisher,
    "format":       row.shop_format,
    "match_method": row.match_method,
}
```

This is a backwards-compatible extension — all new fields are nullable, existing consumers that read `shop`, `price`, `in_stock`, `url`, `last_seen_at` are unaffected.

---

## Frontend — replace `HFBookMetadata`

`HFBookMetadata({ book, authorsByRole })` in `hf-book.jsx` currently renders two simple cards (Contributors list + metadata field list with only canonical values). Replace the entire function with a version that renders the cross-shop comparison matrices.

### Data preparation (inside `HFBookMetadata`)

```js
const shops = book.shops || [];
const shopNames = shops.map(s => s.shop);

// Primary canonical author name (for conflict comparison)
const canonicalAuthor = (authorsByRole.author || [])[0] || null;

// ISBN-13 from canonical isbns[]
const canonicalIsbn13 = (book.isbns || []).find(i => i.isbn.length === 13)?.isbn || null;
```

### Conflict detection helpers

```js
const norm = s => (s || '').trim().toLowerCase();
const isConflict = (shopVal, canonVal) =>
  shopVal != null && canonVal != null && norm(shopVal) !== norm(String(canonVal));
const isMissing = shopVal => shopVal == null || shopVal === '';
```

### Card 1 — Contributors

Renders a horizontally scrollable table: rows = roles, columns = Canonical + one per shop.

Only render roles that have canonical data (`authorsByRole[role]?.length > 0`). Roles in order: `author`, `translator`, `narrator`, `editor`, `illustrator`, `cover_artist`, `producer`.

**Author row** (the only row where shops provide data):
- Canonical cell: canonical author names joined with `', '`
- Shop cell: `shop.author` — if it normalises to match the canonical author → ✓ (grey); if different non-null value → ⚠ (orange, show shop value); if null → `—`

**All other role rows** (Translator, Editor etc.):
- Canonical cell: `authorsByRole[role].join(', ')`
- Shop cells: always `—` (shops don't provide role-separated contributors)

Row style: 12px grid, alternating `var(--hf-subtle)`. Conflict cell: `color: var(--hf-warn-ink)` with a `!` warning badge. Shop column header: `ShopMark` (colored dot) + shop name, truncated.

### Card 2 — Canonical metadata · per shop

Renders a horizontally scrollable table: rows = fields, columns = Field label + Canonical + one per shop.

Fields and conflict logic:

| Field | Canonical source | Shop source | Conflict if |
|---|---|---|---|
| Title | `book.title` | `shop.title` | `norm(shop.title) !== norm(book.title)` |
| Author | primary canonical author | `shop.author` | `norm(shop.author) !== norm(canonicalAuthor)` |
| Year | `book.year` | `shop.year` | `shop.year !== book.year` |
| Publisher | `book.publisher` | `shop.publisher` | `norm(shop.publisher) !== norm(book.publisher)` |
| ISBN-13 | canonical ISBN-13 | `shop.isbn` (normalised) | `shop.isbn (normalised) !== canonicalIsbn13` |
| Format | `book.format` | `shop.format` | `norm(shop.format) !== norm(book.format)` |

Only render rows where the canonical value exists. Skip rows where `book.year == null`, `book.publisher == null`, etc.

Row summary (below field label, muted 11px monospace):
- Count shops providing the field: `N of M`
- If any conflict: `· K conflict` in `var(--hf-warn-ink)`

Cell rendering:
- ✓ match: `var(--hf-ink3)` text, checkmark icon or just the value in muted style
- ⚠ conflict: `var(--hf-warn-ink)`, show `⚠ <shop_value>` (truncated with `title` tooltip for full value)
- `—`: `var(--hf-ink5)`, italic

Table is horizontally scrollable (`overflow-x: auto`) with `min-width` on each shop column (140px).

### No prop change needed

The dispatcher stays unchanged:
```jsx
{tab === 'metadata' && <HFBookMetadata book={book} authorsByRole={authorsByRole} />}
```

`book.shops` is already on the `book` object passed to the component — the new matrix code reads it directly via `const shops = book.shops || []`.

---

## Testing

### Integration test (append to `tests/integration/test_books_api.py`)

```python
def test_book_detail_shops_include_metadata_fields(client, db_session):
    from decimal import Decimal
    from book_scraper.db.models import Book, Shop, ShopBook
    from sqlalchemy import select

    shop = db_session.execute(
        select(Shop).where(Shop.name == "vaga")
    ).scalar_one_or_none()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt")
        db_session.add(shop); db_session.flush()

    book = Book(data_source="shop_inferred", title="Meta Test Book", year=2022)
    db_session.add(book); db_session.flush()

    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/meta-test",
        title="Meta Test Book", author="Test Author",
        isbn="9780062316097", publisher="Test Press",
        year=2022, format="Paperback",
        price=Decimal("15.00"), in_stock=True,
        book_id=book.id,
    )
    db_session.add(sb); db_session.commit()

    resp = client.get(f"/api/books/{book.id}")
    assert resp.status_code == 200
    shops = resp.json()["shops"]
    assert len(shops) == 1
    s = shops[0]
    assert s["title"] == "Meta Test Book"
    assert s["author"] == "Test Author"
    assert s["isbn"] == "9780062316097"
    assert s["publisher"] == "Test Press"
    assert s["year"] == 2022
    assert s["format"] == "Paperback"
    assert "shop_book_id" in s
```

### Manual browser verification

Open any book with multiple shops on `/books/:id` → click Metadata tab. Verify:
- Contributors card shows Author row with per-shop values; other roles show canonical only with `—` for shop columns
- Metadata matrix shows Title/Author/Year/Publisher/ISBN-13 rows with per-shop cells
- Conflicts shown in orange (find a book where patogu/humanitas has a different title or year)
- Tables scroll horizontally when many shops

---

## Notes

- `ShopBook.title`, `author`, `isbn`, `publisher`, `year`, `format` are all nullable (except `title`). Missing values render as `—`.
- `match_method` is included in the shops dict but not shown in the Metadata tab — it will be used in a future "Listings" tab enrichment (showing how the match was established).
- `ShopMark` (colored dot per shop) is already defined in `hf-book.jsx` from the Listings tab work. Reuse it.
- Tables use `overflow-x: auto` with `white-space: nowrap` on cells, `minWidth: 140` per shop column.
- The `norm()` helper lowercases and trims for comparison — not a full fuzzy match. "Kitos knygos" vs "Kitos knygos studio" would show as a conflict, which is correct.
