# Book Detail Tabs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade HFBook from a single-card layout to a tabbed detail page with Listings (improved), Metadata, and stub Prices/Conflicts tabs.

**Architecture:** Pure frontend change to `hf-book.jsx`. Add `React.useState('listings')` tab state, wrap content below the hero card in `HFTabs` + conditional tab renders. Move subjects + description from hero card into Metadata tab. Listings tab improves the existing shops table with a "BEST" price badge. Metadata tab adds Contributors (authors by role) and a metadata field matrix. Prices and Conflicts are stubs.

**Tech Stack:** React 18 (Babel CDN), existing `HFTabs`, `HFTable`, `HFCard`, `HFPill`, `HFEmptyState` components. No API changes — all data from `/api/books/:id`.

**Spec:** `docs/superpowers/specs/2026-05-14-book-detail-tabs-design.md`

---

## File Structure

| File | Change |
|---|---|
| `book_scraper/dashboard/static/hifi/hf-book.jsx` | Add tab state, ShopMark helper, Contributors card, Metadata matrix, Prices/Conflicts stubs; move subjects+description; improve Listings table |

No new files. No backend changes.

---

## Task 1: Add tab state + HFTabs + ShopMark helper

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-book.jsx`

- [ ] **Step 1: Add `ShopMark` helper component above `HFBook`**

Add this just before the `function HFBook` declaration (after the existing `DataSourceBadge`):

```jsx
const SHOP_COLORS = ['var(--hf-accent)', '#0e7490', '#b45309', '#7c3aed', '#16a34a', '#6b7280'];

function ShopMark({ name, allShops }) {
  const idx = allShops ? allShops.indexOf(name) : 0;
  const color = SHOP_COLORS[Math.max(0, idx) % SHOP_COLORS.length];
  return (
    <span style={{
      display: 'inline-block',
      width: 10, height: 10,
      borderRadius: '50%',
      background: color === 'var(--hf-accent)' ? 'var(--hf-accent)' : color,
      flexShrink: 0,
    }} aria-hidden="true" />
  );
}
```

`allShops` is the ordered list of shop names so colors are stable and consistent across tabs.

- [ ] **Step 2: Add tab state inside `HFBook`**

Inside `function HFBook({ nav, goto, params })`, after the existing state declarations (`book`, `loading`, `error`), add:

```jsx
const [tab, setTab] = React.useState('listings');
```

- [ ] **Step 3: Derive helpers after book is loaded**

After the `if (error || !book)` guard, and after the existing `authorsByRole` computation, add:

```jsx
const shopNames = (book.shops || []).map(s => s.shop);
const prices = (book.shops || []).map(s => s.price).filter(p => p != null).map(Number);
const lowestPrice = prices.length ? Math.min(...prices) : null;
```

- [ ] **Step 4: Remove subjects + description from hero card**

In the hero card JSX, delete the entire `{/* Subjects */}` block and the entire `{/* Description */}` block. Both move to the Metadata tab in Task 4.

The hero card should end after the ISBNs + LIBIS chips block:
```jsx
      </HFCard>  {/* end hero card */}
```

- [ ] **Step 5: Add HFTabs below hero card**

Immediately after the closing tag of the hero `HFCard`, add:

```jsx
<HFCard style={{ marginBottom: 'var(--hf-gap)' }} padding={0}>
  <div style={{ padding: `0 var(--hf-card-p, 16px)` }}>
    <HFTabs
      active={tab}
      onChange={setTab}
      tabs={[
        { id: 'listings',  label: 'Listings',  count: (book.shops || []).length },
        { id: 'metadata',  label: 'Metadata' },
        { id: 'prices',    label: 'Prices' },
        { id: 'conflicts', label: 'Conflicts' },
      ]}
    />
  </div>
