# Canonical Books Layer

**Date:** 2026-05-08
**Status:** Design approved, awaiting implementation plan

## Background

The scraper currently has one product table — `shop_books` — that represents
every book listing on every shop. There is no notion of a canonical book
record that survives independently of any one shop's listing. The match
phase mentioned in `CLAUDE.md` is unimplemented, so books across shops
aren't deduplicated.

The new `ibiblioteka.lt` source (Lithuanian National Library) cleanly
separates "what books exist" (the LIBIS catalogue) from "where to buy
them" (vaga, pegasas, humanitas, knygos, patogupirkti). LIBIS provides
authoritative bibliographic metadata — clean ISBNs, structured authors
with authority codes, UDC subjects, translator/narrator roles — that
shops mostly don't carry.

This spec introduces a canonical books layer populated primarily from
ibiblioteka, with `shop_books` linking back to it via ISBN.

## Scope

The full vision: schema + ibiblioteka writes to the canonical layer +
matcher links existing `shop_books` + dashboard UI for canonical books +
`shop_inferred` synthesis for books that exist on shops but not in LIBIS.

Out of scope (deferred to future specs):

- Cross-shop price comparison view on the book detail page
- Faceted search / browse by publisher / series / UDC
- Author detail pages
- ibiblioteka cron re-sync schedule (manual runs only for now)
- Importing per-format extras (`shop_book_attributes`) into the canonical layer
- Change tracking on `books` (mirror of `shop_book_changes` — out)

## Architecture overview

```
┌──────────────────────────────────────────────────────────────────┐
│ CANONICAL LAYER  (books, book_isbns, book_authors,               │
│                   authors, publishers, series)                   │
│   • Source: ibiblioteka spider (data_source='ibiblioteka')       │
│   • Or: shop_inferred synthesis (≥2 shops, same ISBN)            │
│   • Or: manual                                                   │
└─────────────────────────────────┬────────────────────────────────┘
                                  │ book_id FK
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│ COMMERCIAL LAYER  (shop_books, prices, discovered_urls)          │
│   • Source: vaga, pegasas, humanitas, knygos, patogupirkti       │
│   • Carries price, stock, shop URL, shop description             │
│   • shop_books.book_id linked by the Match phase                 │
└──────────────────────────────────────────────────────────────────┘
```

Three pipeline phases. The first two exist; the third is new:

1. **discover** — find URLs (existing)
2. **scan** — fetch full records (existing)
3. **match** — *new* — link `shop_books.book_id`, synthesize `shop_inferred`
   books

ibiblioteka uses only `discover` + `scan`. Commercial shops use all three.

## Schema (already migrated as `c5d8e2f3a9b1`)

```
publishers
  id, name UNIQUE NOT NULL, country, libis_codes TEXT[], created_at

series
  id, title UNIQUE NOT NULL, libis_code UNIQUE, created_at

authors
  id, name NOT NULL, normalized_name UNIQUE NOT NULL,
  libis_code UNIQUE NULL, viaf_id UNIQUE NULL,
  isni UNIQUE NULL, wikidata_id UNIQUE NULL, created_at

books
  id, data_source ENUM('ibiblioteka','shop_inferred','manual') NOT NULL,
  libis_code TEXT UNIQUE NULL,
  CHECK (data_source != 'ibiblioteka' OR libis_code IS NOT NULL),
  title NOT NULL, title_full, year,
  publisher_id FK publishers, series_id FK series,
  release_place, type, format, pages, duration, dimensions,
  language, translated_from TEXT[],
  description, cover_url, upcoming_release BOOL DEFAULT FALSE,
  udc_codes TEXT[], subjects TEXT[], audience,
  libis_rating NUMERIC(3,2), libis_review_count,
  source_run_id FK scrape_runs, created_at, updated_at

book_isbns
  id, book_id FK books CASCADE, isbn UNIQUE NOT NULL,
  isbn_type ENUM('isbn10','isbn13','ebook','audio','unknown')

book_authors
  (book_id, author_id, role) PRIMARY KEY,
  role ENUM('author','translator','narrator','illustrator','editor','compiler'),
  position INT

shop_books     — existing + book_id FK NULL (set by matcher)
shop_authors   — existing + canonical_author_id FK NULL (set by matcher)
```

