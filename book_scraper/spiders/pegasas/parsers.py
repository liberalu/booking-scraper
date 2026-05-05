"""Parsers for pegasas.lt — a Magento 2 PWA (Venia) bookshop.

Two complementary discovery sources:

* Magento GraphQL (`parse_category_page`) — primary; returns full metadata
  including ISBN/year/pages via `product_page_attributes`. Verified at
  pageSize=50 with response times ~5–7s on Lithuanian fiction.
* LupaSearch (`parse_lupasearch_response`) — supplementary; returns flat
  JSON with prices, stock, `is_new`, but no ISBN/year/pages. Used for
  cheap rescans and new-arrivals detection.

Product pages themselves are JS-rendered (Venia/PWA) and contain no
parseable HTML, so `parse_product_page` is a stub that marks URLs as
non-products. All real data comes from the discover phase.
"""

from __future__ import annotations

import html as html_module
import json
import re
from typing import Any
from urllib.parse import urlencode, urlparse

from book_scraper.book_types import BOOK_LIKE_TYPES, BookType
from book_scraper.spiders.cover_type import format_from_cover_type
from book_scraper.spiders.graphql_urls import _PRODUCT_FIELDS
from book_scraper.spiders.parser_types import CategoryPageResult, ProductPageResult

_BASE_URL = "https://www.pegasas.lt"

# Trailing numeric suffix on the URL slug is the unpadded SKU. Magento
# expects the SKU as a zero-padded 18-character string in the GraphQL
# filter, so `1115331` → `000000000001115331`.
_SKU_FROM_SLUG_RE = re.compile(r"-(\d+)/?$")
_MAGENTO_SKU_WIDTH = 18

# Magento `product_page_attributes` field labels. Lithuanian text — these
# are stable Magento attribute labels, not user-editable.
_LABEL_PUBLISHER = "Leidykla"
_LABEL_TRANSLATOR = "Vertėjas"
_LABEL_YEAR = "Leidimo metai"
_LABEL_COVER = "Viršelio tipas"
_LABEL_PAGES = "Puslapių skaičius"
_LABEL_ISBN = "ISBN kodas"
_LABEL_EAN = "EAN kodas"
_LABEL_LANGUAGE = "Leidinio kalba"
_LABEL_DIMENSIONS = "Matmenys"
_LABEL_ORIGINAL_TITLE = "Pav. originalo kalba"
_LABEL_COLOR = "Spalvingumas"

# Magento label for "Lithuanian" on the language attribute. Anything else
# (Anglų / Prancūzų / Lenkų / …) is treated as non-LT and dropped during
# discovery — pegasas.lt mixes ~38k LT items with ~600k drop-shipped
# English imports under the same parent categories, so a language filter
# is the only reliable way to scope to LT-only.
_LANG_LITHUANIAN = "Lietuvių"

# Magento category IDs that flag English-language books. LupaSearch
# doesn't return the language attribute, so we use category membership
# as a proxy. 8128 = "Knygos anglų kalba" — the English book root.
_ENGLISH_CATEGORY_IDS: frozenset[int] = frozenset({8128})

# Magento category IDs that flag e-books. Magento's GraphQL exposes
# `is_book` / `is_audio_book` flags but no `is_ebook`, so we infer from
# category membership. 6122 = "Elektroninės knygos".
_EBOOK_CATEGORY_IDS: frozenset[int] = frozenset({6122})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def derive_book_type(
    is_book: object, is_audio_book: object, is_ebook: object = None
) -> BookType:
    """Map Magento/LupaSearch boolean-ish flags to our `type` field."""
    if bool(is_audio_book):
        return "audio"
    if bool(is_ebook):
        return "ebook"
    if bool(is_book):
        return "book"
    return "non_book"


def _fmt_from_book_type(book_type: BookType, cover_type: str | None) -> str | None:
    if book_type == "audio":
        return "audiobook"
    if book_type == "ebook":
        return "ebook"
    if book_type == "book":
        return format_from_cover_type(cover_type) or "book"
    return None


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = html_module.unescape(re.sub(r"\s+", " ", cleaned).strip())
    return cleaned or None


def _flatten_anotacija(raw: object) -> str | None:
    """LupaSearch returns `anotacija` as list[str]; GraphQL returns str."""
    if raw is None:
        return None
    if isinstance(raw, list):
        joined = " ".join(s for s in raw if isinstance(s, str))
    elif isinstance(raw, str):
        joined = raw
    else:
        return None
    return _strip_html(joined)