</HFCard>
```

- [ ] **Step 6: Add tab content dispatcher**

After the HFTabs card, replace the existing "Shop listings" HFCard block with:

```jsx
{tab === 'listings'  && <HFBookListings  book={book} shopNames={shopNames} lowestPrice={lowestPrice} goto={goto} />}
{tab === 'metadata'  && <HFBookMetadata  book={book} authorsByRole={authorsByRole} />}
{tab === 'prices'    && <HFBookPricesStub />}
{tab === 'conflicts' && <HFBookConflictsStub />}
```

- [ ] **Step 7: Rebuild and verify tabs render**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Open `http://localhost:8000/books/<any-id>`. Verify:
- Four tabs visible: Listings, Metadata, Prices, Conflicts.
- Clicking each switches active tab (underline moves).
- Listings count badge shows shop count.
- Hero card no longer shows subjects or description.

- [ ] **Step 8: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-book.jsx
git commit -m "feat(dashboard): add tab skeleton + ShopMark to HFBook"
```

---

## Task 2: Listings tab with BEST badge

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-book.jsx` (add `HFBookListings` component)

- [ ] **Step 1: Add `HFBookListings` component**

Add this function before `function HFBook`:

```jsx
function HFBookListings({ book, shopNames, lowestPrice, goto }) {
  const shops = book.shops || [];

  if (shops.length === 0) {
    return (
      <HFCard>
        <div style={{ padding: 20 }}>
          <HFEmptyState
            title="Not listed anywhere we track"
            sub="No shop listings have been linked to this canonical book yet."
          />
        </div>
      </HFCard>
    );
  }

  return (
    <HFCard
      title="Listings across shops"
      sub={`${shops.length} shop${shops.length !== 1 ? 's' : ''} · price, stock, last scrape`}
    >
      <HFTable
        columns={[
          { key: 'shop', label: 'Shop', w: '1.1fr', cell: (v) => (
            <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <ShopMark name={v} allShops={shopNames} />
              <span style={{ color: 'var(--hf-ink)', fontWeight: 500 }}>{v}</span>
            </span>
          )},
          { key: 'price', label: 'Price', w: '0.9fr', align: 'right', cell: (_, r) => {
            if (r.price == null) return <span style={{ color: 'var(--hf-ink4)' }}>—</span>;
            const n = Number(r.price);
            const isBest = lowestPrice != null && Math.abs(n - lowestPrice) < 0.001;
            return (
              <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6, justifyContent: 'flex-end' }}>
                <span style={{
                  fontFamily: 'var(--hf-mono)',
                  color: isBest ? 'var(--hf-ok-ink)' : 'var(--hf-ink)',
                  fontWeight: isBest ? 600 : 500,
                }}>
                  {new Intl.NumberFormat('lt-LT', { style: 'currency', currency: 'EUR' }).format(n)}
                </span>
                {isBest && (
                  <span style={{
                    fontSize: 10, color: 'var(--hf-ok-ink)',
                    fontWeight: 600, letterSpacing: 0.4,
                  }}>BEST</span>
                )}
              </span>
            );
          }},
          { key: 'delta', label: 'Δ 30d', w: '0.55fr', align: 'right',
            cell: () => <span style={{ color: 'var(--hf-ink4)', fontFamily: 'var(--hf-mono)' }}>—</span>
          },
          { key: 'in_stock', label: 'Stock', w: '0.7fr', cell: (v) => (
            v
              ? <HFPill tone="ok" soft>In stock</HFPill>
              : <HFPill tone="warn" soft>Out</HFPill>
          )},
          { key: 'last_seen_at', label: 'Last scrape', w: '0.85fr', cell: (v) =>
            v
              ? <time dateTime={v}>{formatRelative(v)}</time>
              : <span style={{ color: 'var(--hf-ink4)' }}>—</span>
          },
          { key: 'url', label: '', w: '90px', align: 'right', cell: (v, r) =>
            v
              ? <a
                  href={v}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Open at ${r.shop} (new tab)`}
                  title={`Open at ${r.shop}`}
                  style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    minWidth: 32, minHeight: 32, padding: '0 8px',
                    color: 'var(--hf-accent-ink)',
                    fontFamily: 'var(--hf-mono)', fontSize: 11,
                    textDecoration: 'none',
                  }}
                >Visit ↗</a>
              : '—'
          },
        ]}
        rows={shops}
      />
    </HFCard>
  );
}
```

- [ ] **Step 2: Rebuild and verify Listings tab**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Open a book with multiple shops. On the Listings tab verify:
- All shops listed with price (locale-formatted: `1,99 €`).
- Cheapest shop has price in green + "BEST" badge.
- Δ 30d column shows "—" for all rows (placeholder).
- Stock pills correct.
- Last scrape shows relative time ("5h ago").
- Visit ↗ opens the shop URL.

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-book.jsx
git commit -m "feat(dashboard): Listings tab with BEST price badge"
```

