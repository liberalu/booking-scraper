# Non-Book Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent non-book items from entering `shop_books` and delete existing ones.

**Architecture:** Two independent changes — (1) the scan spider swaps its title-only gate for the `is_book_product` flag already computed by the parser; (2) an Alembic migration deletes all existing `shop_books` rows with `type = 'non_book'` and marks their discovered URLs as `non_product` so they are never re-scraped.

**Tech Stack:** Python 3.12, Scrapy, SQLAlchemy 2.0, Alembic, pytest

---

### Task 1: Update scan spider to use `is_book_product` as the non-product gate

**Files:**
- Modify: `book_scraper/spiders/scan.py:213-221`
- Test: `tests/unit/test_spiders.py`

The scan spider already calls `self.parsers.parse_product_page(response.text)` which internally runs `classify_book_product()` and sets `data["is_book_product"]`. Currently the spider only checks `if not data.get("title")`. We replace that check with `if not data.get("is_book_product")`.

The existing test `test_parse_product_yields_non_book_product_item` currently asserts that a board-game page (title present but `is_book_product = False`) yields a `ShopBookItem` with `type = "non_book"`. After this change it must assert the opposite: no item yielded, URL marked `non_product`.

- [ ] **Step 1: Update the existing test to match the new expected behaviour**

Open `tests/unit/test_spiders.py`. Find the method `test_parse_product_yields_non_book_product_item` (around line 206). Replace it entirely:

```python
def test_parse_product_non_book_is_skipped(self):
    from book_scraper.spiders.scan import ScanSpider

    spider = ScanSpider(shop="vaga")
    html = """
    <html><body>
      <script type="application/ld+json">
        {"@type":"Product","name":"Stalo žaidimas \\"Teleloto\\"","sku":"1",
         "offers":{"price":"25.49","availability":"OutOfStock"},
         "brand":{"name":"Terra Publica"},
         "isRelatedTo":{"isbn":"4779054890696"}}
      </script>
      <script type="application/ld+json">
        {"@type":"BreadcrumbList","itemListElement":[
          {"name":"Žaislai ir žaidimai"},
          {"name":"Stalo žaidimai"},
          {"name":"Šeimos stalo žaidimai"}
        ]}
      </script>
    </body></html>
    """
    response = _fake_response(
        "https://vaga.lt/stalo-zaidimas-teleloto",
        html,
        meta={"discovered_url_id": 3},
    )
    items = list(spider.parse_product(response))
    shop_book_items = [i for i in items if isinstance(i, ShopBookItem)]
    assert shop_book_items == []
    assert spider._url_status_updates[-1]["url_type"] == "non_product"
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/unit/test_spiders.py::TestScanSpider::test_parse_product_non_book_is_skipped -v
```

Expected: **FAIL** — the spider still yields a `ShopBookItem` and marks URL as `"product"`.

- [ ] **Step 3: Apply the one-line change in `scan.py`**

Open `book_scraper/spiders/scan.py`. Find the block at approximately line 213:

```python
        if not data.get("title"):
            self._queue_url_status_update(
                discovered_url_id,
                http_status=200,
                url_type="non_product",
                scrape_url_item_id=scrape_url_item_id,
                success=False,
            )
            return
```

Change `not data.get("title")` to `not data.get("is_book_product")`:

```python
        if not data.get("is_book_product"):
            self._queue_url_status_update(
                discovered_url_id,
                http_status=200,
                url_type="non_product",
                scrape_url_item_id=scrape_url_item_id,
                success=False,
            )
            return
```

- [ ] **Step 4: Run the updated test and the full unit suite**

```bash
uv run pytest tests/unit/test_spiders.py -v
```

Expected: all tests **PASS**. The renamed test now passes; the book-product test that asserts `url_type == "product"` for a real book must still pass.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/spiders/scan.py tests/unit/test_spiders.py
git commit -m "fix: skip non-book items in scan spider using is_book_product flag"
```

---

### Task 2: Alembic migration — delete existing non_book shop_books

**Files:**
- Create: `alembic/versions/<hash>_delete_non_book_shop_books.py`

The migration must run in FK-safe order:
1. Mark `discovered_urls.url_type = 'non_product'` for URLs whose `shop_book_id` is a non_book — prevents re-creation on the next scan.
2. Delete from `prices`, `shop_book_changes`, `validation_issues` where `shop_book_id` is in the non_book set (these FKs have no `ON DELETE CASCADE` at the DB level).
3. Delete from `shop_books WHERE type = 'non_book'` — tables with `ON DELETE CASCADE` (`shop_book_attributes`, `shop_book_authors`, `shop_book_field_updates`) are cleaned up automatically by the DB.

`downgrade()` is a no-op: deleted data is not recoverable and restoring it would be wrong.

- [ ] **Step 1: Generate the migration file**

```bash
PYTHONPATH=. uv run alembic revision -m "delete_non_book_shop_books"
```

This creates a file like `alembic/versions/<autohash>_delete_non_book_shop_books.py`. Open it. (Also update the `**Files:** Create:` path above to match the real filename.)

- [ ] **Step 2: Write the migration body**

Replace the generated `upgrade()` and `downgrade()` with:

```python
def upgrade() -> None:
    # Step 1: mark discovered_urls as non_product so they are never re-scanned
    op.execute("""
        UPDATE discovered_urls
        SET url_type = 'non_product'
        WHERE shop_book_id IN (
            SELECT id FROM shop_books WHERE type = 'non_book'
        )
    """)

    # Step 2: delete dependent rows that lack ON DELETE CASCADE
    op.execute("""
        DELETE FROM prices
        WHERE shop_book_id IN (
            SELECT id FROM shop_books WHERE type = 'non_book'
        )
    """)
    op.execute("""
        DELETE FROM shop_book_changes
        WHERE shop_book_id IN (
            SELECT id FROM shop_books WHERE type = 'non_book'
        )
    """)
    op.execute("""
        DELETE FROM validation_issues
        WHERE shop_book_id IN (
            SELECT id FROM shop_books WHERE type = 'non_book'
        )
    """)

    # Step 3: delete the non_book shop_books themselves
    # (shop_book_attributes, shop_book_authors, shop_book_field_updates
    #  have ON DELETE CASCADE and are cleaned up automatically)
    op.execute("DELETE FROM shop_books WHERE type = 'non_book'")


def downgrade() -> None:
    pass  # data deletion is not reversible
```

- [ ] **Step 3: Run the migration against the test DB to verify it works**

```bash
PYTHONPATH=. uv run alembic -x db=test upgrade head
```

Expected: migration applies cleanly with no FK violation errors.

- [ ] **Step 4: Run the integration test suite**

```bash
uv run pytest tests/integration/ -v
```

Expected: all tests **PASS**.

- [ ] **Step 5: Run the migration against the main DB**

```bash
PYTHONPATH=. uv run alembic upgrade head
```

Expected: applies cleanly.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/<autohash>_delete_non_book_shop_books.py
git commit -m "feat: migration to delete non_book shop_books and mark their URLs as non_product"
```

---

### Task 3: Full test run and smoke test

- [ ] **Step 1: Run the complete test suite**

```bash
uv run pytest -v
```

Expected: all tests **PASS**.

- [ ] **Step 2: Rebuild and restart containers**

```bash
docker compose build scraper dashboard && docker compose up -d scraper dashboard
```

- [ ] **Step 3: Smoke test the dashboard routes**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all routes respond correctly.

- [ ] **Step 4: Verify item 19502 (or similar non-book) is gone**

Open `http://localhost:8000/shop-books/19502` in the browser.

Expected: **404 "Shop book not found"** — the record no longer exists.