def _parse_year(value: object) -> int | None:
    if not value:
        return None
    m = re.match(r"(\d{4})", str(value))
    if not m:
        return None
    year = int(m.group(1))
    if 1500 <= year <= 2100:
        return year
    return None


def _parse_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _coerce_isbn(value: object) -> str | None:
    """Return the value only if it's a plausible ISBN-13.

    pegasas's Magento `EAN kodas` field carries non-book GTIN-13 codes
    too (sticker kits, puzzles, etc., often prefixed `40100706...`).
    Bookland (and therefore ISBN-13) only uses the 978/979 EAN
    prefixes, so we use that as the gate. Returns None for anything
    else; downstream code keeps the raw EAN in `properties.ean`.
    """
    if not isinstance(value, str):
        return None
    digits = value.replace("-", "").replace(" ", "").strip()
    # ISBN-13: exactly 13 digits, starts with 978 or 979. ISBN-10 is
    # accepted too (10 digits, last char may be 'X') — converting it
    # to a tagged ISBN form is out of scope here.
    if len(digits) == 13 and digits.isdigit() and digits[:3] in ("978", "979"):
        return digits
    if len(digits) == 10 and (digits[:9].isdigit() and digits[9] in "0123456789Xx"):
        return digits.upper()
    return None


def _attrs_to_labels(ppa_node: object) -> dict[str, str]:
    """Flatten product_page_attributes into a {label: value} dict.

    `product_page_attributes` from Magento is returned as a list of
    container objects; each container holds `primary_attributes` and
    `secondary_attributes`. We merge all label/value pairs across the
    list into a single dict.
    """
    labels: dict[str, str] = {}
    if not ppa_node:
        return labels
    containers = ppa_node if isinstance(ppa_node, list) else [ppa_node]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for bucket in ("primary_attributes", "secondary_attributes"):
            for attr in container.get(bucket) or []:
                label = attr.get("label")
                value = attr.get("value")
                if label and value is not None:
                    labels[label] = str(value)
    return labels


# ---------------------------------------------------------------------------
# Sitemap (not available for this shop)
# ---------------------------------------------------------------------------


def parse_sitemap_urls(xml_content: str) -> list[str]:
    """pegasas.lt has no XML sitemap — always returns empty."""
    return []


# ---------------------------------------------------------------------------
# Category page (Magento GraphQL JSON response)
# ---------------------------------------------------------------------------