---

## Task 3: Prices and Conflicts stub tabs

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-book.jsx` (add 2 stub components)

- [ ] **Step 1: Add stub components**

Add these two functions before `function HFBook`:

```jsx
function HFBookPricesStub() {
  return (
    <HFCard title="Price history" sub="Coming in a future release">
      <div style={{ padding: 32 }}>
        <HFEmptyState
          title="Price history not yet available"
          sub="Once the price history endpoint is added, this tab will show per-shop price trends over time."
        />
      </div>
    </HFCard>
  );
}

function HFBookConflictsStub() {
  return (
    <HFCard title="Conflicts" sub="Coming in a future release">
      <div style={{ padding: 32 }}>
        <HFEmptyState
          title="Conflict detection not yet available"
          sub="This tab will highlight fields that differ between the canonical record and individual shop listings."
        />
      </div>
    </HFCard>
  );
}
```

- [ ] **Step 2: Rebuild and verify stubs**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Click the Prices tab → empty state with "Price history not yet available".
Click the Conflicts tab → empty state with "Conflict detection not yet available".

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-book.jsx
git commit -m "feat(dashboard): Prices + Conflicts stub tabs"
```

---

## Task 4: Metadata tab — Contributors + field matrix

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-book.jsx` (add `HFBookMetadata` component with Contributors and matrix)

- [ ] **Step 1: Add `HFBookMetadata` component**

Add this function before `function HFBook`:

```jsx
function HFBookMetadata({ book, authorsByRole }) {
  // Ordered role labels for Contributors card.
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
  // Collect roles: known-order first, then any extras.
  const extraRoles = Object.keys(authorsByRole).filter(r => !roleOrder.includes(r));
  const allRoles = [...roleOrder, ...extraRoles].filter(r => (authorsByRole[r] || []).length > 0);

  // Metadata field rows: [label, value] — skip nullish.
  const fields = [
    ['Year',           book.year],
    ['Publisher',      book.publisher],
    ['Format',         book.format],
    ['Language',       book.language],
    ['Pages',          book.pages ? `${book.pages} p.` : null],
    ['Duration',       book.duration],
    ['Type',           book.type],
    ['Audience',       book.audience],
    ['Series',         book.series],
    ['Release place',  book.release_place],
    ['UDC codes',      (book.udc_codes || []).join(', ') || null],
    ['Translated from',book.translated_from],
    ['Dimensions',     book.dimensions],
    ['LIBIS code',     book.libis_code],
    ['Data source',    book.data_source],
    ['Subjects',       (book.subjects || []).join(' · ') || null],
    ['Description',    book.description],
  ].filter(([, v]) => v != null && v !== '');

  return (
    <>
      {/* Contributors card */}
      <HFCard
        title="Contributors"
        sub="author, translator, narrator, editor, and other credited roles"
        style={{ marginBottom: 'var(--hf-gap)' }}
      >
        {allRoles.length === 0 ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--hf-ink3)' }}>
            No contributor data.
          </div>
        ) : (
          <div style={{ padding: '4px 0' }}>
            {allRoles.map((role, i) => (
              <div key={role} style={{
                display: 'grid',
                gridTemplateColumns: '160px 1fr',
                padding: '10px 20px',
                borderBottom: i < allRoles.length - 1
                  ? '1px solid var(--hf-border-faint)' : 'none',
                fontSize: 13,
                alignItems: 'baseline',
              }}>
                <span style={{ color: 'var(--hf-ink3)', fontWeight: 500 }}>
                  {ROLE_LABELS[role] || role.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                </span>
                <span style={{ color: 'var(--hf-ink)' }}>
                  {authorsByRole[role].join(', ')}
                </span>
              </div>
            ))}
          </div>
        )}
      </HFCard>

      {/* Metadata matrix card */}
      <HFCard title="Metadata" sub="fields from the canonical record">
        {fields.length === 0 ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--hf-ink3)' }}>
            No metadata.
          </div>
        ) : (
          <div style={{ padding: '4px 0' }}>
            {fields.map(([label, value], i) => (
              <div key={label} style={{
                display: 'grid',
                gridTemplateColumns: '160px 1fr',
                padding: '10px 20px',
                borderBottom: i < fields.length - 1
                  ? '1px solid var(--hf-border-faint)' : 'none',
                fontSize: 13,
                alignItems: 'baseline',
                background: i % 2 === 0 ? 'transparent' : 'var(--hf-subtle)',
              }}>
                <span style={{ color: 'var(--hf-ink3)', fontWeight: 500 }}>{label}</span>
                <span style={{ color: 'var(--hf-ink)', lineHeight: 1.5 }}>
                  {label === 'LIBIS code'
                    ? <span style={{
                        fontFamily: 'var(--hf-mono)', fontSize: 11,
                        padding: '2px 7px', borderRadius: 4,
                        background: 'var(--hf-subtle)',
                        border: '1px solid var(--hf-border)',
                        color: 'var(--hf-ink3)',
                      }}>{value}</span>
                    : label === 'Data source'
                      ? <DataSourceBadge value={book.data_source} />
                      : String(value)
                  }
                </span>
              </div>
            ))}
          </div>
        )}
      </HFCard>
    </>
  );
}
```

- [ ] **Step 2: Rebuild and verify Metadata tab**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Open a book with authors. On Metadata tab verify:
- Contributors card shows "Author", "Translated by", etc. rows — only roles present in data.
- Book with no authors shows "No contributor data."
- Metadata matrix shows Year, Publisher, Language, etc. — only non-null fields.
- LIBIS code shown in monospace chip.
- Subjects and description appear in matrix (moved from hero card).
- Alternating row backgrounds (subtle stripe).

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-book.jsx
git commit -m "feat(dashboard): Metadata tab — Contributors + field matrix"
```

