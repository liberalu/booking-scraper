# Rename `listing` → `shop_book` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the `listing` concept to `shop_book` across DB schema, ORM, Scrapy items, pipelines, dashboard, tests, and scripts so the domain model self-describes "book as it appears in a specific shop" — ready for onboarding a second shop (pegasas.lt).

**Architecture:** Single atomic refactor. One Alembic migration renames all `listings*` tables, their FK columns (`listing_id` → `shop_book_id`), unique constraints, indexes, the CHECK constraint, and the `listing_type` enum. Python code is renamed in lockstep across models, Scrapy items, pipelines, repository, dashboard routes/queries/templates, scripts, and tests. Everything ships as a single commit so `main` is never in a broken state (DB and code always match).

**Tech Stack:** PostgreSQL, SQLAlchemy 2.0, Alembic, Scrapy, FastAPI, Jinja2, pytest, Docker Compose

---

## Decisions

- **One atomic commit.** Migration + Python + templates + tests + docs all land together. Splitting into multiple commits would leave intermediate states where DB and code disagree.
- **No HTTP 301 redirects for old `/listings/` URLs.** The Notion spec mentioned them, but this dashboard is local-only and has no external consumers. Old tabs/bookmarks will 404; that's acceptable for a personal project. Skipping the redirect shim keeps the diff smaller and removes dead code from day one.
- **URL path kebab-case.** `/shop-books` and `/shop-books/{shop_book_id}` (standard REST convention; matches the Notion spec's example).
- **No separate "first PR for spec" step.** Personal project, commit directly on `main` (per `CLAUDE.md`).
- **Out of scope:** `discovered_urls`, `shop_authors`, `shop_id` — only concepts whose name contains "listing" are renamed. `shop_authors` stays as-is (it's already well-named).
- **Rollback strategy:** Alembic `downgrade()` fully reverses the migration. Test it explicitly before committing.

---

## Scope Inventory

### Tables

| Old | New |
|---|---|
| `listings` | `shop_books` |
| `listing_authors` | `shop_book_authors` |
| `listing_attributes` | `shop_book_attributes` |
| `listing_changes` | `shop_book_changes` |
| `listing_field_updates` | `shop_book_field_updates` |

### FK columns (all `listing_id` → `shop_book_id`)

- `listing_authors.listing_id`
- `listing_attributes.listing_id`
- `listing_field_updates.listing_id`
- `listing_changes.listing_id`
- `prices.listing_id`
- `discovered_urls.listing_id`
- `validation_issues.listing_id`

### Constraints & indexes

- `uq_listing_shop_url` → `uq_shop_book_shop_url`
- `uq_listing_attribute_listing_key` → `uq_shop_book_attribute_shop_book_key`
- `uq_listing_field_updates_listing_field` → `uq_shop_book_field_updates_shop_book_field`
- `ix_listing_field_updates_listing_field` → `ix_shop_book_field_updates_shop_book_field`
- `ix_discovered_urls_listing_id` → `ix_discovered_urls_shop_book_id`
- CHECK `ck_validation_issues_single_entity` must be dropped and recreated (it references `listing_id`).

### Enums

- `listing_type` → `shop_book_type`

### ORM classes (in `book_scraper/db/models.py`)

| Old | New |
|---|---|
| `Listing` | `ShopBook` |
| `ListingAuthor` | `ShopBookAuthor` |
| `ListingAttribute` | `ShopBookAttribute` |
| `ListingChange` | `ShopBookChange` |
| `ListingFieldUpdate` | `ShopBookFieldUpdate` |
| module-level `listing_type_enum` | `shop_book_type_enum` |

Relationships to rename: `Shop.listings` → `Shop.shop_books`; `Price.listing` → `Price.shop_book`; `DiscoveredUrl.listing` → `DiscoveredUrl.shop_book`; `ValidationIssue.listing` → `ValidationIssue.shop_book`; `ShopBook.prices.back_populates="listing"` → `"shop_book"`; similarly for `changes`, `attributes`, `discovered_urls`.

### Scrapy items

- `ListingItem` → `ShopBookItem` (in `book_scraper/items.py`).

### Repository functions (in `book_scraper/db/repo.py`)

| Old | New |
|---|---|
| `upsert_listing` | `upsert_shop_book` |
| `_sync_listing_authors` | `_sync_shop_book_authors` |
| `_sync_attribute_rows` | (same name — not listing-specific) |
| `touch_listing_field_updates` | `touch_shop_book_field_updates` |
| `mark_listings_inactive` | `mark_shop_books_inactive` |
| `link_discovered_url_to_listing` | `link_discovered_url_to_shop_book` |
| `get_listing_changes` | `get_shop_book_changes` |

Plus: every `listing` / `listing_id` parameter/local variable, every `.listing_id` column reference in queries.

### Dashboard

- Route file: `book_scraper/dashboard/routes/listings.py` → `book_scraper/dashboard/routes/shop_books.py`. Update the include in whatever file mounts it (likely `book_scraper/dashboard/app.py` or `__init__.py`).
- Routes: `/listings` → `/shop-books`; `/listings/{listing_id}` → `/shop-books/{shop_book_id}`. View functions `listings_page` → `shop_books_page`; `listing_detail` → `shop_book_detail`.
- `book_scraper/dashboard/routes/scrape.py`: update redirect URL.
- `book_scraper/dashboard/queries.py`: `get_listings_page` → `get_shop_books_page`; `get_listing_changes` → `get_shop_book_changes`; every `listing_id` param renamed.
- Templates: rename `listings.html` → `shop_books.html`; rename `listing_detail.html` → `shop_book_detail.html`. Update all `/listings` URLs, "Listing"/"listing" labels, template variables (`listings`, `listing` → `shop_books`, `shop_book`), `active_page` value `"listings"` → `"shop_books"` in every route that sets it.
- Cross-linking templates to edit: `base.html`, `shops.html`, `shop_detail.html`, `overview.html`, `validation.html`, `validation_detail.html`, `discovered_urls.html`, `run_detail.html`, `not_listed.html`.

### Scripts

- `book_scraper/scripts/backfill_listing_attributes.py` → `backfill_shop_book_attributes.py` (rename + update internals).
- `backfill_authors.py`, `backfill_html_entities.py` — update model imports and any local variables.

### Tests

Unit tests to update (`tests/unit/`):
- `test_items.py`
- `test_validation_pipeline.py`
- `test_spiders.py`

Integration tests to update/rename (`tests/integration/`):
- `test_listing_authors.py` → `test_shop_book_authors.py`
- `test_listing_type.py` → `test_shop_book_type.py`
- `test_listings_filter_sort.py` → `test_shop_books_filter_sort.py`
- `test_db_repo.py`
- `test_db_repo_extra.py`
- `test_postgres_pipeline.py`
- `test_validation_linkage.py`
- `test_validation_lifecycle.py`
- `test_discovered_urls_repo.py`
- `test_dashboard_routes.py` (confirms `/shop-books` routes, not `/listings`)

### Docs

- `CLAUDE.md` lines referencing `listings` table and Post-Task Checklist wording around listings/dashboard.

---

## Task 1: Write the Alembic migration

**Files:**
- Create: `alembic/versions/<new-hash>_rename_listings_to_shop_books.py`

- [ ] **Step 1: Generate migration stub**

Run: `PYTHONPATH=. uv run alembic revision -m "rename listings to shop_books"`

Note the revision filename printed to stdout. Open it.

- [ ] **Step 2: Confirm `down_revision`**

The stub's `down_revision` should be `e6ccc5193517` (the current head). Verify with `PYTHONPATH=. uv run alembic heads` if unsure.

- [ ] **Step 3: Write `upgrade()`**

Replace the generated `upgrade()` body with this exact content (keep the `import` block and `revision`/`down_revision` lines untouched):

```python
def upgrade() -> None:
    # 1. Drop CHECK that references the old column name — recreated below.
    op.drop_constraint(
        "ck_validation_issues_single_entity",
        "validation_issues",
        type_="check",
    )

    # 2. Rename the enum type (SQL — SQLAlchemy has no op.alter_type_name).
    op.execute("ALTER TYPE listing_type RENAME TO shop_book_type")

    # 3. Rename FK columns (tables still have old names here).
    op.alter_column("prices", "listing_id", new_column_name="shop_book_id")
    op.alter_column("listing_changes", "listing_id", new_column_name="shop_book_id")
    op.alter_column("listing_attributes", "listing_id", new_column_name="shop_book_id")
    op.alter_column(
        "listing_field_updates", "listing_id", new_column_name="shop_book_id"
    )
    op.alter_column("listing_authors", "listing_id", new_column_name="shop_book_id")
    op.alter_column("discovered_urls", "listing_id", new_column_name="shop_book_id")
    op.alter_column("validation_issues", "listing_id", new_column_name="shop_book_id")

    # 4. Rename tables. FKs follow automatically.
    op.rename_table("listings", "shop_books")
    op.rename_table("listing_authors", "shop_book_authors")
    op.rename_table("listing_attributes", "shop_book_attributes")
    op.rename_table("listing_changes", "shop_book_changes")
    op.rename_table("listing_field_updates", "shop_book_field_updates")

    # 5. Rename constraints (use new table names).
    op.execute(
        "ALTER TABLE shop_books RENAME CONSTRAINT uq_listing_shop_url "
        "TO uq_shop_book_shop_url"
    )
    op.execute(
        "ALTER TABLE shop_book_attributes RENAME CONSTRAINT "
        "uq_listing_attribute_listing_key TO uq_shop_book_attribute_shop_book_key"
    )
    op.execute(
        "ALTER TABLE shop_book_field_updates RENAME CONSTRAINT "
        "uq_listing_field_updates_listing_field TO "
        "uq_shop_book_field_updates_shop_book_field"
    )

    # 6. Rename indexes (indexes have global names, not per-table).
    op.execute(
        "ALTER INDEX ix_listing_field_updates_listing_field "
        "RENAME TO ix_shop_book_field_updates_shop_book_field"
    )
    op.execute(
        "ALTER INDEX ix_discovered_urls_listing_id "
        "RENAME TO ix_discovered_urls_shop_book_id"
    )

    # 7. Recreate CHECK with the new column name.
    op.create_check_constraint(
        "ck_validation_issues_single_entity",
        "validation_issues",
        "NOT (shop_book_id IS NOT NULL AND discovered_url_id IS NOT NULL)",
    )
```

- [ ] **Step 4: Write `downgrade()`**

Replace `downgrade()` body with:

```python
def downgrade() -> None:
    op.drop_constraint(
        "ck_validation_issues_single_entity",
        "validation_issues",
        type_="check",
    )

    op.execute(
        "ALTER INDEX ix_discovered_urls_shop_book_id "
        "RENAME TO ix_discovered_urls_listing_id"
    )
    op.execute(
        "ALTER INDEX ix_shop_book_field_updates_shop_book_field "
        "RENAME TO ix_listing_field_updates_listing_field"
    )

    op.execute(
        "ALTER TABLE shop_book_field_updates RENAME CONSTRAINT "
        "uq_shop_book_field_updates_shop_book_field TO "
        "uq_listing_field_updates_listing_field"
    )
    op.execute(
        "ALTER TABLE shop_book_attributes RENAME CONSTRAINT "
        "uq_shop_book_attribute_shop_book_key TO uq_listing_attribute_listing_key"
    )
    op.execute(
        "ALTER TABLE shop_books RENAME CONSTRAINT uq_shop_book_shop_url "
        "TO uq_listing_shop_url"
    )

    op.rename_table("shop_book_field_updates", "listing_field_updates")
    op.rename_table("shop_book_changes", "listing_changes")
    op.rename_table("shop_book_attributes", "listing_attributes")
    op.rename_table("shop_book_authors", "listing_authors")
    op.rename_table("shop_books", "listings")

    op.alter_column("validation_issues", "shop_book_id", new_column_name="listing_id")
    op.alter_column("discovered_urls", "shop_book_id", new_column_name="listing_id")
    op.alter_column("listing_authors", "shop_book_id", new_column_name="listing_id")
    op.alter_column(
        "listing_field_updates", "shop_book_id", new_column_name="listing_id"
    )
    op.alter_column("listing_attributes", "shop_book_id", new_column_name="listing_id")
    op.alter_column("listing_changes", "shop_book_id", new_column_name="listing_id")
    op.alter_column("prices", "shop_book_id", new_column_name="listing_id")

    op.execute("ALTER TYPE shop_book_type RENAME TO listing_type")

    op.create_check_constraint(
        "ck_validation_issues_single_entity",
        "validation_issues",
        "NOT (listing_id IS NOT NULL AND discovered_url_id IS NOT NULL)",
    )
```

- [ ] **Step 5: Dry-run migration SQL**

Run: `PYTHONPATH=. uv run alembic upgrade head --sql`
Expected: SQL output prints `ALTER TABLE ... RENAME`, `ALTER INDEX ... RENAME`, `ALTER TYPE ... RENAME` statements for every rename. No errors. Do NOT apply live yet — we apply together with the code rename (Task 10).

---

## Task 2: Rename ORM models

**File:** `book_scraper/db/models.py`

- [ ] **Step 1: Rename enum and classes**

Edit lines 57–59:
```python
shop_book_type_enum = Enum(
    "book", "audio", "ebook", name="shop_book_type", create_type=False
)
```

Rename classes and their `__tablename__`:
- `Listing` → `ShopBook`, `__tablename__ = "shop_books"`
- `ListingAuthor` → `ShopBookAuthor`, `__tablename__ = "shop_book_authors"`
- `ListingAttribute` → `ShopBookAttribute`, `__tablename__ = "shop_book_attributes"`
- `ListingFieldUpdate` → `ShopBookFieldUpdate`, `__tablename__ = "shop_book_field_updates"`
- `ListingChange` → `ShopBookChange`, `__tablename__ = "shop_book_changes"`

Rename all `listing_id: Mapped[int]` columns to `shop_book_id: Mapped[int]` with `ForeignKey("shop_books.id", ...)`.

Rename FKs in the remaining classes:
- `Price.listing_id` → `Price.shop_book_id` with `ForeignKey("shop_books.id")`
- `DiscoveredUrl.listing_id` → `DiscoveredUrl.shop_book_id` with `ForeignKey("shop_books.id")`
- `ValidationIssue.listing_id` → `ValidationIssue.shop_book_id` with `ForeignKey("shop_books.id")`

- [ ] **Step 2: Rename constraints in `__table_args__`**

- `ShopBook`: `name="uq_shop_book_shop_url"`
- `ShopBookAttribute`: `name="uq_shop_book_attribute_shop_book_key"`, and change the column list to `("shop_book_id", "key")`
- `ShopBookFieldUpdate`: `name="uq_shop_book_field_updates_shop_book_field"` (and `("shop_book_id", "field")`), Index name `"ix_shop_book_field_updates_shop_book_field"` with columns `"shop_book_id", "field"`
- `DiscoveredUrl` Index `"ix_discovered_urls_listing_id"` → `"ix_discovered_urls_shop_book_id"` on `"shop_book_id"`
- `ValidationIssue` CHECK: `"NOT (shop_book_id IS NOT NULL AND discovered_url_id IS NOT NULL)"`

- [ ] **Step 3: Rename relationships**

- `Shop.listings` → `Shop.shop_books: Mapped[list["ShopBook"]] = relationship(back_populates="shop")`
- In `ShopBook`: `shop = relationship(back_populates="shop_books")`
- In `ShopBook`: `prices`, `changes`, `attributes`, `discovered_urls` — flip every `back_populates="listing"` to `back_populates="shop_book"`
- `ShopBook.authors`: `secondary="shop_book_authors"`, `order_by="ShopBookAuthor.position"`
- In `Price`: `shop_book: Mapped["ShopBook"] = relationship(back_populates="prices")`
- In `ShopBookChange`: `shop_book: Mapped["ShopBook"] = relationship(back_populates="changes")`
- In `ShopBookAttribute`: `shop_book: Mapped["ShopBook"] = relationship(back_populates="attributes")`
- In `DiscoveredUrl`: `shop_book: Mapped["ShopBook | None"] = relationship(back_populates="discovered_urls")`
- In `ValidationIssue`: `shop_book: Mapped["ShopBook | None"] = relationship()`

- [ ] **Step 4: Rename enum reference on `ShopBook.type`**

Use `shop_book_type_enum` where `listing_type_enum` was referenced.

- [ ] **Step 5: Quick grep check inside this file**

Run: `Grep pattern="[Ll]isting" path="book_scraper/db/models.py"`
Expected: no matches.

> Do NOT commit yet. Proceed to Task 3.

---

## Task 3: Rename Scrapy items

**File:** `book_scraper/items.py`

- [ ] **Step 1: Rename class**

Change `class ListingItem(scrapy.Item):` to `class ShopBookItem(scrapy.Item):`. Update the docstring if it mentions "listing".

- [ ] **Step 2: Grep check**

Run: `Grep pattern="[Ll]isting" path="book_scraper/items.py"`
Expected: no matches.

---

## Task 4: Update the validation pipeline

**File:** `book_scraper/pipelines.py`

- [ ] **Step 1: Update import and references**

- Change `from book_scraper.items import ListingItem` → `... import ShopBookItem`.
- Replace every `ListingItem` → `ShopBookItem`. Rename any `process_listing_item` method → `process_shop_book_item`.
- Rename local vars `listing` → `shop_book` where they refer to a model row.

- [ ] **Step 2: Grep check**

Run: `Grep pattern="[Ll]isting" path="book_scraper/pipelines.py"`
Expected: no matches.

---

## Task 5: Update the repository

**File:** `book_scraper/db/repo.py`

- [ ] **Step 1: Update imports**

Replace:
```python
from book_scraper.db.models import (
    Category, DiscoveredUrl, Listing, ListingAttribute, ListingAuthor,
    ListingFieldUpdate, Price, ScrapeRun, Shop, ShopAuthor, ValidationIssue,
)
```
with:
```python
from book_scraper.db.models import (
    Category, DiscoveredUrl, Price, ScrapeRun, Shop, ShopAuthor, ShopBook,
    ShopBookAttribute, ShopBookAuthor, ShopBookChange, ShopBookFieldUpdate,
    ValidationIssue,
)
```

(`ShopBookChange` is needed if `get_listing_changes` used `ListingChange` directly — check and include.)

- [ ] **Step 2: Rename functions**

| Old | New |
|---|---|
| `upsert_listing` | `upsert_shop_book` |
| `_sync_listing_authors` | `_sync_shop_book_authors` |
| `touch_listing_field_updates` | `touch_shop_book_field_updates` |
| `mark_listings_inactive` | `mark_shop_books_inactive` |
| `link_discovered_url_to_listing` | `link_discovered_url_to_shop_book` |
| `get_listing_changes` | `get_shop_book_changes` |

- [ ] **Step 3: Rename parameters and local vars**

Every `listing_id: int` parameter → `shop_book_id: int`. Every local `listing` → `shop_book`. Every `.listing_id` column access → `.shop_book_id`. Every `Listing.__table__` / `Listing.column` → `ShopBook.*`. Every `ListingAttribute`, `ListingAuthor`, `ListingFieldUpdate`, `ListingChange` → the renamed class.

In `get_overview_stats()` (or equivalent): `select(func.count()).select_from(Listing)` → `... ShopBook`.

In `insert_price` / `bulk_insert_validation_issues`: argument `listing_id` → `shop_book_id`; `Price(listing_id=...)` → `Price(shop_book_id=...)`; `ValidationIssue(listing_id=...)` → `ValidationIssue(shop_book_id=...)`.

- [ ] **Step 4: Grep check**

Run: `Grep pattern="[Ll]isting" path="book_scraper/db/repo.py"`
Expected: no matches.

---

## Task 6: Update spiders

**Files:**
- `book_scraper/spiders/scan.py`
- `book_scraper/spiders/discover.py`
- `book_scraper/spiders/vaga/parsers.py`

- [ ] **Step 1: `scan.py`**

- `from book_scraper.items import ListingItem` → `ShopBookItem`.
- Every yielded `ListingItem(...)` → `ShopBookItem(...)`.

- [ ] **Step 2: `discover.py`**

- Import and call `mark_listings_inactive` → `mark_shop_books_inactive`.

- [ ] **Step 3: `vaga/parsers.py`**

- Import `ListingItem` → `ShopBookItem`.
- `parse_product_page` yields `ShopBookItem(...)`.

- [ ] **Step 4: Grep check across spiders**

Run: `Grep pattern="[Ll]isting" path="book_scraper/spiders/"`
Expected: no matches.

---

## Task 7: Update dashboard queries

**File:** `book_scraper/dashboard/queries.py`

- [ ] **Step 1: Update imports**

Replace `Listing`, `ListingAttribute`, `ListingFieldUpdate`, `ListingChange`, `ListingAuthor` → renamed classes.

- [ ] **Step 2: Rename query functions**

- `get_listings_page` → `get_shop_books_page`
- `get_listing_changes` → `get_shop_book_changes`

Rename every `listing_id` parameter → `shop_book_id`. Rename every `.listing_id` column ref → `.shop_book_id`. Rename local vars `listing` → `shop_book`, `listings` → `shop_books`.

- [ ] **Step 3: Grep check**

Run: `Grep pattern="[Ll]isting" path="book_scraper/dashboard/queries.py"`
Expected: no matches.

---

## Task 8: Update dashboard routes

**Files:**
- Rename: `book_scraper/dashboard/routes/listings.py` → `book_scraper/dashboard/routes/shop_books.py`
- Modify: the file that mounts routes (find with `Grep pattern="routes.listings|routes/listings" path="book_scraper/dashboard/"`; typically `app.py` or `__init__.py`)
- Modify: `book_scraper/dashboard/routes/scrape.py`

- [ ] **Step 1: Rename the routes file and update its body**

After renaming with `git mv book_scraper/dashboard/routes/listings.py book_scraper/dashboard/routes/shop_books.py`, replace the body so routes read `/shop-books` / `/shop-books/{shop_book_id}`, view functions are `shop_books_page` / `shop_book_detail`, `active_page` is `"shop_books"`, imports reference `ShopBook` and `get_shop_books_page`, `get_shop_book_changes`, and template names are `"shop_books.html"` / `"shop_book_detail.html"`. Context dict key `"listings"` → `"shop_books"`, `"listing"` → `"shop_book"`.

- [ ] **Step 2: Update the router import/mount**

Edit the dashboard app entry point: replace `from book_scraper.dashboard.routes import listings` (or equivalent) → `... import shop_books`; replace `app.include_router(listings.router)` → `app.include_router(shop_books.router)`.

- [ ] **Step 3: Update `scrape.py` redirect**

Any redirect to `/listings...` → `/shop-books...`. Any `active_page="listings"` → `"shop_books"` if present.

- [ ] **Step 4: Grep check across routes**

Run: `Grep pattern="[Ll]isting" path="book_scraper/dashboard/routes/"`
Expected: no matches.

---

## Task 9: Update dashboard templates

**Directory:** `book_scraper/dashboard/templates/`

- [ ] **Step 1: Rename the two listing-specific templates**

```bash
git mv book_scraper/dashboard/templates/listings.html \
       book_scraper/dashboard/templates/shop_books.html
git mv book_scraper/dashboard/templates/listing_detail.html \
       book_scraper/dashboard/templates/shop_book_detail.html
```

- [ ] **Step 2: Update content inside `shop_books.html` and `shop_book_detail.html`**

- Form `action="/listings"` → `action="/shop-books"`.
- Links `href="/listings"` / `href="/listings/{{ l.id }}"` → `/shop-books` / `/shop-books/{{ sb.id }}`.
- Loop vars: `{% for l in listings %}` → `{% for sb in shop_books %}`.
- Any `{{ listing.X }}` → `{{ shop_book.X }}`.
- Any breadcrumb/title text "Listing" → "Shop Book"; "Listings" → "Shop Books".
- Any stat pills / tab labels using "listings".

- [ ] **Step 3: Update cross-linking templates**

For each of these, rewrite `/listings` URLs → `/shop-books`, labels "Listing(s)" → "Shop Book(s)", and any template var `u.listing_id` → `u.shop_book_id`, `active_page == "listings"` → `"shop_books"`:

- `base.html` (nav link, line ~23)
- `shops.html`
- `shop_detail.html`
- `overview.html` (stat cards: `total_listings`, `active_listings` → `total_shop_books`, `active_shop_books` — also update the query/route that populates these)
- `validation.html`
- `validation_detail.html`
- `discovered_urls.html`
- `run_detail.html`
- `not_listed.html`

> Note: the stat var names `total_listings` / `active_listings` used in `overview.html` are populated from a query in `queries.py` or route in `routes/overview.py`. Rename both the template keys and the code that supplies them.

- [ ] **Step 4: Grep check across templates**

Run: `Grep pattern="[Ll]isting|listings?\.html|/listings" path="book_scraper/dashboard/templates/"`
Expected: no matches.

---

## Task 10: Update tests

**Directory:** `tests/`

- [ ] **Step 1: Rename integration test files**

```bash
git mv tests/integration/test_listing_authors.py tests/integration/test_shop_book_authors.py
git mv tests/integration/test_listing_type.py tests/integration/test_shop_book_type.py
git mv tests/integration/test_listings_filter_sort.py tests/integration/test_shop_books_filter_sort.py
```

- [ ] **Step 2: Update test file contents**

For every test file in `tests/unit/` and `tests/integration/`:

- Update imports: `Listing` → `ShopBook`, `ListingItem` → `ShopBookItem`, `ListingAttribute` → `ShopBookAttribute`, `ListingAuthor` → `ShopBookAuthor`, `ListingFieldUpdate` → `ShopBookFieldUpdate`, `ListingChange` → `ShopBookChange`.
- Update repo function imports: `upsert_listing` → `upsert_shop_book`, `mark_listings_inactive` → `mark_shop_books_inactive`, `link_discovered_url_to_listing` → `link_discovered_url_to_shop_book`, `get_listing_changes` → `get_shop_book_changes`.
- Update dashboard query imports: `get_listings_page` → `get_shop_books_page`.
- Rename test functions: `test_valid_listing_item_passes` → `test_valid_shop_book_item_passes`, `test_listing_item_without_title_dropped` → `test_shop_book_item_without_title_dropped`, `test_valid_listing_passes` → `test_valid_shop_book_passes`, `test_listing_without_title_dropped` → `test_shop_book_without_title_dropped`, `test_parse_product_yields_listing_item` → `test_parse_product_yields_shop_book_item`, `process_listing_item` → `process_shop_book_item`, and so on for every test whose name contains `listing`.
- Rename fixtures: local fixtures named `listing` / `listings` → `shop_book` / `shop_books`. Kwargs like `listing_id=...` → `shop_book_id=...`.
- Rename DB assertions: `session.query(Listing)` etc. → `ShopBook`. `.listing_id` → `.shop_book_id`.

- [ ] **Step 3: Update `test_dashboard_routes.py`**

Every `client.get("/listings")` → `client.get("/shop-books")`, every `/listings/1` → `/shop-books/1`, and any asserted text "Listing" / "Listings" → "Shop Book" / "Shop Books".

- [ ] **Step 4: Grep check across tests**

Run: `Grep pattern="[Ll]isting" path="tests/"`
Expected: no matches.

---

## Task 11: Update scripts

**Files:**
- Rename: `book_scraper/scripts/backfill_listing_attributes.py` → `backfill_shop_book_attributes.py`
- Modify: `backfill_authors.py`, `backfill_html_entities.py`

- [ ] **Step 1: Rename and update `backfill_shop_book_attributes.py`**

```bash
git mv book_scraper/scripts/backfill_listing_attributes.py \
       book_scraper/scripts/backfill_shop_book_attributes.py
```

Inside: `Listing` → `ShopBook`, `ListingAttribute` → `ShopBookAttribute`, `listing_id` → `shop_book_id`, log strings "listing" → "shop book", any `--listing-id` CLI flag → `--shop-book-id`.

- [ ] **Step 2: Update the remaining two scripts**

In `backfill_authors.py` and `backfill_html_entities.py`: replace `Listing` → `ShopBook` in imports and queries; update any local vars named `listing` → `shop_book`.

- [ ] **Step 3: Grep check**

Run: `Grep pattern="[Ll]isting" path="book_scraper/scripts/"`
Expected: no matches.

---

## Task 12: Update `CLAUDE.md`

**File:** `CLAUDE.md`

- [ ] **Step 1: Edit the Architecture section**

Replace:
```
- `listings` table stores full product metadata (title, author, ISBN, publisher, year, pages, etc.)
- `prices` table is append-only (one row per scrape per listing)
```
with:
```
- `shop_books` table stores full product metadata (title, author, ISBN, publisher, year, pages, etc.) — one row per book-as-it-appears-in-a-shop
- `prices` table is append-only (one row per scrape per shop_book)
```

- [ ] **Step 2: Update Post-Task Checklist example**

The commit hash reference stays (`f740448`), but update prose mentioning listings.

- [ ] **Step 3: Grep check**

Run: `Grep pattern="[Ll]isting" path="CLAUDE.md"`
Expected: no matches.

---

## Task 13: Global grep + verification

- [ ] **Step 1: Repo-wide grep**

Run: `Grep pattern="[Ll]isting" path="book_scraper/"` and `Grep pattern="[Ll]isting" path="tests/"`
Expected: no matches in either.

Historical plans and specs under `docs/superpowers/plans/` and `docs/superpowers/specs/` will still mention "listing" — that's correct, they document work done at an earlier point in time. Do not rewrite them.

- [ ] **Step 2: Apply the migration locally**

Run: `PYTHONPATH=. uv run alembic upgrade head`
Expected: "Running upgrade ... -> <new_hash>, rename listings to shop_books" and no errors.

- [ ] **Step 3: Spot-check the DB**

Run: `docker compose exec postgres psql -U postgres -d book_scraper -c "\dt"`
Expected: table list contains `shop_books`, `shop_book_authors`, `shop_book_attributes`, `shop_book_changes`, `shop_book_field_updates`. No `listings*` tables.

Run: `docker compose exec postgres psql -U postgres -d book_scraper -c "\d prices"`
Expected: `prices` has column `shop_book_id` referencing `shop_books(id)`.

- [ ] **Step 4: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass. (The integration fixtures will rebuild the test schema from the new migration.)

- [ ] **Step 5: Lint, format, typecheck**

Run:
- `uv run ruff check book_scraper/ tests/`
- `uv run ruff format book_scraper/ tests/`
- `uv run mypy book_scraper/`
Expected: all clean.

- [ ] **Step 6: Test the downgrade**

Run: `PYTHONPATH=. uv run alembic downgrade -1` then `PYTHONPATH=. uv run alembic upgrade head`.
Expected: both succeed, ending back on the new revision with all `shop_books*` tables.

---

## Task 14: Rebuild Docker, smoke test, crawl test

- [ ] **Step 1: Rebuild dashboard + scraper containers**

Run: `docker compose build dashboard scraper && docker compose up -d dashboard scraper`
Expected: containers come up healthy.

- [ ] **Step 2: Dashboard route smoke test**

Run: `uv run pytest tests/integration/test_dashboard_routes.py -v`
Expected: all routes return 200 on `/shop-books`, `/shop-books/{id}`, etc.

- [ ] **Step 3: Manually load a few dashboard pages**

Open in a browser: `http://localhost:8000/`, `http://localhost:8000/shop-books`, click through to a detail page.
Expected: pages render, no "Listing" text in the UI, navigation works, no 500s in the docker logs (`docker compose logs dashboard --tail 100`).

- [ ] **Step 4: Trigger a short scan to confirm the scraper is happy**

Pick one existing URL from `shop_books` (`docker compose exec postgres psql -U postgres -d book_scraper -c "SELECT url FROM shop_books LIMIT 1"`).
Run: `uv run scrapy crawl scan -a shop=vaga -a urls=<that-url>`
Expected: scan completes without errors, the row in `shop_books` gets a new `last_seen_at`, and a new row appears in `prices` with `shop_book_id` set.

---

## Task 15: Commit

- [ ] **Step 1: Stage everything**

```bash
git add -A
git status    # double-check: the migration file, models.py, items.py, pipelines.py, repo.py, spiders, dashboard/, tests/, scripts, CLAUDE.md. No stray junk.
```

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
refactor(data-model): rename listing to shop_book

Rename the concept end-to-end: DB tables (listings → shop_books and
its four child tables), FK columns (listing_id → shop_book_id in
prices, discovered_urls, validation_issues, and the four renamed
children), ORM classes, the Scrapy ShopBookItem, repository functions,
dashboard routes (/shop-books), templates, tests, and scripts.
Single atomic commit — DB schema and code match at every revision.
No 301 redirects for old /listings URLs: local dashboard only.
EOF
)"
```

- [ ] **Step 3: Verify a clean tree**

Run: `git status`
Expected: "nothing to commit, working tree clean".

---

## Self-Review Checklist

Before handing off / executing, re-read this plan and confirm:

- [ ] Every rename in the Scope Inventory maps to a task step.
- [ ] No step says "TBD", "similar to above", or "handle edge cases".
- [ ] Type names referenced in later tasks (`ShopBook`, `ShopBookItem`, etc.) match what Task 2 and Task 3 define.
- [ ] Migration `upgrade()` + `downgrade()` are exact mirrors.
- [ ] Every function name change in repo.py matches what's imported in routes, queries, tests, and scripts.
- [ ] Template rename order: the template files are renamed BEFORE the routes that reference them (or git tracks the rename regardless — either way, the route file should reference the new template names).