def parse_category_page(text: str) -> CategoryPageResult:
    """Parse the Magento GraphQL products-in-category JSON response.

    Returns ``{"products": [...], "total": int | None}``. The total
    enables the discover spider's "upfront pagination" mode — on the
    first page it can enqueue all remaining pages at once, letting
    concurrent_requests_per_domain actually engage instead of being
    bottlenecked by serial page-by-page chaining.

    Non-Lithuanian products are dropped here based on the
    `Leidinio kalba` attribute (see `_LANG_LITHUANIAN`).
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"products": [], "total": None}

    products_node = data.get("data", {}).get("products", {}) or {}
    items = products_node.get("items") or []
    total_raw = products_node.get("total_count")
    try:
        total = int(total_raw) if total_raw is not None else None
    except (ValueError, TypeError):
        total = None

    products: list[dict[str, Any]] = []
    for it in items:
        if not it.get("url_key"):
            continue
        product = _graphql_item_to_product(it)
        if product is not None:
            products.append(product)
    return {"products": products, "total": total}


def _graphql_item_to_product(item: dict[str, Any]) -> dict[str, Any] | None:
    url_key = item["url_key"]
    canonical_url = f"{_BASE_URL}/{url_key}"

    # Price
    price_info = item.get("price_range", {}).get("minimum_price", {})
    final = price_info.get("final_price") or {}
    regular = price_info.get("regular_price") or {}
    price = str(final["value"]) if final.get("value") is not None else None
    price_original: str | None = None
    if regular.get("value") is not None and regular.get("value") != final.get("value"):
        price_original = str(regular["value"])

    # Author
    authors = item.get("author") or []
    author_str: str | None = None
    if authors:
        author_labels = [
            a.get("author_label", "") for a in authors if a.get("author_label")
        ]
        author_str = ", ".join(author_labels) if author_labels else None

    # Narrator
    narrators = item.get("narrator") or []
    narrator_str = ", ".join(narrators) if narrators else None

    # Categories — names only (deduped, deepest-last preserved)
    raw_cats = item.get("categories") or []
    category_names: list[str] = []
    category_ids: list[int] = []
    for cat in raw_cats:
        name = cat.get("name")
        if name and name not in category_names:
            category_names.append(name)
        cid = cat.get("id")
        if isinstance(cid, int) and cid not in category_ids:
            category_ids.append(cid)

    # Description
    description = _flatten_anotacija(item.get("anotacija"))

    # Type — Magento exposes is_book/is_audio_book but no is_ebook flag,
    # so infer e-book status from category membership (6122).
    is_ebook = any(cid in _EBOOK_CATEGORY_IDS for cid in category_ids)
    book_type = derive_book_type(
        item.get("is_book"),
        item.get("is_audio_book"),
        is_ebook=is_ebook,
    )

    # Stock
    in_stock = item.get("stock_status") == "IN_STOCK"

    # ----- Rich metadata -----
    # Prefer product_page_attributes (always populated when included in
    # the query); fall back to structured_data JSON-LD if attributes are
    # missing for any reason.
    isbn: str | None = None
    ean: str | None = None
    publisher: str | None = None
    pages: int | None = None
    year: int | None = None
    cover_type: str | None = None
    translator: str | None = None
    language: str | None = None
    dimensions: str | None = None
    original_title: str | None = None
    color: str | None = None

    def _clean(value: object) -> str | None:
        """Treat empty / whitespace-only / dash strings as missing."""
        if not isinstance(value, str):
            return None
        v = value.strip()
        if not v or v in {"-", "—"}:
            return None
        return v

    labels = _attrs_to_labels(item.get("product_page_attributes"))
    if labels:
        # Language gate: drop non-Lithuanian products before doing any
        # more work. We only filter when the attribute is *populated*
        # and clearly non-LT — items with no language attribute fall
        # through (~1% of the catalogue) so we don't lose anything
        # legitimate just because Magento didn't tag it.
        lang_raw = labels.get(_LABEL_LANGUAGE)
        if lang_raw and lang_raw.strip() and lang_raw.strip() != _LANG_LITHUANIAN:
            return None

        # ISBN vs EAN: pegasas's `EAN kodas` field carries non-book
        # GTINs too (e.g. `4010070...` = German non-book product codes
        # for sticker kits, puzzles). Only accept 978/979-prefixed
        # 13-digit codes as ISBN (the Bookland prefixes); keep the raw
        # EAN separately in `properties.ean` for completeness.
        raw_isbn = _clean(labels.get(_LABEL_ISBN))
        raw_ean = _clean(labels.get(_LABEL_EAN))
        isbn = _coerce_isbn(raw_isbn) or _coerce_isbn(raw_ean)
        # Keep EAN if it's a real GTIN-13 and differs from the ISBN.
        ean = raw_ean if raw_ean and raw_ean != isbn else None

        publisher = _clean(labels.get(_LABEL_PUBLISHER))
        pages = _parse_int(labels.get(_LABEL_PAGES))
        year = _parse_year(labels.get(_LABEL_YEAR))
        cover_type = _clean(labels.get(_LABEL_COVER))
        translator = _clean(labels.get(_LABEL_TRANSLATOR))
        language = _clean(labels.get(_LABEL_LANGUAGE))
        dimensions = _clean(labels.get(_LABEL_DIMENSIONS))
        original_title = _clean(labels.get(_LABEL_ORIGINAL_TITLE))
        color = _clean(labels.get(_LABEL_COLOR))

    # Fallback via structured_data JSON-LD. The ISBN field there is
    # populated even on non-book products (Magento puts the EAN-13 in
    # the Schema.org `isbn` slot), so we run it through `_coerce_isbn`
    # too — without that, sticker-kit GTINs like `4770833862422` slip
    # past the labels-level filter via this fallback path and get
    # stored as ISBN, then fail downstream `invalid_isbn` validation.
    if (isbn is None or publisher is None or pages is None or year is None) and (
        sd_raw := item.get("structured_data")
    ):
        try:
            sd = json.loads(sd_raw)
            main = sd.get("mainEntity", {})
            if isbn is None:
                isbn = _coerce_isbn(main.get("isbn"))
            if publisher is None:
                pub = main.get("publisher", {})
                if isinstance(pub, dict):
                    publisher = pub.get("name") or None
                elif isinstance(pub, str):
                    publisher = pub or None
            if pages is None:
                pages = _parse_int(main.get("numberOfPages"))
            if year is None:
                year = _parse_year(main.get("datePublished"))
        except (json.JSONDecodeError, AttributeError):
            pass

    # Properties dict for format-specific extras
    properties: dict[str, object] = {}
    if pages is not None:
        properties["pages"] = pages
    if narrator_str:
        properties["narrator"] = narrator_str
    if cover_type:
        properties["cover_type"] = cover_type
    if translator:
        properties["translator"] = translator
    if language:
        properties["language"] = language
    if dimensions:
        properties["dimensions"] = dimensions
    if original_title:
        properties["original_title"] = original_title
    if color:
        properties["color"] = color
    if ean:
        properties["ean"] = ean

    fmt = _fmt_from_book_type(book_type, cover_type)

    return {
        "url": canonical_url,
        "title": item.get("name"),
        "author": author_str,
        "sku": item.get("sku"),
        "isbn": isbn,
        "publisher": publisher,
        "year": year,
        "format": fmt,
        "description": description,
        "image_url": (item.get("image") or {}).get("url"),
        "price": price,
        "price_original": price_original,
        "in_stock": in_stock,
        "type": book_type,
        "categories": category_names,
        "properties": properties or None,
    }


# ---------------------------------------------------------------------------
# LupaSearch response (JSON, POST endpoint)
# ---------------------------------------------------------------------------


def parse_lupasearch_response(text: str) -> CategoryPageResult:
    """Parse the LupaSearch query API response.

    Returns ``{"products": [...], "total": int}``. The product dict shape
    matches `parse_category_page` so the discover spider can route both
    sources through the same yielding logic. ISBN/year/pages are always
    None (LupaSearch does not expose them); enrichment happens via
    GraphQL or scan-phase fetches.

    English-language items are dropped here using the `category_ids`
    proxy — LupaSearch doesn't return the language attribute directly,
    so we exclude any product whose category list intersects
    `_ENGLISH_CATEGORY_IDS` (currently just 8128, the English book root).
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"products": [], "total": 0}

    raw_items = data.get("items") or []
    total = int(data.get("total") or 0)
    products: list[dict[str, Any]] = []
    for item in raw_items:
        product = _lupasearch_item_to_product(item)
        if product is not None:
            products.append(product)
    return {"products": products, "total": total}