---

## Task 5: Final smoke

- [ ] **Step 1: Test a book with shops + a book without shops**

Open `http://localhost:8000/books` → pick a book with shops → Listings tab shows rows with BEST badge.
Open a book with no shops → Listings tab shows "Not listed anywhere we track."

- [ ] **Step 2: Test a book with authors + a book without**

Book with authors → Metadata tab shows Contributors with role rows.
Book with no authors → "No contributor data."

- [ ] **Step 3: Verify no console errors**

Open browser DevTools → Console. Navigate through all 4 tabs. No errors.

- [ ] **Step 4: Run smoke tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py tests/integration/test_books_api.py -q
```

Expected: all pass (no backend change, just frontend).

---

## Notes for the implementer

- **`authorsByRole`** is already computed in `HFBook` and passed as a prop to `HFBookMetadata`. It's a plain object `{ author: ['Name1'], translator: ['Name2'], ... }`.
- **`formatRelative`** and **`formatEur`** are already defined at the top of `hf-book.jsx` (from Phase 1). Reuse directly.
- **`DataSourceBadge`** is already defined at the top of `hf-book.jsx`. Reuse directly.
- **Docker BuildKit cache gotcha:** if changes don't appear, confirm: `docker exec book-scraper-dashboard-1 grep -c 'HFBookListings' /app/book_scraper/dashboard/static/hifi/hf-book.jsx`. If 0, rebuild with `--no-cache`.
- **HFTabs** is exported from `hf-ui.jsx` and available globally — no import needed (all files are global Babel scripts).
- **No backend changes needed** — all data from `/api/books/:id` which already returns `authors`, `subjects`, `description`, `udc_codes`, `series`, etc.
