# tytoalba.lt Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Onboard tytoalba.lt as the fifth shop in the scraper using the `sitemap` discovery strategy plus a JSON-LD-first product parser.

**Architecture:** Custom-PHP shop, ~800 LT books. Discovery is a single GET to `products.xml?locale=LT&limit=2000` (799 URLs). Product pages carry two JSON-LD blocks (`Product` + `BreadcrumbList`) plus a spec block of `<div data-attribute-name=… data-attribute-values='[…]'>` rows. The parser prefers JSON-LD for the canonical fields (title / sku=ISBN / brand=author / offers.price / availability / image) and falls back to spec attributes for year / pages / cover-type / translator / original title. No FlareSolverr, no GraphQL, no `categories` strategy — at 800 URLs the per-product scan is cheap enough that a fast-rescan path is unnecessary in v1.

**Tech Stack:** Scrapy + asyncio, SQLAlchemy 2.0 (Postgres), TOML per-shop config, pytest. Reuses `book_scraper.spiders.vaga.parsers.classify_book_product` / `infer_shop_book_type`, `book_scraper.spiders.cover_type.format_from_cover_type`, `book_scraper.isbn.is_valid_isbn` / `normalize_isbn` — same composition pattern as `patogupirkti/parsers.py`.

---

## File Structure

**Create:**
- `config/shops/tytoalba.toml` — shop config (sitemap-only, plain HTTP).
- `book_scraper/spiders/tytoalba/__init__.py` — empty marker.
- `book_scraper/spiders/tytoalba/parsers.py` — `parse_sitemap_urls`, `parse_product_page`. (No `parse_category_page` for v1.)
- `tests/fixtures/tytoalba/sitemap_index.xml` — captured `https://www.tytoalba.lt/sitemap.xml`.
- `tests/fixtures/tytoalba/products.xml` — captured `products.xml?locale=LT&offset=0&limit=2000` (truncated to ~10 entries to keep the fixture small).
- `tests/fixtures/tytoalba/product_page.html` — captured `https://www.tytoalba.lt/jeruzale`.
- `tests/fixtures/tytoalba/product_page_no_discount.html` — a second product without the `<s data-priceold>` strikethrough, to lock the no-discount branch.
- `tests/unit/test_tytoalba_parsers.py` — parser tests.

**Modify:** none. Spiders auto-load via `book_scraper.spiders.registry.load_parsers(shop_name)`. The pipeline auto-creates the `shops` row on first item via `_get_shop_id` → `upsert_shop` (`book_scraper/pipelines.py:455`). No alembic migration, no scrapy boilerplate edits.