def _lupasearch_item_to_product(item: dict[str, Any]) -> dict[str, Any] | None:
    # Language gate via category membership. LupaSearch returns
    # `category_ids` as ints; treat the list as a set for the
    # intersection so order doesn't matter.
    cat_ids_raw = item.get("category_ids") or []
    if any(int(c) in _ENGLISH_CATEGORY_IDS for c in cat_ids_raw if str(c).isdigit()):
        return None

    url = item.get("url") or ""
    # Preserve the URL as-is; the spider will normalize.

    # Price — LupaSearch returns `price` as a stringified decimal and
    # `regular_price` as a float. Normalize both to strings, only emit
    # `price_original` when it differs from the sale price.
    price_raw = item.get("price")
    price = str(price_raw) if price_raw is not None else None
    regular_raw = item.get("regular_price")
    price_original: str | None = None
    if regular_raw is not None and price is not None:
        try:
            if float(regular_raw) != float(price):
                price_original = str(regular_raw)
        except (ValueError, TypeError):
            pass

    # Author
    authors = item.get("autorius") or []
    author_str = ", ".join(a for a in authors if a) if authors else None

    # Publisher (string field; some items have trailing whitespace)
    publisher_raw = item.get("leidykla")
    publisher: str | None = None
    if isinstance(publisher_raw, str):
        cleaned = publisher_raw.strip()
        if cleaned and cleaned not in {"-", "—"}:
            publisher = cleaned

    # Cover type — list of strings, take first
    cover_list = item.get("virselio_tipas") or []
    cover_type = cover_list[0] if cover_list else None

    # Type — LupaSearch exposes ebook flag as well
    book_type = derive_book_type(
        item.get("is_book"), item.get("is_audio_book"), item.get("is_ebook")
    )
    fmt = _fmt_from_book_type(book_type, cover_type)

    # Categories — numeric ids; stringify for downstream consistency
    cat_ids = item.get("category_ids") or []
    categories = [str(cid) for cid in cat_ids]

    # Description
    description = _flatten_anotacija(item.get("anotacija"))

    # Stock
    in_stock = bool(item.get("in_stock") == 1 or item.get("in_stock") is True)

    # Properties — extra LupaSearch-only signals worth retaining
    properties: dict[str, object] = {}
    if cover_type:
        properties["cover_type"] = cover_type
    is_new = item.get("is_new")
    if is_new is not None:
        properties["is_new"] = bool(is_new)
    if item.get("in_store_only") is not None:
        properties["in_store_only"] = bool(item.get("in_store_only"))
    discount_rate = item.get("discount_rate")
    if isinstance(discount_rate, (int, float)):
        properties["discount_rate"] = float(discount_rate)

    return {
        "url": url,
        "title": item.get("name"),
        "author": author_str,
        "sku": item.get("sku"),
        "isbn": None,  # not in LupaSearch payload
        "publisher": publisher,
        "year": None,  # not in LupaSearch payload
        "format": fmt,
        "description": description,
        "image_url": item.get("image"),
        "price": price,
        "price_original": price_original,
        "in_stock": in_stock,
        "type": book_type,
        "categories": categories,
        "properties": properties or None,
    }