**Three notable design decisions**

- ISBN-10 and ISBN-13 are stored as separate rows in `book_isbns`. When the
  spider sees one form, the pipeline auto-computes and inserts the equivalent
  form. `book_isbns.isbn` is globally UNIQUE — one ISBN belongs to exactly
  one book.
- `shop_authors` and `authors` stay as parallel tables, linked via
  `canonical_author_id`. The matcher fills `canonical_author_id` only when the
  containing book matches by ISBN. No name-based author matching.
- `data_source = 'ibiblioteka'` requires `libis_code` (CHECK constraint).
  `shop_inferred` and `manual` rows have `libis_code = NULL`.

## Spider and pipeline changes

### New `BookItem`

`book_scraper/items.py` gets a third item type alongside `ShopBookItem` and
`PriceItem`:

```python
class BookItem(scrapy.Item):
    """Canonical bibliographic record. Goes to the books table."""
    libis_code     = scrapy.Field()    # required when data_source='ibiblioteka'
    data_source    = scrapy.Field()    # 'ibiblioteka' | 'shop_inferred' | 'manual'
    title          = scrapy.Field()
    title_full     = scrapy.Field()
    year           = scrapy.Field()
    publisher      = scrapy.Field()    # name; pipeline upserts publishers row
    series         = scrapy.Field()    # title; pipeline upserts series row
    isbns          = scrapy.Field()    # list[(isbn, type)]
    authors        = scrapy.Field()    # list[{name, libis_code, role, position}]
    release_place  = scrapy.Field()
    type           = scrapy.Field()    # 'book' | 'audio' | 'ebook'
    format         = scrapy.Field()    # 'PRINTED' | 'ELECTRONIC'
    pages          = scrapy.Field()
    duration       = scrapy.Field()
    dimensions     = scrapy.Field()
    language       = scrapy.Field()
    translated_from = scrapy.Field()
    description    = scrapy.Field()
    cover_url      = scrapy.Field()
    upcoming_release = scrapy.Field()
    udc_codes      = scrapy.Field()
    subjects       = scrapy.Field()
    audience       = scrapy.Field()
    libis_rating   = scrapy.Field()
    libis_review_count = scrapy.Field()
```

### ibiblioteka spider rewrite

**Discover phase** keeps yielding `DiscoveredUrlItem` (one per detail URL,
so the scan queue knows what to fetch). The intermediate `ShopBookItem`
emission added during early development goes away — the `_emit_products`
custom path in `parse_ibiblioteka_page` shrinks back to URL emission only.

**Scan phase rewrite is non-trivial.** `ScanSpider.parse_product`
currently constructs a `ShopBookItem` directly from parser output
(scan.py around line 346) — the parser contract returns a flat dict and
the spider builds the item. To support `BookItem` for ibiblioteka without
duplicating the entire scan pipeline, the parser contract is extended:

```python
# Parsers may return either:
#   ProductPageResult (existing dict)
#   OR a sentinel-tagged result indicating canonical book emission
#
# The ibiblioteka parse_product_page returns:
#   {"_emit_as": "book", **book_fields}
#
# Other shop parsers continue returning the existing flat dict
# (treated as ProductPageResult by default).
```

`ScanSpider.parse_product` branches on `_emit_as`:

- `_emit_as == "book"` → construct `BookItem` from parser output, yield it.
  Skip price/stock/url-classification logic that doesn't apply.
- absent / `"shop_book"` → existing `ShopBookItem` path unchanged.

The branch is small (~15 lines) and keeps shop scan paths untouched.
Validation pipeline routes by item type as before. The discovered_url is
still marked done in the same finally block.

ibiblioteka is no longer a "shop". The `shops` row is removed (see
backfill section). Books from LIBIS appear only on the new Books page.

### Pipeline changes

`ValidationPipeline.process_item` gains a `BookItem` branch with rules:

- `title` required (DropItem if missing)
- `data_source` required and in the enum
- `libis_code` required when `data_source == 'ibiblioteka'`
- No price validation (BookItem has no price)

`PostgresPipeline.process_item` gains a `BookItem` branch routing to
`_upsert_book(session, item)`. The order matters because the LIBIS
upgrade path (Match phase Step 4) requires merging into an existing
`shop_inferred` row that already has the same ISBN — a `libis_code`-only
upsert would create a second row and collide on
`book_isbns.isbn UNIQUE`.

Resolution order to find the target `books.id`:

1. **By any incoming ISBN** (normalized) — find the existing book that
   already owns this ISBN via `book_isbns`. Catches the
   shop_inferred → ibiblioteka upgrade case.
2. **By `libis_code`** — for re-scrapes where ISBNs may have changed.
3. **Otherwise INSERT** a new books row.

When step 1 finds a row whose `data_source = 'shop_inferred'` and we're
writing `'ibiblioteka'`, the row is upgraded in place: `data_source`
flips, `libis_code` fills in, fields overwrite (per Q4) except
`publisher_id` (sticky, see below).

**Multi-match edge case.** Step 1 may find multiple distinct existing
books — e.g. shop_inferred Book B owns ISBN `978-X` (print), shop_inferred
Book C owns ISBN `978-Y` (ebook), and the incoming LIBIS record now
declares both ISBNs belong to one work. Resolution: pick the existing
book with the **lowest id** as the target, mark the others for merge,
and emit a `book_merge_needed` validation issue. The merge itself (move
shop_books.book_id from the loser to the winner, delete the loser) is
out of scope for this spec — listed as a follow-on. For now, the matcher
logs and skips so a human can resolve. This case is rare in practice.

After the target `books.id` is known, the upsert performs:

1. Upsert `publishers` by name → `publisher_id`
2. Upsert `series` by title → `series_id`
3. UPDATE/INSERT `books` row: idempotent, last-write-wins for all fields
   **except `publisher_id`**, which is sticky — set only when the
   existing row has `publisher_id IS NULL`, otherwise left unchanged.
4. **Normalize all incoming ISBNs** (strip dashes, uppercase X) before
   any DB write. Compute the missing ISBN-10/13 form. UPSERT into
   `book_isbns` keyed on the normalized ISBN — never DELETE existing
   rows (they may be referenced by Step 1's resolution above and by
   already-matched shop_books). Use `ON CONFLICT (isbn) DO UPDATE SET
   isbn_type = EXCLUDED.isbn_type, book_id = EXCLUDED.book_id` so
   reassigning an ISBN to a merged book is explicit and visible.
5. Upsert each author into `authors` (by `libis_code` if present, else by
   `normalized_name`)
6. Replace `book_authors` rows for this book

All in one transaction per item, same per-item commit pattern the existing
`ShopBookItem` path uses.

**ISBN normalization is shared between this pipeline and the Match
phase.** Verified state of the codebase (2026-05-08):

- `book_scraper/isbn.py` already exposes `normalize_isbn(raw)` (strips
  dashes/spaces) and `is_valid_isbn(raw)` (checksum validation, calls
  normalize internally).
- `ValidationPipeline.process_item` (pipelines.py around line 275)
  calls `_is_valid_isbn(isbn)` to validate but **does not normalize the
  stored value** — `adapter["isbn"]` keeps the raw form (dashes intact)
  unless validation fails. So `shop_books.isbn` currently contains a
  mix of dashed and undashed forms across shops.

The fix:

1. Extend `isbn.py` with `to_isbn13(s)` / `to_isbn10(s)` converters (new
   functions; checksums recomputed for the converted form).
2. Modify `ValidationPipeline` to set `adapter["isbn"] =
   normalize_isbn(isbn)` after validation passes — going forward all
   shop scrapes write the normalized form. (Single-line change.)
3. One-shot SQL back-fill of existing `shop_books.isbn`:
   ```sql
   UPDATE shop_books
      SET isbn = REPLACE(REPLACE(isbn, '-', ''), ' ', '')
    WHERE isbn IS NOT NULL AND (isbn LIKE '%-%' OR isbn LIKE '% %');
   ```
   Run as part of commit 4 alongside the matcher landing.
