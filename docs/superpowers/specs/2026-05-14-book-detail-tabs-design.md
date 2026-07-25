# Book Detail Tabs — Design Spec

**Status:** Implemented
## Goal

Upgrade `HFBook` from a single-card layout to a tabbed detail page. Add Listings (improved), Metadata, and stub Prices/Conflicts tabs. No backend changes — all data comes from the existing `/api/books/:id` response.

## Scope

- One file changed: `book_scraper/dashboard/static/hifi/hf-book.jsx`
- No API changes, no new endpoints
- Design reference: `hifi/hf-book.jsx` in `Test design (1)/` folder — adapted for option B (no Re-match/Unlink, no price history, no conflict detection)

## Non-Goals

- Re-match / Unlink shop_book actions (Phase 4)
- Price history chart (needs new API endpoint)
- Conflict detection (needs new API endpoint)
- Match metadata columns in Listings (matched-at, method, confidence)
- Any change to the hero card (cover, title, authors, ISBNs — already polished in Phase 1)

---

## Layout

```
┌─────────────────────────────────────────────────────────┐
│  Hero card (unchanged)                                   │
│  Cover · title · authors · meta · ISBNs · subjects ·    │
│  description                                            │
└─────────────────────────────────────────────────────────┘

[Listings]  [Metadata]  [Prices]  [Conflicts]
   ↑ default active

┌─────────────────────────────────────────────────────────┐
│  Tab content                                             │
└─────────────────────────────────────────────────────────┘
```

Tab state is local (`React.useState('listings')`). No URL persistence for tab in Phase 2 (add if needed later).

---

## Tab: Listings (default)

Replaces the current "Available at" card. Shows one row per shop.

**Columns:**

| Key | Label | Width | Notes |
|---|---|---|---|
| `shop` | Shop | 1.1fr | Shop name with colored dot (`ShopMark`) |
| `price` | Price | 0.8fr | `Intl.NumberFormat('lt-LT', {style:'currency',currency:'EUR'})`. Lowest price gets `BEST` badge in `var(--hf-ok-ink)`, weight 600. |
| `delta` | Δ 30d | 0.55fr | Stub `—` for now (no price history). |
| `in_stock` | Stock | 0.65fr | `HFPill tone="ok"` for in-stock, `tone="warn"` for out. |
| `last_seen_at` | Last scrape | 0.8fr | `formatRelative()` inside `<time dateTime>`. |
| `url` | — | 90px | "Visit ↗" link, `aria-label="Open at {shop} (new tab)"`, `minWidth:32, minHeight:32`. |

**Lowest price logic:** `Math.min(...shops.filter(s => s.price).map(s => Number(s.price)))`. Multiple shops at same lowest price all get the badge.

**Empty state:** "Not listed anywhere we track" (same as current).

### `ShopMark` component

Small colored dot (10px, border-radius 50%) before the shop name. Color cycles through a fixed palette indexed by shop position in the list:
```js
const SHOP_COLORS = ['var(--hf-accent)', '#0e7490', '#b45309', '#7c3aed', '#16a34a', '#6b7280'];
```
Reused in Prices tab when price history is added later.

---

## Tab: Metadata

Two stacked cards.

### Card 1: Contributors

Renders `book.authors[]` grouped by `role`. Each role group is one row: role label (muted, 13px) + names joined with `', '`.

Roles to surface (in order, skip if empty):
1. `author` → label "Author / Authors"
2. `translator` → "Translated by"
3. `narrator` → "Narrated by"
4. `editor` → "Edited by"
5. `illustrator` → "Illustrated by"
6. `cover_artist` → "Cover by"
7. `producer` → "Produced by"
8. Any other role → title-case of role value

If `book.authors` is empty, show a small empty-state note "No contributor data."

### Card 2: Metadata matrix

Two-column table (label | value). Only render rows where value is non-null/non-empty.

| Field | Source |
|---|---|
| Year | `book.year` |
| Publisher | `book.publisher` |
| Format | `book.format` |
| Language | `book.language` |
| Pages | `book.pages` + " p." |
| Duration | `book.duration` |
| Type | `book.type` |
| Audience | `book.audience` |
| Series | `book.series` |
| Release place | `book.release_place` |
| UDC codes | `book.udc_codes` joined `', '` |
| Translated from | `book.translated_from` |
| Dimensions | `book.dimensions` |
| Data source | `<DataSourceBadge value={book.data_source}/>` |
| LIBIS code | `book.libis_code` (monospace chip) |

Row style: label in `var(--hf-ink3)` 13px, value in `var(--hf-ink)` 13px. Alternating rows use `var(--hf-subtle)` background.

---

## Tab: Prices (stub)

Single card:
```
title="Price history"
sub="Coming in a future release"
```
Body: `HFEmptyState title="Price history not yet available" sub="Once the price history endpoint is added, this tab will show per-shop price trends over time."`

---

## Tab: Conflicts (stub)

Single card:
```
title="Conflicts"
sub="Coming in a future release"
```
Body: `HFEmptyState title="Conflict detection not yet available" sub="This tab will highlight fields that differ between the canonical record and individual shop listings."`

---

## Implementation notes

### Tab state
```jsx
const [tab, setTab] = React.useState('listings');
```

Use existing `HFTabs` component (already in `hf-ui.jsx`):
```jsx
<HFTabs
  tabs={[
    { id:'listings', label:'Listings', count: (book.shops||[]).length },
    { id:'metadata', label:'Metadata' },
    { id:'prices',   label:'Prices' },
    { id:'conflicts',label:'Conflicts' },
  ]}
  active={tab}
  onChange={setTab}
/>
```

### Helper reuse

`formatEur`, `formatRelative`, `DataSourceBadge` — already in `hf-book.jsx` from Phase 1. No changes needed.

### Subjects + description

Move from hero card body into the Metadata tab's matrix card (as a dedicated "Subjects" row and a "Description" section below the matrix). The hero card becomes more compact.

---

## Testing

Manual only — no API change, no new integration tests.

- Open `/books/:id` for a book with multiple shops → Listings tab shows rows, lowest price has BEST badge.
- Switch to Metadata tab → Contributors and matrix render without errors.
- Empty fields omitted (no blank rows in matrix).
- Prices + Conflicts tabs show stub empty states.
- Book with no shops → Listings shows "Not listed anywhere we track."
- Book with no authors → Contributors shows "No contributor data."
- Rebuild: `docker compose build dashboard && docker compose up -d dashboard`
