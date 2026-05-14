# Metadata Tab Cross-Shop Comparison — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Metadata tab on the canonical Book detail page to show cross-shop comparison matrices (Contributors per role + field-by-field metadata) with conflict detection highlighting.

**Architecture:** Extend `book_detail` in `queries.py` to include per-shop metadata fields from `ShopBook` (title, author, year, isbn, publisher, format, match_method). Replace the current `HFBookMetadata` in `hf-book.jsx` with two horizontally-scrollable cross-shop tables. Conflict detection is purely client-side: compare each shop's field value against the canonical value using case-insensitive trimmed comparison.

**Tech Stack:** Python/SQLAlchemy for the backend query change; React 18 Babel CDN for the frontend. No new endpoints. No schema changes.

**Spec:** `docs/superpowers/specs/2026-05-14-metadata-tab-cross-shop-design.md`

---

## File Structure

| File | Change |
|---|---|
| `book_scraper/dashboard/queries.py` | Extend `book_detail` shops SELECT + update dict construction (lines ~2856–2905) |
| `tests/integration/test_books_api.py` | Append 1 integration test |
| `book_scraper/dashboard/static/hifi/hf-book.jsx` | Replace `HFBookMetadata` function (lines ~143–240) |

---

## Task 1: Extend `book_detail` shops with per-shop metadata (TDD)

**Files:**
- Modify: `book_scraper/dashboard/queries.py` (around line 2856)
- Test: `tests/integration/test_books_api.py` (append)

- [ ] **Step 1: Append failing integration test**

Open `tests/integration/test_books_api.py` and append at the end:

```python
def test_book_detail_shops_include_metadata_fields(client, db_session):
    from decimal import Decimal

    from sqlalchemy import select

    from book_scraper.db.models import Book, Shop, ShopBook

    shop = db_session.execute(
        select(Shop).where(Shop.name == "vaga")
    ).scalar_one_or_none()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt")
        db_session.add(shop)
        db_session.flush()

    book = Book(data_source="shop_inferred", title="Meta Test Book", year=2022)
    db_session.add(book)
    db_session.flush()

    sb = ShopBook(
        shop_id=shop.id,
        url="https://vaga.lt/meta-test",
        title="Meta Test Book",
        author="Test Author",
        isbn="9780062316097",
        publisher="Test Press",
        year=2022,
        format="Paperback",
        price=Decimal("15.00"),
        in_stock=True,
        book_id=book.id,
    )
    db_session.add(sb)
    db_session.commit()

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

- [ ] **Step 2: Run test — confirm FAIL**

```
uv run pytest tests/integration/test_books_api.py::test_book_detail_shops_include_metadata_fields -v 2>&1 | tail -8
```

Expected: FAIL — `s["title"]` KeyError (field not returned yet).

- [ ] **Step 3: Extend shops SELECT in `book_detail`**

Open `book_scraper/dashboard/queries.py`. Find the shops SELECT around line 2856:

```python
shops = session.execute(
    select(
        Shop.name,
        ShopBook.url,
        ShopBook.price,
        ShopBook.in_stock,
        ShopBook.last_seen_at,
    )
    .join(ShopBook, ShopBook.shop_id == Shop.id)
    .where(ShopBook.book_id == book_id)
    .order_by(Shop.name)
).all()
```

Replace with:

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

- [ ] **Step 4: Update shops dict construction**

Find the shops dict comprehension in the same function (the `"shops": [...]` block). Replace it with:

```python
"shops": [
    {
        "shop":         row.name,
        "shop_book_id": row.shop_book_id,
        "url":          row.url,
        "price":        str(row.price) if row.price is not None else None,
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
    for row in shops
],
```

Note: the old comprehension used positional tuple unpacking (`for shop, url, price, in_stock, last_seen in shops`). The new one uses `for row in shops` with named attribute access. Make sure to remove the old comprehension entirely.

- [ ] **Step 5: Run the test — confirm PASS**

```
uv run pytest tests/integration/test_books_api.py::test_book_detail_shops_include_metadata_fields -v 2>&1 | tail -8
```

Expected: PASS.

- [ ] **Step 6: Full books_api suite — no regressions**

```
uv run pytest tests/integration/test_books_api.py -q 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add book_scraper/dashboard/queries.py tests/integration/test_books_api.py
git commit -m "feat(api): book_detail shops include per-shop metadata fields for cross-shop comparison"
```

---

## Task 2: Replace `HFBookMetadata` with cross-shop matrices

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-book.jsx` (replace `HFBookMetadata`, lines ~143–242)

- [ ] **Step 1: Read the file to locate `HFBookMetadata`**

Open `book_scraper/dashboard/static/hifi/hf-book.jsx`. Find `function HFBookMetadata` (around line 143). It ends around line 242 just before `function HFBookListings`. You will replace the entire function.

- [ ] **Step 2: Replace `HFBookMetadata` with the cross-shop version**

Delete the entire `HFBookMetadata` function and replace with:

```jsx
function HFBookMetadata({ book, authorsByRole }) {
  const shops = book.shops || [];
  const shopNames = shops.map(s => s.shop);

  // Conflict detection helpers (case-insensitive, trimmed)
  const norm = s => (s == null ? '' : String(s).trim().toLowerCase());
  const hasConflict = (shopVal, canonVal) =>
    shopVal != null && shopVal !== '' &&
    canonVal != null && canonVal !== '' &&
    norm(shopVal) !== norm(String(canonVal));
  const isMissing = v => v == null || v === '';

  // Primary canonical author name (for cross-shop comparison)
  const canonicalAuthor = (authorsByRole.author || [])[0] || null;

  // Canonical ISBN-13
  const canonicalIsbn13 = (book.isbns || []).find(i => String(i.isbn).length === 13)?.isbn || null;

  // Roles to show in Contributors card
  const ROLE_LABELS = {
    author:       'Author',
    translator:   'Translated by',
    narrator:     'Narrated by',
    editor:       'Edited by',
    illustrator:  'Illustrated by',
    cover_artist: 'Cover by',
    producer:     'Produced by',
  };
  const roleOrder = ['author', 'translator', 'narrator', 'editor',
                     'illustrator', 'cover_artist', 'producer'];
  const extraRoles = Object.keys(authorsByRole).filter(r => !roleOrder.includes(r));
  const allRoles = [...roleOrder, ...extraRoles]
    .filter(r => (authorsByRole[r] || []).length > 0);

  // Metadata matrix rows: [label, canonVal, shopValueFn, conflictFn]
  const matrixRows = [
    { label: 'Title',    canonical: book.title,     shopVal: s => s.title,
      conflict: s => hasConflict(s.title, book.title) },
    { label: 'Author',   canonical: canonicalAuthor, shopVal: s => s.author,
      conflict: s => hasConflict(s.author, canonicalAuthor) },
    { label: 'Year',     canonical: book.year,       shopVal: s => s.year,
      conflict: s => s.year != null && book.year != null && s.year !== book.year },
    { label: 'Publisher',canonical: book.publisher,  shopVal: s => s.publisher,
      conflict: s => hasConflict(s.publisher, book.publisher) },
    { label: 'ISBN-13',  canonical: canonicalIsbn13, shopVal: s => s.isbn,
      conflict: s => s.isbn != null && canonicalIsbn13 != null &&
                     s.isbn.replace(/-/g,'') !== canonicalIsbn13.replace(/-/g,'') },
    { label: 'Format',   canonical: book.format,    shopVal: s => s.format,
      conflict: s => hasConflict(s.format, book.format) },
  ].filter(row => row.canonical != null && row.canonical !== '');

  const colW = 140;
  const headerStyle = {
    display: 'grid',
    gridTemplateColumns: `160px 200px repeat(${shopNames.length}, ${colW}px)`,
    padding: '8px 20px',
    background: 'var(--hf-subtle)',
    borderBottom: '1px solid var(--hf-border)',
    fontSize: 11, fontWeight: 600, color: 'var(--hf-ink3)',
    textTransform: 'uppercase', letterSpacing: 0.5,
    position: 'sticky', top: 0, zIndex: 1,
  };
  const shopHeaderStyle = {
    display: 'flex', alignItems: 'center', gap: 6,
    textTransform: 'none', letterSpacing: 0, fontWeight: 600,
    color: 'var(--hf-ink2)', fontSize: 11.5,
    overflow: 'hidden',
  };

  return (
    <>
      {/* Card 1 — Contributors */}
      <HFCard
        title="Contributors"
        sub="author, translator, narrator and other credited roles — shops only provide raw author string"
        style={{ marginBottom: 'var(--hf-gap)' }}
        flush
      >
        <div style={{ overflowX: 'auto' }} className="hf-scroll">
          <div style={{ minWidth: 160 + 200 + shopNames.length * colW }}>
            {/* Header */}
            <div style={headerStyle}>
              <span>Role</span>
              <span>Canonical</span>
              {shopNames.map((name, i) => (
                <span key={name} style={shopHeaderStyle}>
                  <ShopMark name={name} allShops={shopNames} />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
                </span>
              ))}
            </div>

            {/* Role rows */}
            {allRoles.length === 0 ? (
              <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--hf-ink3)' }}>
                No contributor data.
              </div>
            ) : allRoles.map((role, i) => (
              <div key={role} style={{
                display: 'grid',
                gridTemplateColumns: `160px 200px repeat(${shopNames.length}, ${colW}px)`,
                padding: '9px 20px',
                borderBottom: i < allRoles.length - 1 ? '1px solid var(--hf-border-faint)' : 'none',
                fontSize: 12, alignItems: 'center',
              }}>
                {/* Role label */}
                <span style={{ color: 'var(--hf-ink)', fontWeight: 600, fontSize: 12.5 }}>
                  {ROLE_LABELS[role] || role.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                </span>
                {/* Canonical value */}
                <span style={{ color: 'var(--hf-ink2)', fontWeight: 500,
                               overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                               paddingRight: 12 }}>
                  {authorsByRole[role].join(', ')}
                </span>
                {/* Per-shop cells */}
                {shopNames.map(name => {
                  const shop = shops.find(s => s.shop === name);
                  // Only Author row shows shop data; all other roles are canonical-only
                  if (role !== 'author') {
                    return <span key={name} style={{ color: 'var(--hf-ink5)', fontSize: 11.5, fontFamily: 'var(--hf-mono)' }}>—</span>;
                  }
                  const val = shop?.author;
                  if (isMissing(val)) {
                    return <span key={name} style={{ color: 'var(--hf-ink5)', fontSize: 11.5, fontFamily: 'var(--hf-mono)' }}>—</span>;
                  }
                  const conflict = hasConflict(val, canonicalAuthor);
                  return (
                    <span key={name} title={val} style={{
                      display: 'flex', alignItems: 'center', gap: 5,
                      color: conflict ? 'var(--hf-warn-ink)' : 'var(--hf-ink2)',
                      fontSize: 11.5,
                      overflow: 'hidden',
                    }}>
                      {conflict && (
                        <span style={{
                          width: 14, height: 14, borderRadius: 3,
                          background: 'var(--hf-warn-soft)', border: '1px solid var(--hf-warn-border)',
                          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 9, fontWeight: 700, flexShrink: 0,
                        }}>!</span>
                      )}
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{val}</span>
                    </span>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </HFCard>

      {/* Card 2 — Metadata matrix */}
      <HFCard
        title="Canonical metadata · per shop"
        sub="each row is a field · ✓ = matches canonical · ⚠ = conflict · — = not provided"
        flush
      >
        <div style={{ overflowX: 'auto' }} className="hf-scroll">
          <div style={{ minWidth: 160 + 200 + shopNames.length * colW }}>
            {/* Header */}
            <div style={headerStyle}>
              <span>Field</span>
              <span>Canonical</span>
              {shopNames.map((name, i) => (
                <span key={name} style={shopHeaderStyle}>
                  <ShopMark name={name} allShops={shopNames} />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
                </span>
              ))}
            </div>

            {matrixRows.length === 0 ? (
              <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--hf-ink3)' }}>
                No metadata.
              </div>
            ) : matrixRows.map((row, i) => {
              const conflictCount = shops.filter(s => row.conflict(s)).length;
              const missingCount  = shops.filter(s => isMissing(row.shopVal(s))).length;
              const providedCount = shops.length - missingCount;
              const summaryParts = [`${providedCount} of ${shops.length}`];
              if (missingCount > 0) summaryParts.push(`${missingCount} missing`);
              if (conflictCount > 0) summaryParts.push(`${conflictCount} conflict`);

              return (
                <div key={row.label} style={{
                  display: 'grid',
                  gridTemplateColumns: `160px 200px repeat(${shopNames.length}, ${colW}px)`,
                  padding: '10px 20px',
                  borderBottom: i < matrixRows.length - 1 ? '1px solid var(--hf-border-faint)' : 'none',
                  fontSize: 12, alignItems: 'center',
                }}>
                  {/* Field label + summary */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ color: 'var(--hf-ink)', fontWeight: 600, fontSize: 12.5 }}>{row.label}</span>
                    <span style={{
                      fontSize: 10.5, fontFamily: 'var(--hf-mono)',
                      color: conflictCount > 0 ? 'var(--hf-warn-ink)' : 'var(--hf-ink4)',
                    }}>
                      {summaryParts.join(' · ')}
                    </span>
                  </div>

                  {/* Canonical value */}
                  <span style={{
                    color: 'var(--hf-ink)', fontWeight: 500,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    paddingRight: 12, fontSize: 12.5,
                  }}>
                    {String(row.canonical)}
                  </span>

                  {/* Per-shop cells */}
                  {shopNames.map(name => {
                    const shop = shops.find(s => s.shop === name);
                    const val  = shop ? row.shopVal(shop) : null;
                    if (isMissing(val)) {
                      return (
                        <span key={name} style={{ color: 'var(--hf-ink5)', fontSize: 11.5, fontFamily: 'var(--hf-mono)' }}>—</span>
                      );
                    }
                    const conflict = shop && row.conflict(shop);
                    return (
                      <span key={name} title={String(val)} style={{
                        display: 'flex', alignItems: 'center', gap: 5,
                        color: conflict ? 'var(--hf-warn-ink)' : 'var(--hf-ink3)',
                        fontSize: 11.5, overflow: 'hidden',
                      }}>
                        {conflict ? (
                          <span style={{
                            width: 14, height: 14, borderRadius: 3,
                            background: 'var(--hf-warn-soft)', border: '1px solid var(--hf-warn-border)',
                            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                            fontSize: 9, fontWeight: 700, flexShrink: 0,
                          }}>!</span>
                        ) : (
                          <span style={{ color: 'var(--hf-ok-ink)', fontWeight: 600, fontSize: 10, flexShrink: 0 }}>✓</span>
                        )}
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {conflict ? String(val) : 'match'}
                        </span>
                      </span>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </HFCard>
    </>
  );
}
```

- [ ] **Step 3: Rebuild dashboard**

```bash
HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" ALL_PROXY="" all_proxy="" docker compose build dashboard && docker compose up -d dashboard
```

- [ ] **Step 4: Verify in container**

```bash
docker exec book-scraper-dashboard-1 grep -c 'matrixRows\|conflictCount\|shopNames' /app/book_scraper/dashboard/static/hifi/hf-book.jsx
```

Expected: 3+

- [ ] **Step 5: Manual verification in browser**

Open `http://localhost:8000/books` → pick a book that has 2+ shops linked.

On the **Metadata** tab verify:
1. **Contributors card** shows a multi-column table with shop names as headers and colored dots.
2. The Author row shows per-shop author values; rows like Translator show `—` for all shop columns.
3. Any shop whose author string differs from canonical appears in orange with `!` badge.
4. **Metadata matrix card** shows Title/Author/Year/Publisher/ISBN-13/Format rows with per-shop cells.
5. Matching shops show `✓ match` in muted green; conflicting shops show `⚠ <value>` in orange.
6. Row summary below field label shows "N of M · K conflict/missing" counts.
7. Both tables scroll horizontally if many shops.

To find a book with conflicts: navigate to `/books?search=Sapiens` or any well-known title that multiple shops carry with slightly different metadata (e.g. short publisher names, variant title spelling).

- [ ] **Step 6: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-book.jsx
git commit -m "feat(dashboard): Metadata tab — cross-shop Contributors + field matrix with conflict detection"
```

---

## Task 3: Final smoke

- [ ] **Step 1: Full test suite**

```bash
uv run pytest tests/ -q --tb=no 2>&1 | tail -4
```

Expected: 820+ passing.

- [ ] **Step 2: API field presence spot check**

```bash
BOOK_ID=$(curl -s 'http://localhost:8000/api/books?has_shops=true&per_page=1' \
  | python3 -c "import json,sys; b=json.load(sys.stdin)['books']; print(b[0]['id'] if b else 'none')")
curl -s "http://localhost:8000/api/books/$BOOK_ID" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); s=d['shops'][0] if d['shops'] else {}; print('shop fields:', sorted(s.keys()))"
```

Expected: output includes `title`, `author`, `year`, `isbn`, `publisher`, `format`, `shop_book_id`, `match_method`.

---

## Notes for the implementer

- **`ShopMark`** is already defined in `hf-book.jsx` (from the Listings tab). Use it directly — no import needed.
- **`hf-scroll`** CSS class — the dashboard uses this class on scrollable containers. If it does not provide `overflow-x: auto`, add `style={{ overflowX: 'auto' }}` on the wrapper div instead (the plan already includes it).
- **`flush` prop on `HFCard`** — removes inner padding so the table rows go edge-to-edge. Already used by other cards in the codebase.
- **`sticky` header** — the `position: sticky; top: 0; zIndex: 1` on the header row works inside the scrollable `div`, not relative to the viewport. It stays visible as the user scrolls the table.
- **Docker BuildKit cache** — if changes don't appear after rebuild, check: `docker exec book-scraper-dashboard-1 grep -c 'matrixRows' /app/book_scraper/dashboard/static/hifi/hf-book.jsx`. If 0, rebuild with `--no-cache`.
- **Books with 0 shops** — if `book.shops` is empty, both cards render their respective empty states ("No contributor data." / "No metadata.").