# ---------------------------------------------------------------------------
# Product page (per-SKU GraphQL JSON via rewrite_scan_url)
# ---------------------------------------------------------------------------


def _empty_product_page_result(reason_key: str) -> ProductPageResult:
    """Default non-product shape used for both PWA-shell HTML responses
    and GraphQL responses with empty `items[]`."""
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
        "book_score_reasons": [{"key": reason_key, "points": 0}],
        "type": "non_book",
        "planned_availability_date": None,
        "rating": None,
        "review_count": None,
    }


def parse_product_page(text: str) -> ProductPageResult:
    """Parse a per-SKU Magento GraphQL JSON response.

    The scan spider hits this with the body of the GraphQL endpoint after
    `rewrite_scan_url` swapped the product page URL for a single-SKU
    GraphQL query. Falls back to a non-product result when the body
    isn't JSON (e.g. the legacy PWA-shell HTML, returned for ad-hoc
    direct fetches that bypassed `rewrite_scan_url`).
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _empty_product_page_result("pwa_shell_no_data")

    items = (data.get("data", {}).get("products", {}) or {}).get("items") or []
    if not items:
        return _empty_product_page_result("graphql_no_match")
    product = _graphql_item_to_product(items[0])
    if product is None:
        # Language gate fired (non-LT) — record as non-product so the
        # row is closed cleanly without a noisy validation error.
        return _empty_product_page_result("graphql_non_lt_filtered")

    properties = product.get("properties") or {}
    return {
        "title": product.get("title"),
        "description": product.get("description"),
        "price": product.get("price"),
        "price_original": product.get("price_original"),
        "in_stock": product.get("in_stock"),
        "isbn": product.get("isbn"),
        "sku": product.get("sku"),
        "publisher": product.get("publisher"),
        "image_url": product.get("image_url"),
        "categories": product.get("categories", []),
        "year": product.get("year"),
        "pages": properties.get("pages"),
        "author": product.get("author"),
        "cover_type": properties.get("cover_type"),
        "format": product.get("format"),
        "duration": properties.get("duration"),
        "narrator": properties.get("narrator"),
        "translator": properties.get("translator"),
        "schema_types": [],
        "is_book_product": product.get("type") in BOOK_LIKE_TYPES,
        "book_score": 100,
        "book_score_reasons": [{"key": "graphql_sku_match", "points": 100}],
        "type": product.get("type") or "non_book",
        "planned_availability_date": None,
        "rating": None,
        "review_count": None,
    }


def rewrite_scan_url(url: str) -> dict[str, Any] | None:
    """Rewrite a product URL to a single-SKU GraphQL request.

    The PWA serves React-shell HTML for product pages — no parseable data.
    The Magento GraphQL endpoint, however, returns full product metadata
    in 200–500 ms when filtered to a single SKU. The trailing numeric
    suffix on the slug is the unpadded SKU; we pad to 18 chars per
    Magento's storage format.

    Returns ``{"url": str, "headers": {...}}`` to swap into the request,
    or ``None`` when the URL has no extractable SKU (the spider then
    leaves the request untouched and the response will land in the
    PWA-shell fallback path).
    """
    parsed = urlparse(url)
    match = _SKU_FROM_SLUG_RE.search(parsed.path.rstrip("/"))
    if not match:
        return None
    sku_padded = match.group(1).rjust(_MAGENTO_SKU_WIDTH, "0")
    query = (
        "{products("
        f'filter:{{sku:{{eq:"{sku_padded}"}}}},'
        "pageSize:1,currentPage:1"
        f"){{items{{{_PRODUCT_FIELDS}}}}}}}"
    )
    base = f"{parsed.scheme}://{parsed.netloc}"
    rewritten = base + "/graphql?" + urlencode([("query", query)])
    return {
        "url": rewritten,
        "headers": {"Accept": "application/json"},
    }