**Out of scope for this plan** (track as follow-ups, not blockers):
- `parse_category_page` for fast price-only rescans — defer until per-product scan time becomes a problem (at ~800 URLs × 0.5s/req it's ~7 min; not a problem).
- Cron schedule entry — separate change to whatever wires shop crons (verify against `scripts/generate_crontab.py` once parser lands).
- React dashboard SHOPS dropdown wiring (`hf-overlays.jsx`, `hf-parser.jsx`) — cosmetic; current dashboard reads shop list from DB.
- Description extraction — JSON-LD description on tytoalba is an SEO keyword blob, not prose. Real description sits in `<div class="description-outer">` and is left for a follow-up.

---

## Task 1: Capture fixtures from the live site

**Files:**
- Create: `tests/fixtures/tytoalba/sitemap_index.xml`
- Create: `tests/fixtures/tytoalba/products.xml`
- Create: `tests/fixtures/tytoalba/product_page.html`
- Create: `tests/fixtures/tytoalba/product_page_no_discount.html`

- [ ] **Step 1: Save the sitemap index**

```bash
mkdir -p tests/fixtures/tytoalba
curl -sS -A "Mozilla/5.0" https://www.tytoalba.lt/sitemap.xml \
  -o tests/fixtures/tytoalba/sitemap_index.xml
```

Verify: `head -3 tests/fixtures/tytoalba/sitemap_index.xml` — first line should be `<?xml version="1.0" encoding="UTF-8"?>`, the body should contain `<sitemapindex …>` with a child `<loc>https://www.tytoalba.lt/products.xml?locale=LT&amp;offset=0&amp;limit=2000</loc>`.

- [ ] **Step 2: Save the LT product sitemap, truncated for fixture compactness**

```bash
curl -sS -A "Mozilla/5.0" \
  "https://www.tytoalba.lt/products.xml?locale=LT&offset=0&limit=2000" \
  > /tmp/tytoalba_products_full.xml

# Keep first 10 <url> entries to keep the fixture under a few KB.
python3 - <<'PY'
import re
src = open("/tmp/tytoalba_products_full.xml", encoding="utf-8").read()
# Match the urlset wrapper + first 10 <url>...</url> blocks.
opener = re.search(r"<urlset[^>]*>", src).group(0)
urls = re.findall(r"<url>.*?</url>", src, flags=re.S)[:10]
xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + opener + "".join(urls) + "</urlset>"
open("tests/fixtures/tytoalba/products.xml", "w", encoding="utf-8").write(xml)
PY
```

Verify: `grep -c "<loc>" tests/fixtures/tytoalba/products.xml` prints `10`.

- [ ] **Step 3: Save the canonical product page (Jeruzalė — has discount, all spec fields populated)**

```bash
curl -sS -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
  https://www.tytoalba.lt/jeruzale \
  -o tests/fixtures/tytoalba/product_page.html
```

Verify: `grep -c '"@type":"Product"' tests/fixtures/tytoalba/product_page.html` prints `1`; `grep -c '"@type":"BreadcrumbList"' tests/fixtures/tytoalba/product_page.html` prints `1`.

- [ ] **Step 4: Save a second product without the strikethrough discount**

Pick any URL from `products.xml` whose price block lacks `data-priceold`. From `tests/fixtures/tytoalba/products.xml` pick the second `<loc>` (e.g. `https://www.tytoalba.lt/merginos-is-bostono-knyga-su-defektais` or whichever `<loc>` is at index 1) and confirm:

```bash
URL=$(python3 -c "import re; xml=open('tests/fixtures/tytoalba/products.xml').read(); print(re.findall(r'<loc>([^<]+)</loc>', xml)[1])")
echo "$URL"
curl -sS -A "Mozilla/5.0" "$URL" -o /tmp/tytoalba_alt.html
grep -c 'data-priceold' /tmp/tytoalba_alt.html  # if 0 → use this; if >0 try the next URL
```

If `data-priceold` count is `0`, save it:

```bash
cp /tmp/tytoalba_alt.html tests/fixtures/tytoalba/product_page_no_discount.html
```

If every probed URL has a discount, fall back to a second discounted product — note the swap in the test docstring and adjust the price-overlay test to use a different fixture pair. (Discount is common on tytoalba, so a no-discount fixture may need 2–3 probes.)

- [ ] **Step 5: Commit fixtures**

```bash
git add tests/fixtures/tytoalba/
git commit -m "test(tytoalba): capture sitemap + product page fixtures"
```

---

## Task 2: Scaffold spider package and config

**Files:**
- Create: `book_scraper/spiders/tytoalba/__init__.py`
- Create: `book_scraper/spiders/tytoalba/parsers.py`
- Create: `config/shops/tytoalba.toml`

- [ ] **Step 1: Create the empty package marker**

```bash
mkdir -p book_scraper/spiders/tytoalba
: > book_scraper/spiders/tytoalba/__init__.py
```

- [ ] **Step 2: Create the shop TOML config**

Write `config/shops/tytoalba.toml` with:

```toml
[shop]
name = "tytoalba"
base_url = "https://www.tytoalba.lt"

[scraping]
# tytoalba is plain Apache/PHP — no Cloudflare, no rate limiting observed
# on calibration probes (2026-05-07: 5/5 sequential GETs OK in <1s each).
# Default pacing matches vaga's profile; can be tuned downward via
# shop_settings DB row if the host complains.
download_delay = 0.3
concurrent_requests_per_domain = 6
batch_size = 100
batch_pause = 10
max_retries = 2

connect_timeout = 5
read_timeout = 15
hard_timeout = 30
batch_timeout = 300

[discover]
# Product permalinks are clean slugs at the root: /jeruzale, /morgano-kelias.
# This pattern excludes /knygos/<category>, /<author-slug>, and the
# article/menu/image sub-sitemap entries that the LT product sitemap
# happens to not include anyway. Belt-and-braces.
url_include_pattern = "^https://www\\.tytoalba\\.lt/[a-z0-9][a-z0-9-]+$"

[discover.sitemap]
# `products.xml?locale=LT&limit=2000` returns the full LT catalogue
# (~800 URLs, single response). The site sitemap.xml is a sitemap-of-
# sitemaps that also points to images.xml + articles.xml + menu.xml; we
# go straight to the LT product feed to skip those.
url = "https://www.tytoalba.lt/products.xml?locale=LT&offset=0&limit=2000"
max_age_hours = 168

[scan]
# Reads from discovered_urls table; no URL needed.
```

- [ ] **Step 3: Create the parser stub with all three contract functions raising `NotImplementedError`**

Write `book_scraper/spiders/tytoalba/parsers.py`:

```python
"""Parsers for tytoalba.lt — custom PHP shop, ~800-book LT catalogue.

Discovery: single GET to `products.xml?locale=LT&limit=2000` returns
the full LT product list (~800 URLs).

Product page: two JSON-LD blocks (`Product` with sku=ISBN +
`BreadcrumbList`) carry the canonical fields; a `<div
data-attribute-name="…" data-attribute-values='[…]'>` block fills in
year / pages / cover_type / translator / original title / source
language.
"""

from __future__ import annotations

from book_scraper.spiders.parser_types import ProductPageResult


def parse_sitemap_urls(xml_content: str) -> list[str]:
    raise NotImplementedError


def parse_product_page(html: str) -> ProductPageResult:
    raise NotImplementedError
```

- [ ] **Step 4: Verify the registry can import the module**

```bash
PYTHONPATH=. uv run python -c "from book_scraper.spiders.registry import load_parsers; m = load_parsers('tytoalba'); print(m.parse_sitemap_urls, m.parse_product_page)"
```

Expected: prints two `<function …>` reprs; no ImportError.

- [ ] **Step 5: Commit scaffold**

```bash
git add book_scraper/spiders/tytoalba/ config/shops/tytoalba.toml
git commit -m "feat(tytoalba): scaffold spider package + TOML config"
```

---

## Task 3: Implement and test `parse_sitemap_urls`

**Files:**
- Modify: `book_scraper/spiders/tytoalba/parsers.py`
- Test: `tests/unit/test_tytoalba_parsers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tytoalba_parsers.py`:

```python
"""Unit tests for the tytoalba.lt parser module.

tytoalba is a small (~800-book) custom PHP shop. Discovery uses a single
LT-locale-filtered product sitemap; product pages carry rich JSON-LD
plus a `data-attribute-name` spec block.
"""

from pathlib import Path

from book_scraper.spiders.tytoalba.parsers import (
    parse_product_page,
    parse_sitemap_urls,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "tytoalba"


def test_parse_sitemap_urls_returns_lt_product_urls():
    xml = (FIXTURES / "products.xml").read_text(encoding="utf-8")
    urls = parse_sitemap_urls(xml)
    assert urls
    # All URLs are absolute https://www.tytoalba.lt/<slug> with no path.
    assert all(u.startswith("https://www.tytoalba.lt/") for u in urls)
    # Truncated fixture has 10 <url> entries.
    assert len(urls) == 10
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py::test_parse_sitemap_urls_returns_lt_product_urls -v
```

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `parse_sitemap_urls`**

In `book_scraper/spiders/tytoalba/parsers.py` replace the stub and the import block:

```python
from __future__ import annotations

import xml.etree.ElementTree as ET

from book_scraper.spiders.parser_types import ProductPageResult

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def parse_sitemap_urls(xml_content: str) -> list[str]:
    """Extract product URLs from a tytoalba `<urlset>`.

    The shop's top-level sitemap.xml is a `<sitemapindex>` pointing at
    `products.xml?locale=LT&offset=0&limit=2000` (and three non-product
    sub-sitemaps: menu, articles, images). The discover spider is
    configured to fetch the LT product feed directly, so this parser
    only handles the flat `<urlset>` shape.
    """
    root = ET.fromstring(xml_content)
    return [
        loc.text
        for loc in root.findall(f".//{_SITEMAP_NS}loc")
        if loc.text is not None
    ]


def parse_product_page(html: str) -> ProductPageResult:
    raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py::test_parse_sitemap_urls_returns_lt_product_urls -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/spiders/tytoalba/parsers.py tests/unit/test_tytoalba_parsers.py
git commit -m "feat(tytoalba): parse_sitemap_urls — flat LT product feed"
```

---

## Task 4: Implement product-page core fields from JSON-LD

This task lands `title`, `isbn`, `author`, `image_url`, `price`, `in_stock`, `description=None`, plus the empty defaults for the rest of the `ProductPageResult` shape. Spec attributes, breadcrumbs, price overlay, and classification follow in later tasks.

**Files:**
- Modify: `book_scraper/spiders/tytoalba/parsers.py`
- Modify: `tests/unit/test_tytoalba_parsers.py`

- [ ] **Step 1: Write failing tests for JSON-LD core fields**

Append to `tests/unit/test_tytoalba_parsers.py`:

```python
def test_parse_product_page_extracts_jsonld_core_fields():
    """Title / ISBN (=sku) / author (=brand) / image / price / in_stock
    come from the schema.org Product JSON-LD block."""
    html = (FIXTURES / "product_page.html").read_text(encoding="utf-8")
    data = parse_product_page(html)

    assert data["title"] == "Jeruzalė"
    assert data["isbn"] == "9786094665035"
    assert data["sku"] == "9786094665035"
    assert data["author"] == "Simon Sebag Montefiore"
    assert data["image_url"] == "https://www.tytoalba.lt/images/uploader/je/jeruzale-1.jpg"
    assert data["price"] == "13"
    assert data["in_stock"] is True


def test_parse_product_page_returns_full_default_shape():
    """Every key in `ProductPageResult` is present even when the source
    page doesn't populate it — the scan pipeline reads keys positionally."""
    html = (FIXTURES / "product_page.html").read_text(encoding="utf-8")
    data = parse_product_page(html)
    expected_keys = {
        "title", "description", "price", "price_original", "in_stock",
        "isbn", "sku", "publisher", "image_url", "categories",
        "year", "pages", "author", "cover_type", "format",
        "duration", "narrator", "translator", "schema_types",
        "is_book_product", "book_score", "book_score_reasons", "type",
        "planned_availability_date", "rating", "review_count",
    }
    assert set(data.keys()) >= expected_keys
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py -v
```

Expected: both new tests FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement the JSON-LD slice of `parse_product_page`**

In `book_scraper/spiders/tytoalba/parsers.py`, replace the `parse_product_page` stub. Add the new imports at the top of the file too:

```python
from __future__ import annotations

import contextlib
import html as html_module
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, cast

from book_scraper.isbn import is_valid_isbn, normalize_isbn
from book_scraper.spiders.parser_types import ProductPageResult

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def parse_sitemap_urls(xml_content: str) -> list[str]:
    """Extract product URLs from a tytoalba `<urlset>`."""
    root = ET.fromstring(xml_content)
    return [
        loc.text
        for loc in root.findall(f".//{_SITEMAP_NS}loc")
        if loc.text is not None
    ]


_JSONLD_BLOCK_RE = re.compile(
    r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
    re.S,
)


def _unescape(value: object) -> object:
    return html_module.unescape(value) if isinstance(value, str) else value


def _empty_product_data() -> dict[str, object]:
    return {
        "title": None,
        "description": None,
        "price": None,
        "price_original": None,
        "in_stock": None,
        "isbn": None,
        "sku": None,
        "publisher": None,
        "image_url": None,
        "categories": [],
        "year": None,
        "pages": None,
        "author": None,
        "cover_type": None,
        "format": None,
        "duration": None,
        "narrator": None,
        "translator": None,
        "schema_types": [],
        "is_book_product": False,
        "book_score": 0,
        "book_score_reasons": [],
        "type": "book",
        "planned_availability_date": None,
        "rating": None,
        "review_count": None,
    }


def _iter_jsonld_blocks(html: str) -> list[dict[str, Any]]:
    """Yield each parsed JSON-LD object embedded in the page."""
    blocks: list[dict[str, Any]] = []
    for raw in _JSONLD_BLOCK_RE.findall(html):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            blocks.append(obj)
    return blocks


def parse_product_page(html: str) -> ProductPageResult:
    """Parse a tytoalba.lt product page response.

    JSON-LD `Product` block carries: name, sku (=ISBN), brand
    (=author, plain string), image, offers.price, offers.availability.
    JSON-LD `BreadcrumbList` carries the category chain. Spec
    attributes (year / pages / cover-type / translator / original
    title / source language) are pulled later from the
    `<div data-attribute-name="…" data-attribute-values='[…]'>` rows
    above the description tabs.
    """
    data = _empty_product_data()
    schema_types: set[str] = set()

    for block in _iter_jsonld_blocks(html):
        ld_type = block.get("@type", "")
        if isinstance(ld_type, list):
            ld_types = [str(v) for v in ld_type]
        elif ld_type:
            ld_types = [str(ld_type)]
        else:
            ld_types = []
        schema_types.update(ld_types)

        if "Product" in ld_types or "Book" in ld_types:
            data["title"] = _unescape(block.get("name"))
            sku_raw = block.get("sku")
            if isinstance(sku_raw, str):
                normalized = normalize_isbn(sku_raw)
                if is_valid_isbn(normalized):
                    data["isbn"] = normalized
                    data["sku"] = normalized
                else:
                    # Keep sku for traceability even when it's not a valid ISBN.
                    data["sku"] = sku_raw
            brand = block.get("brand")
            if isinstance(brand, str) and brand.strip():
                data["author"] = _unescape(brand.strip())
            elif isinstance(brand, dict):
                data["author"] = _unescape(brand.get("name"))
            image = block.get("image")
            if isinstance(image, str):
                data["image_url"] = image
            elif isinstance(image, list) and image:
                data["image_url"] = image[0]
            offers = block.get("offers")
            if isinstance(offers, dict):
                price_raw = offers.get("price")
                if price_raw is not None:
                    data["price"] = str(price_raw)
                availability = offers.get("availability")
                if isinstance(availability, str):
                    data["in_stock"] = availability.endswith("InStock")

    data["schema_types"] = sorted(schema_types)
    return cast(ProductPageResult, data)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py -v
```

Expected: 3 tests PASS (sitemap + 2 new product-page tests).

- [ ] **Step 5: Commit**

```bash
git add book_scraper/spiders/tytoalba/parsers.py tests/unit/test_tytoalba_parsers.py
git commit -m "feat(tytoalba): parse_product_page — JSON-LD core fields"
```

---

## Task 5: Extract categories from the BreadcrumbList JSON-LD

**Files:**
- Modify: `book_scraper/spiders/tytoalba/parsers.py`
- Modify: `tests/unit/test_tytoalba_parsers.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_parse_product_page_extracts_categories_from_breadcrumb():
    """BreadcrumbList drops the universal 'Pradžia' root and the trailing
    product-title item, leaving the actual category chain."""
    html = (FIXTURES / "product_page.html").read_text(encoding="utf-8")
    data = parse_product_page(html)
    assert data["categories"] == ["Knygos", "Negrožinė", "Kelionės"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py::test_parse_product_page_extracts_categories_from_breadcrumb -v
```

Expected: FAIL — `data["categories"]` is `[]`.

- [ ] **Step 3: Add the BreadcrumbList branch inside the JSON-LD loop**

In `parse_product_page`, inside the `for block in _iter_jsonld_blocks(html):` loop, after the `if "Product" in ld_types or "Book" in ld_types:` arm, add:

```python
        if "BreadcrumbList" in ld_types:
            items = block.get("itemListElement", [])
            names: list[str] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                inner = item.get("item")
                if isinstance(inner, dict):
                    name = inner.get("name")
                else:
                    name = item.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(html_module.unescape(name.strip()))
            # Drop the universal "Pradžia" root (every product carries it)
            # and the trailing item which is the product title itself.
            if names and names[0].lower() == "pradžia":
                names = names[1:]
            if len(names) > 1:
                names = names[:-1]
            data["categories"] = names
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/spiders/tytoalba/parsers.py tests/unit/test_tytoalba_parsers.py
git commit -m "feat(tytoalba): extract categories from BreadcrumbList"
```

---

## Task 6: Extract spec attributes (year / pages / cover_type / translator / original title / source language)

The spec block uses one row per attribute, each shaped like:

```html
<div class="bt1 attribute product-attribute "
     data-attribute-name="Metai"
     data-attribute-values='["2020"]'>
  …
</div>
```

`data-attribute-values` is a JSON array (single-element in practice) whose first value is what we want.

**Files:**
- Modify: `book_scraper/spiders/tytoalba/parsers.py`
- Modify: `tests/unit/test_tytoalba_parsers.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_parse_product_page_extracts_spec_attributes():
    """Spec block populates year/pages/cover_type/format/translator and
    properties.original_title / properties.source_language."""
    html = (FIXTURES / "product_page.html").read_text(encoding="utf-8")
    data = parse_product_page(html)
    assert data["year"] == 2020
    assert data["pages"] == 698
    assert data["cover_type"] == "kietas"
    assert data["format"] == "hardcover"  # via format_from_cover_type
    assert data["translator"] == "Laimantas Jonušys"
    properties = data.get("properties")
    assert isinstance(properties, dict)
    assert properties["original_title"] == "Jerusalem: The Biography"
    assert properties["source_language"] == "anglų k."
```

Note: `properties` is not a top-level key on `ProductPageResult` — it's an extension dict that the pipeline persists into the JSONB `properties` column on `shop_books`. Both `vaga` and `patogupirkti` parsers attach it the same way (`data["properties"] = properties`), so adding it for tytoalba follows the established pattern.

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py::test_parse_product_page_extracts_spec_attributes -v
```

Expected: FAIL — `data["year"]` is `None`.

- [ ] **Step 3: Implement the spec-attribute extractor**

Add at the top of the file, after the existing imports:

```python
from book_scraper.spiders.cover_type import format_from_cover_type
```

Add helper + caller. Place these after `_iter_jsonld_blocks` and before `parse_product_page`:

```python
# Each spec row looks like:
#   <div class="bt1 attribute product-attribute "
#        data-attribute-slug=""
#        data-attribute-name="Metai"
#        data-attribute-values='["2020"]'>
# `data-attribute-values` is JSON; we read the first array element.
_ATTR_ROW_RE = re.compile(
    r'data-attribute-name="([^"]+)"\s+'
    r"data-attribute-values='(\[[^']*\])'",
    re.S,
)


def _extract_spec_attributes(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_name, raw_values in _ATTR_ROW_RE.findall(html):
        name = html_module.unescape(raw_name).strip()
        try:
            values = json.loads(raw_values)
        except json.JSONDecodeError:
            continue
        if not isinstance(values, list) or not values:
            continue
        first = values[0]
        if not isinstance(first, str):
            continue
        first = html_module.unescape(first).strip()
        if name and first:
            out[name] = first
    return out
```

Inside `parse_product_page`, after the JSON-LD loop and before the final `data["schema_types"] = sorted(schema_types)` line, add:

```python
    spec = _extract_spec_attributes(html)

    if (year_raw := spec.get("Metai")) is not None:
        with contextlib.suppress(ValueError):
            data["year"] = int(year_raw)
    if (pages_raw := spec.get("Puslapių skaičius")) is not None:
        with contextlib.suppress(ValueError):
            data["pages"] = int(pages_raw)
    if (cover := spec.get("Įrišimas")) is not None:
        data["cover_type"] = cover
        data["format"] = format_from_cover_type(cover)
    # Tytoalba labels the translator as "Vertė" (NOT "Vertėjas" — that
    # would shadow the Lithuanian word for "value"). Confirmed against
    # the Jeruzalė fixture: data-attribute-name="Vertė" → "Laimantas
    # Jonušys".
    if (translator := spec.get("Vertė")) is not None:
        data["translator"] = translator
    if data["isbn"] is None and (isbn_s := spec.get("ISBN")) is not None:
        normalized = normalize_isbn(isbn_s)
        if is_valid_isbn(normalized):
            data["isbn"] = normalized
            data["sku"] = data["sku"] or normalized

    properties: dict[str, Any] = {}
    if (orig_title := spec.get("Orig. pav.")) is not None:
        properties["original_title"] = orig_title
    if (source_lang := spec.get("Versta iš")) is not None:
        properties["source_language"] = source_lang
    if properties:
        data["properties"] = properties
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/spiders/tytoalba/parsers.py tests/unit/test_tytoalba_parsers.py
git commit -m "feat(tytoalba): extract spec attributes (year/pages/cover/translator)"
```

---

## Task 7: Extract original price from the strikethrough markup

The current price comes from JSON-LD `offers.price`. When a discount is active, tytoalba shows the pre-discount value as `<s … data-priceold="20">…</s>`. When there's no discount that element is absent and `price_original` stays `None`.

**Files:**
- Modify: `book_scraper/spiders/tytoalba/parsers.py`
- Modify: `tests/unit/test_tytoalba_parsers.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_parse_product_page_extracts_original_price_when_discounted():
    """`<s … data-priceold="N">` carries the pre-discount price as a
    plain decimal. Only emitted when a discount is active."""
    html = (FIXTURES / "product_page.html").read_text(encoding="utf-8")
    data = parse_product_page(html)
    assert data["price"] == "13"
    assert data["price_original"] == "20"


def test_parse_product_page_no_discount_leaves_original_price_none():
    html = (FIXTURES / "product_page_no_discount.html").read_text(encoding="utf-8")
    data = parse_product_page(html)
    assert data["price"] is not None
    assert data["price_original"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py -v
```

Expected: the discount test FAILs (`price_original` is `None`); the no-discount test PASSes incidentally.

- [ ] **Step 3: Implement the price overlay**

After the spec-attribute block in `parse_product_page` (still before `data["schema_types"] = …`), add:

```python
    # `<s … data-priceold="20">…</s>` carries the pre-discount price as a
    # plain decimal string. Absent when the product isn't discounted.
    old_match = re.search(
        r'<s[^>]+data-priceold="([\d.,]+)"',
        html,
    )
    if old_match:
        data["price_original"] = old_match.group(1).replace(",", ".")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/spiders/tytoalba/parsers.py tests/unit/test_tytoalba_parsers.py
git commit -m "feat(tytoalba): extract pre-discount price from data-priceold"
```

---

## Task 8: Wire classification + type inference (re-use vaga's classifier)

**Files:**
- Modify: `book_scraper/spiders/tytoalba/parsers.py`
- Modify: `tests/unit/test_tytoalba_parsers.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_parse_product_page_classifies_book_product():
    """A product with valid ISBN, author, year, pages and a book
    breadcrumb should pass the shared classifier as `is_book_product`
    with `type="book"`."""
    html = (FIXTURES / "product_page.html").read_text(encoding="utf-8")
    data = parse_product_page(html)
    assert data["is_book_product"] is True
    assert data["type"] == "book"
    assert data["book_score"] >= 3
    assert any(
        r["key"] == "valid_isbn" and r["points"] == 3
        for r in data["book_score_reasons"]
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py::test_parse_product_page_classifies_book_product -v
```

Expected: FAIL — `is_book_product` is `False` (default).

- [ ] **Step 3: Wire the shared classifier**

Add to imports at the top of `book_scraper/spiders/tytoalba/parsers.py`:

```python
from book_scraper.spiders.vaga.parsers import (
    classify_book_product,
    infer_shop_book_type,
)
```

At the end of `parse_product_page`, before the `return cast(...)` line, add:

```python
    classification = classify_book_product(data)
    data["is_book_product"] = classification.is_book_product
    data["book_score"] = classification.score
    data["book_score_reasons"] = classification.reasons
    data["type"] = infer_shop_book_type(data)
```

(The existing `data["schema_types"] = sorted(schema_types)` line stays where it is, just before this new block.)

- [ ] **Step 4: Run all tytoalba tests**

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 5: Run the full unit suite to confirm no cross-shop regressions**

```bash
PYTHONPATH=. uv run pytest tests/unit/ -v
```

Expected: every existing test still PASSes alongside the 8 new tytoalba tests.

- [ ] **Step 6: Commit**

```bash
git add book_scraper/spiders/tytoalba/parsers.py tests/unit/test_tytoalba_parsers.py
git commit -m "feat(tytoalba): plug into shared book classifier + type inference"
```

---

## Task 9: Lint, type-check, format

**Files:** none (verification only).

- [ ] **Step 1: Ruff lint**

```bash
uv run ruff check book_scraper/spiders/tytoalba/ tests/unit/test_tytoalba_parsers.py
```

Expected: `All checks passed!`. Fix any reported issues (re-running until clean) before continuing.

- [ ] **Step 2: Ruff format**

```bash
uv run ruff format book_scraper/spiders/tytoalba/ tests/unit/test_tytoalba_parsers.py
```

Expected: `… reformatted` or `unchanged`. Then re-run the parser tests to confirm formatting didn't break anything:

```bash
PYTHONPATH=. uv run pytest tests/unit/test_tytoalba_parsers.py -v
```

- [ ] **Step 3: mypy strict**

```bash
uv run mypy book_scraper/
```

Expected: `Success: no issues found`. If mypy complains about the `properties` key (it's not on `ProductPageResult`), the `cast(ProductPageResult, data)` already covers it — the same pattern is used in `book_scraper/spiders/patogupirkti/parsers.py`.

- [ ] **Step 4: Commit any lint/format/type fixes**

```bash
git add -u
git commit -m "chore(tytoalba): ruff + mypy clean-up"
```

(Skip if there's nothing to commit.)

---

## Task 10: Live smoke — discover then scan a handful of URLs

This task hits the real site. Keep the volume tiny.

**Pre-requisite:** Postgres + scraper containers running (`docker compose up -d postgres scraper`). The scraper container needs the new code, so:

- [ ] **Step 1: Rebuild scraper image with new spider package**

```bash
docker compose build scraper && docker compose up -d scraper
```

Verify the container has the new module:

```bash
docker exec book-scraper-scraper-1 ls /app/book_scraper/spiders/tytoalba
```

Expected: lists `__init__.py`, `parsers.py`. If not, see CLAUDE.md "BuildKit cache gotcha" and rebuild with `--no-cache`.

- [ ] **Step 2: Run discover (sitemap)**

```bash
docker compose exec scraper uv run scrapy crawl discover -a shop=tytoalba -a strategy=sitemap
```

Expected: scrapy logs `Crawled (200) <GET https://www.tytoalba.lt/products.xml?locale=LT&offset=0&limit=2000>` followed by a stat line showing ~800 discovered URLs. Run finishes in <30s.

Verify in the DB:

```bash
docker compose exec postgres psql -U postgres -d book_scraper \
  -c "SELECT COUNT(*) FROM discovered_urls du JOIN shops s ON du.shop_id = s.id WHERE s.name = 'tytoalba';"
```

Expected: count is around 800 (allow ±20 for catalogue churn).

- [ ] **Step 3: Run a capped scan (5 URLs)**

```bash
docker compose exec scraper uv run scrapy crawl scan -a shop=tytoalba -a max_urls=5
```

Expected: 5 product fetches, all 200, item-scraped count of 5 in the stats.

Verify rich metadata landed:

```bash
docker compose exec postgres psql -U postgres -d book_scraper -c "
SELECT title, author, isbn, year, pages, cover_type, format, price, in_stock
FROM shop_books sb JOIN shops s ON sb.shop_id = s.id
WHERE s.name = 'tytoalba'
ORDER BY sb.id DESC LIMIT 5;"
```

Expected: 5 rows, all with non-null `title` / `author` / `isbn` / `year` / `pages` / `cover_type` / `format` / `price`. ISBNs are 13-digit Lithuanian (978609…). At least 4/5 rows should be `in_stock = true`.

- [ ] **Step 4: Smoke the dashboard**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all routes 200. The new `tytoalba` shop should appear in the `/shops` listing.

- [ ] **Step 5: Commit a calibration note (no code change)**

If everything passes, write a one-paragraph note in the commit message capturing actual coverage numbers from step 3 (e.g. "5/5 ISBN, 5/5 year, 5/5 pages, 5/5 cover_type, 1/5 discounted") so future onboardings have a comparable benchmark.

```bash
git commit --allow-empty -m "chore(tytoalba): live smoke — discover N URLs, scan 5/5 with full metadata"
```

(Replace `N` and the per-field coverage with the real numbers.)

---

## Task 11: Update CLAUDE.md with the new shop entry

**Files:**
- Modify: `CLAUDE.md` (the "Project Overview" bullet list and the "Key Commands" block)

- [ ] **Step 1: Add a tytoalba bullet to the onboarded-shops list**

Open `CLAUDE.md`. Under the "Project Overview" section, after the existing four shop bullets, append:

```markdown
- **tytoalba.lt** — custom PHP shop, ~800 LT books. `sitemap` strategy fetches `products.xml?locale=LT&limit=2000` (single response). Product pages parsed via JSON-LD `Product` (title / sku=ISBN / brand=author / image / price / availability) + `BreadcrumbList` (categories), with a `data-attribute-name="…" data-attribute-values='[…]'` spec block filling in year / pages / cover_type / translator / original title / source language. No FlareSolverr, no GraphQL.
```

- [ ] **Step 2: Add the runbook commands to the "Key Commands" block**

In the same file's `## Key Commands` section, after the existing patogupirkti entry (or alphabetically near vaga), append:

```bash
uv run scrapy crawl discover -a shop=tytoalba -a strategy=sitemap     # Tytoalba: ~800 LT books from products.xml
uv run scrapy crawl scan -a shop=tytoalba                             # Tytoalba: scan all known product URLs
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add tytoalba.lt to project overview + runbook"
```

---

## Self-review checklist (run after the plan is implemented)

- [ ] All 8 unit tests in `tests/unit/test_tytoalba_parsers.py` pass.
- [ ] `uv run pytest tests/unit/ -v` green across every shop's parser tests.
- [ ] `uv run ruff check book_scraper/ tests/` clean.
- [ ] `uv run mypy book_scraper/` clean.
- [ ] Live smoke: discover yields ~800 URLs, scan 5 yields 5/5 with non-null `title`/`author`/`isbn`/`year`/`pages`/`cover_type`/`format`/`price`.
- [ ] Dashboard route smoke (`tests/integration/test_dashboard_routes.py`) passes; `tytoalba` visible on `/shops`.
- [ ] CLAUDE.md updated with the new shop bullet + commands.