4. The matcher's join uses normalized form on both sides; defensive
   `REPLACE(...)` in the SQL guards against any future regression.

`book_isbns.isbn` is always normalized at write time by `_upsert_book`.

## Match phase

A new pipeline phase, sibling to `discover` and `scan`. The matching
work itself lives in `book_scraper/services/match.py` (pure DB
operations, no HTTP). It is launched the same way as discover/scan:
through `scrapy crawl <phase>`, because both the dashboard
(`api.py:620`) and the cron generator (`scripts/generate_crontab.py:23`)
hardcode that launcher and rewriting both for one phase costs more than
it saves.

A thin spider `book_scraper/spiders/match.py` (`name = "match"`) is the
entrypoint:

```python
class MatchSpider(scrapy.Spider):
    name = "match"
    custom_settings = {"ITEM_PIPELINES": {}}  # no items, no pipelines

    def __init__(self, shop=None, **kw):
        super().__init__(**kw)
        self.shop_name = shop

    async def start(self):
        # No HTTP — invoke the service synchronously and close.
        from book_scraper.services.match import MatchService
        with session_scope() as session:
            MatchService(session).run(self.shop_name)
        return
        yield  # unreachable, satisfies AsyncGenerator typing
```

This makes match runs visible in `scrape_runs` (the spider creates the
run row via `MatchService` just like other phases), respects existing
stall-detection / heartbeat infrastructure, and reuses the launcher
plumbing. The actual matching code is in the service so it's testable
without Scrapy.

### Configuration

Trust ranking lives in each shop's TOML:

```toml
# config/shops/vaga.toml
[shop]
name = "vaga"
base_url = "https://vaga.lt"

[match]
trust = 100
```

`MatchService` loads all shop configs at startup. Default if unspecified: 50.
Higher number = more trusted. Used only by step 3 (shop_inferred synthesis).

### Steps

The matcher runs four steps in order, all idempotent:

#### Step 1 — ISBN match

`shop_books.isbn` is back-filled to normalized form (no dashes, uppercase
X) via a one-shot SQL pass run as part of commit 4 — see the Pipeline
section's ISBN normalization paragraph. With both sides normalized:

```sql
UPDATE shop_books sb
   SET book_id = bi.book_id,
       match_status = 'matched',
       match_method = 'isbn'
  FROM book_isbns bi
 WHERE sb.isbn IS NOT NULL
   AND sb.isbn = bi.isbn       -- both stored normalized
   AND sb.book_id IS NULL
   AND sb.shop_id = (SELECT id FROM shops WHERE name = :shop_name);
```

Defensive belt-and-braces: the matcher applies `normalize_isbn()` to
`sb.isbn` at compare time too (CTE form), in case a future shop scraper
slips a dashed ISBN through validation. Cheapest, runs first. Covers
the majority of books.

#### Step 2 — Author backfill

For each shop_book newly matched in step 1, link its `shop_authors` rows
to canonical `authors` via the matched book's `book_authors`. The matched
book vouches for the link — no name-based heuristics.

`book_authors.position` is **per-role** by spec convention — translators
start at position 0, narrators start at 0, primary authors start at 0,
each independent. `_upsert_book` enforces this when inserting
`book_authors` rows (verified against parser output: ibiblioteka emits
`{role, position}` tuples where positions reset per role).

`shop_authors` records only primary authors — verified against
`book_scraper/db/repo.py:88` (`_sync_shop_book_authors` is fed by the
single `ShopBookItem.author` string, splits multi-author separators,
and writes positional rows; no notion of role). Translators, narrators
and illustrators on shop products live in
`shop_book_attributes.properties` (JSONB), not in `shop_authors`.

So the join must filter to `role = 'author'` to avoid a primary
shop_author at position=0 being paired with a canonical translator or
narrator that also has position=0:

```sql
UPDATE shop_authors sa
   SET canonical_author_id = ba.author_id
  FROM shop_book_authors sba
  JOIN shop_books sb ON sb.id = sba.shop_book_id
  JOIN book_authors ba ON ba.book_id = sb.book_id
                      AND ba.position = sba.position
                      AND ba.role = 'author'      -- critical filter
 WHERE sa.id = sba.author_id
   AND sa.canonical_author_id IS NULL
   AND sb.match_status = 'matched';
```

Position-based pairing within the `author` role is still a heuristic
(the first shop_author corresponds to the first canonical author).
Acceptable because primary authors are usually listed in the same order
on both sides.

#### Step 3 — `shop_inferred` synthesis

Find ISBNs that:

- appear on `shop_books` from ≥2 distinct shops
- aren't in `book_isbns` yet (no canonical match exists)

For each such ISBN:

- Pick the highest-trust shop's `shop_books` row → use its title, year,
  format, type, language, etc.
- **Publisher uses the value from the FIRST shop that wrote it (the row
  with the earliest `created_at` among shops carrying this ISBN). The
  resulting `publisher_id` is sticky — never overwritten.**
- INSERT `books` (`data_source='shop_inferred'`, `libis_code=NULL`)
- INSERT `book_isbns` row
- Link all matching `shop_books.book_id`

#### Step 4 — `shop_inferred` upgrade (when LIBIS catches up)

When ibiblioteka later writes a book whose ISBN already exists on a
`shop_inferred` row, the upsert merges into the existing `books` row
(same id):

- `data_source` flips from `'shop_inferred'` to `'ibiblioteka'`
- `libis_code` fills in
- LIBIS overwrites all canonical fields **EXCEPT publisher** (sticky —
  shops know the printed publisher; LIBIS sometimes uses different
  cataloguing conventions)
- `shop_books.book_id` stays unchanged — already pointing at the right row
- New ISBNs from LIBIS get inserted into `book_isbns` (e.g. LIBIS adds an
  ebook ISBN)

### Trigger surfaces

- **Cron:** match runs per-shop on a configurable schedule (default
  hourly). Each shop's `cron_jobs` row gets a `phase='match'` entry
  alongside its existing `discover_*` / `scan` entries. This fits the
  existing per-shop run lifecycle without a schema change to
  `scrape_runs.shop_id` (which is NOT NULL).
- **On-demand:** dashboard "New Run" dialog gets a third phase option
  `match` alongside `discover` and `scan`. The shop selector stays
  required (operators run match for one shop at a time). Endpoint:
  `POST /api/scrape/match` with `shop` parameter.

Steps 1 and 2 of the matcher are scoped to the run's shop (only that
shop's `shop_books` get linked). Steps 3 and 4 are cross-shop by nature
(synthesis looks at ISBNs across all shops) but the operations are
idempotent — running them from N concurrent per-shop matchers produces
the same result as running once. The first matcher to fire wins for any
given ISBN; the rest see existing rows and skip.
- Auto-trigger after every scan run completes is **out of scope** —
  operators chain manually or set up a dependent cron.

### Run lifecycle

The match run uses the `scrape_runs` table with `phase='match'`. New value
added to the `scrape_phase` enum via Alembic. Emits:

- `items_added` — new books created (step 3)
- `items_updated` — `shop_books` linked in step 1, plus `shop_books`
  re-linked on upgrades in step 4
- standard `urls_processed` counter (interpreted as "rows examined")

Stall detection, resumability, and dashboard run views all apply for free.

## UI changes (minimal)

### New "Books" page

Sidebar Catalog group, between "Shop Books" and "URLs":

```
CATALOG
├─ Shop Books     (existing)
├─ Books          ← NEW
├─ URLs
└─ Shops
```

Backed by `GET /api/books` returning paginated rows with: `id`, `title`,
joined `author` (via `book_authors`), joined `publisher`, `year`,
`data_source`, primary ISBN, shop count (number of `shop_books` linking
back). Filters: `shop_count`, `data_source`, `year`, `has_isbn`. Sortable.
Same `HFTable` + `useShopNames` patterns as other list pages.

### Book detail page

Route `/books/{id}`, backed by `GET /api/books/{id}` returning the
canonical record + a `shops` array (joined `shop_books` with latest
price/stock).

```
┌─────────────────────────────────────────────────────────┐
│  ← Books                                  [data_source] │
│                                                         │
│  Title (large)                                          │
│  by Author 1, Author 2 · 2024 · Publisher              │
│                                                         │
│  ISBN: 978-… · LIBIS: LIBIS000…                        │
│  Format: PRINTED · 122 p. · 21 cm                       │
│  Subjects: …                                            │
│  Description (LIBIS annotation)                         │
│                                                         │
│  ─── Available at ─────────────────────────────────────│
│  ┌─ shop ──── price ── stock ── url ──── last_seen ──┐ │
│  │ vaga      €18.50  ✓ ok   /knygos/…   2 hours ago │ │
│  │ pegasas   €19.90  ✓ ok   /products/  4 hours ago │ │
│  │ humanitas €17.10  ✗ out  /produktas/ 1 day ago   │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Shop book detail badge

Existing shop_book detail page gets a small badge near the title:

```
"Linked to canonical book #123 →"   (clickable link)
or
"Unmatched"                          (subtle, gray)
```

### Dropping ibiblioteka from the Shops listing

After the backfill, ibiblioteka is no longer in the `shops` table. The
existing Shops page automatically stops showing it. Frontend filter
dropdowns that use `useShopNames()` also auto-update.

### Match phase in Runs

Match runs show up in the Runs list with `phase='match'` and a phase label
"Match · ISBN". Same visual patterns as discover/scan runs (timeline,
in-flight card, history). The shop column shows the run's shop normally —
match is per-shop just like discover and scan.

## Backfill

One-shot SQL run before deploying the new spider code. **Delete order
matters** because some tables FK to `shop_books` without
`ON DELETE CASCADE`. Verified against `models.py`:

| Referencing table | FK behavior | Backfill action |
|---|---|---|
| `shop_book_authors` (line 196) | `ON DELETE CASCADE` | auto, no DELETE needed |
| `shop_book_attributes` (line 211) | `ON DELETE CASCADE` | auto, no DELETE needed |
| `shop_book_field_updates` (line 237) | `ON DELETE CASCADE` | auto, no DELETE needed |
| `prices` (line 263) | RESTRICT (default) | explicit DELETE before shop_books |
| `shop_book_changes` (line 292) | RESTRICT | explicit DELETE before shop_books |
| `discovered_urls.shop_book_id` (line 394, nullable) | RESTRICT | UPDATE NULL before shop_books |
| `validation_issues.shop_book_id` (line 599, nullable) | RESTRICT | UPDATE NULL before shop_books |

```sql
BEGIN;

-- 1. Stop any in-flight ibiblioteka run
UPDATE scrape_runs
   SET status='failed', close_reason='superseded_by_canonical_layer'
 WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka')
   AND status IN ('running','paused');

-- 2. Drop / null non-cascading child rows that reference shop_books
DELETE FROM prices             WHERE shop_book_id IN (SELECT id FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));
DELETE FROM shop_book_changes  WHERE shop_book_id IN (SELECT id FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));
UPDATE discovered_urls SET shop_book_id = NULL
 WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
UPDATE validation_issues SET shop_book_id = NULL
 WHERE shop_book_id IN (SELECT id FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));

-- 3. Now safe to delete shop_books (cascades to authors/attributes/field_updates)
DELETE FROM shop_books WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');

-- 4. Drop the rest of the ibiblioteka shop graph
DELETE FROM discovered_urls   WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM scrape_url_items  WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM scrape_run_events WHERE run_id IN (SELECT id FROM scrape_runs WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));
DELETE FROM validation_issues WHERE run_id IN (SELECT id FROM scrape_runs WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka'));
DELETE FROM cron_jobs         WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM scrape_runs       WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM shop_settings     WHERE shop_id = (SELECT id FROM shops WHERE name='ibiblioteka');
DELETE FROM shops             WHERE name='ibiblioteka';

COMMIT;
```

Implementation plan should re-audit `models.py` for any additional FK
to `shop_books` or `shops` added since spec authoring. Wrap in a
transaction; if any DELETE fails, abort.

The 28k thin `shop_books` rows produced before the canonical layer existed
are deleted. Fresh ibiblioteka runs write to the new `books` layer.

## Implementation order

**Worktree state warning.** As of spec authoring (2026-05-08), the
working tree contains uncommitted ibiblioteka work and the applied
canonical-layer migration `c5d8e2f3a9b1`. Specifically: modified
`book_scraper/spiders/discover.py`, `book_scraper/spiders/ibiblioteka/`,
`book_scraper/config_models.py`, `book_scraper/dashboard/static/hifi/*`,
plus untracked tests/fixtures. Implementation must `git status` first,
inspect each modified file, and decide per-file whether to keep, amend,
or replace — not regenerate blindly. The migration must NOT be
re-applied (it's already at head `c5d8e2f3a9b1`).

Six commits, each shippable in isolation:

| # | Commit | Description |
|---|---|---|
| 1 | `add SQLAlchemy models for canonical layer` | `Publisher`, `Series`, `Author`, `Book`, `BookIsbn`, `BookAuthor` ORM models pointing at the existing migrated tables. Pure Python, no behavior change. |
| 2 | `add BookItem + PostgresPipeline upsert path` | New item type, validation rules, pipeline branch with `_upsert_book`. ISBN-10/13 auto-fill helper. Unit tests with fixtures. |
| 3 | `wipe ibiblioteka shop layer + rewrite spider to emit BookItem` | The SQL backfill + spider change. Discover keeps yielding `DiscoveredUrlItem`; scan yields `BookItem`. Drops the dashboard ibiblioteka shop entry. |
| 4 | `add match service + match phase` | All of: (a) `match` value added to `scrape_phase` PG enum (Alembic migration); (b) `MatchService` implementing steps 1 + 2 from the Match section; (c) thin `MatchSpider` entrypoint so `scrapy crawl match -a shop=…` works; (d) extend `api.py:651` phase whitelist to accept `match`; (e) extend `scripts/generate_crontab.py` so per-shop match cron rows are emitted; (f) shared `book_scraper/isbn_utils.py` (normalize / convert ISBN-10↔13); (g) one-shot SQL pass to back-fill normalize-existing `shop_books.isbn` values; (h) per-shop trust config in `config/shops/<shop>.toml`. |
| 5 | `add Books UI: list page + detail + linked-book badge` | New routes, JSX components, API endpoints `/api/books` and `/api/books/{id}`. Adds book_id badge to existing shop_book detail. |
| 6 | `add shop_inferred synthesis + upgrade to match phase` | Steps 3 and 4 of the matcher, with sticky publisher rule. Documented behavior + tests covering the LIBIS-promotion path. |

After commit 3, ibiblioteka books appear in the Books table (no UI yet —
accessible via API and SQL). After commit 4 existing `shop_books` get
linked. After commit 5 the UI shows the canonical layer. After commit 6
the `shop_inferred` synthesis closes the loop.

## Decision log

| Q | Decision |
|---|---|
| Scope | Full vision: schema + ibiblioteka + matcher + UI + shop_inferred |
| Match trigger | Cron + on-demand from dashboard / API |
| `shop_inferred` threshold | ≥2 shops with same ISBN |
| `shop_inferred` field source | Highest-trust shop wins for most fields; **publisher always uses first writer's value, sticky forever** |
| ibiblioteka re-scrape | Idempotent upsert — last LIBIS write wins; no change log; **publisher exempted on shop_inferred upgrade** |
| Existing 28k rows | Wipe and re-discover (clean slate) |
| UI scope | Minimal — new Books page + detail + linked-book badge on shop_books |
| ISBN-10 ↔ ISBN-13 | Store both forms in `book_isbns`; pipeline auto-computes the equivalent |
| Author normalization | No name-based matching; only link via ISBN-matched book |
| Foreign-language books | Become `shop_inferred` once ≥2 Lithuanian shops carry the same ISBN |
| Match config location | Per-shop TOML (`config/shops/<shop>.toml [match] trust = N`) |
