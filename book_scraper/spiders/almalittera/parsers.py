"""Parsers for almalittera.lt — a Shopify store with a Lithuanian-only catalogue.

Discovery via Shopify's public `/products.json` endpoint (paginated at
`limit=250`). Returns title, vendor (author), price, sku, in_stock per
product — but not ISBN/year/pages/cover-type. Those live in HTML
metafields on the product page (`<div class="product-full-width__
description-specs">`) and are extracted by the scan phase.

No anti-bot: behind Cloudflare but no challenge fires for plain
`Mozilla/5.0`. Catalogue is ~4.4k products and walks in a few minutes
under concurrency=4.

Non-book detection: the catalogue mixes books with school notebooks
(`Sąsiuvinis ...`), planners, and similar stationery. The publisher
fills the "vendor" field with the literal placeholder
`"Nėra Autoriaus"` ("No Author") on these — we map that to None at
parse time so the shared classifier from the vaga module flips them to
`is_book_product=False` (no valid book ISBN, no real author, no book
category). Real books carry a 978/979 ISBN-13 plus a proper vendor.
"""

from __future__ import annotations

import contextlib
import html as html_module
import json
import re
from typing import Any, cast

from book_scraper.spiders.cover_type import format_from_cover_type
from book_scraper.spiders.parser_types import CategoryPageResult, ProductPageResult
from book_scraper.spiders.vaga.parsers import classify_book_product

_BASE_URL = "https://almalittera.lt"

# Shopify's vendor field for products without an author — notebooks,
# stationery, planners. Treated as no-author so the classifier can drop
# them.
_PLACEHOLDER_VENDORS = frozenset({"nėra autoriaus", "nera autoriaus"})


def _unescape(value: object) -> object:
    """html.unescape on str values; pass through None and non-strings."""
    return html_module.unescape(value) if isinstance(value, str) else value


def _vendor_to_author(vendor: object) -> str | None:
    if not isinstance(vendor, str):
        return None
    cleaned = vendor.strip()
    if not cleaned:
        return None
    if cleaned.lower() in _PLACEHOLDER_VENDORS:
        return None
    return cleaned


def _book_type_from_shopify(product_type: object, tags: object) -> str:
    """Map Shopify `product_type` + `tags` to our `type` field.

    Almalittera tags e-books with `product_type="EPUB"` and an `EPUB`
    tag; audiobooks (rare on this catalogue) use `MP3`. Everything else
    starts as `book` — the scan phase's classifier downgrades non-book
    items (notebooks, stationery) to `non_book`.
    """
    pt = (product_type or "").strip().upper() if isinstance(product_type, str) else ""
    tag_set = _normalize_tags(tags)
    if pt == "EPUB" or "EPUB" in tag_set:
        return "ebook"
    if pt in {"MP3", "AUDIOBOOK"} or "MP3" in tag_set:
        return "audio"
    return "book"


def _normalize_tags(tags: object) -> set[str]:
    """Shopify tags arrive as list[str] from products.json or as a comma
    string from the per-product `.json` endpoint — normalise to upper
    set for membership checks."""
    if isinstance(tags, list):
        items = [t for t in tags if isinstance(t, str)]
    elif isinstance(tags, str):
        items = [t.strip() for t in tags.split(",")]
    else:
        return set()
    return {t.upper() for t in items if t}


def _parse_year_from_label(value: str) -> int | None:
    """`Leidimo metai` is rendered as `YYYY MM DD` (e.g. `2026 05 05`).

    Take the leading 4 digits — the day-precision is editorial metadata
    and not useful downstream; we only store the year.
    """
    match = re.match(r"\s*(\d{4})", value)
    return int(match.group(1)) if match else None


def parse_category_page(text: str) -> CategoryPageResult:
    """Parse a Shopify `/products.json` page into the discover contract.

    Returns ``{"products": [...], "total": None}``. The endpoint doesn't
    expose a total count, so the spider falls back to per-page chained
    pagination — same behaviour as vaga's HTML strategy.

    Each product dict carries url, title, author, price, price_original
    (when on sale), in_stock, sku, image_url, type, plus a
    `properties` sub-dict with the Shopify tags so downstream consumers
    can introspect promo flags / collection membership without a second
    HTTP call.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"products": [], "total": None}

    raw_products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(raw_products, list):
        return {"products": [], "total": None}

    products: list[dict[str, Any]] = []
    for item in raw_products:
        if not isinstance(item, dict):
            continue
        handle = item.get("handle")
        if not isinstance(handle, str) or not handle:
            continue
        url = f"{_BASE_URL}/products/{handle}"

        variants = (
            item.get("variants") if isinstance(item.get("variants"), list) else []
        )
        first_variant = variants[0] if variants else {}
        if not isinstance(first_variant, dict):
            first_variant = {}

        price_raw = first_variant.get("price")
        price = str(price_raw) if price_raw not in (None, "") else None

        compare = first_variant.get("compare_at_price")
        price_original = str(compare) if compare not in (None, "") else None

        sku_raw = first_variant.get("sku")
        sku = str(sku_raw).strip() if sku_raw not in (None, "") else None

        in_stock = bool(first_variant.get("available"))

        images = item.get("images") if isinstance(item.get("images"), list) else []
        image_url: str | None = None
        if images:
            first_image = images[0]
            if isinstance(first_image, dict):
                src = first_image.get("src")
                if isinstance(src, str):
                    image_url = src

        title = _unescape(item.get("title"))
        author = _vendor_to_author(item.get("vendor"))
        book_type = _book_type_from_shopify(item.get("product_type"), item.get("tags"))

        tags = item.get("tags")
        properties: dict[str, object] = {}
        if isinstance(tags, list) and tags:
            properties["shopify_tags"] = [t for t in tags if isinstance(t, str)]
        elif isinstance(tags, str) and tags:
            properties["shopify_tags"] = [
                t.strip() for t in tags.split(",") if t.strip()
            ]

        products.append(
            {
                "url": url,
                "title": title,
                "author": author,
                "price": price,
                "price_original": price_original,
                "in_stock": in_stock,
                "sku": sku,
                "image_url": image_url,
                "type": book_type,
                "categories": [],
                "properties": properties or None,
            }
        )

    return {"products": products, "total": None}


def parse_product_page(html: str) -> ProductPageResult:
    """Parse a Shopify product page on almalittera.lt.

    Two structured sources, both server-rendered:

    * **JSON-LD `Product` block** — title, description, image, price,
      availability, brand (author), `gtin13` (= ISBN-13). Some pages
      emit `offers` as a list (per-variant); we read the first.
    * **HTML spec block** — `<span class="...specs-name">Label:</span>
      Value</p>` pairs carrying ISBN/EAN, SKU, page count, cover type,
      original language, year, translator, etc.

    A `BreadcrumbList` JSON-LD also exists but on this theme it only
    carries `Home → <product name>`, so we drop it (the leaf is the
    product itself, not a real category).
    """
    data: dict[str, object] = {
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
    schema_types: set[str] = set()

    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        html,
        re.DOTALL,
    )
    for block in blocks:
        cleaned = re.sub(r"[\x00-\x1f]+", " ", block.strip())
        try:
            ld = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        if not isinstance(ld, dict):
            continue

        ld_type = ld.get("@type", "")
        if isinstance(ld_type, list):
            ld_types = [str(t) for t in ld_type]
        elif ld_type:
            ld_types = [str(ld_type)]
        else:
            ld_types = []
        schema_types.update(ld_types)

        if "Product" in ld_types or "Book" in ld_types:
            if not data["title"]:
                data["title"] = _unescape(ld.get("name"))
            if not data["description"]:
                data["description"] = _unescape(ld.get("description"))
            brand = ld.get("brand")
            if isinstance(brand, dict) and not data["author"]:
                data["author"] = _vendor_to_author(brand.get("name"))
            img = ld.get("image")
            if not data["image_url"]:
                if isinstance(img, str):
                    data["image_url"] = img
                elif isinstance(img, list) and img and isinstance(img[0], str):
                    data["image_url"] = img[0]

            offers_raw = ld.get("offers")
            if isinstance(offers_raw, list) and offers_raw:
                offer = offers_raw[0]
            elif isinstance(offers_raw, dict):
                offer = offers_raw
            else:
                offer = {}
            if isinstance(offer, dict):
                if not data["price"]:
                    price_raw = offer.get("price")
                    if price_raw not in (None, ""):
                        data["price"] = str(price_raw)
                if data["in_stock"] is None:
                    avail = offer.get("availability")
                    if isinstance(avail, str):
                        data["in_stock"] = "InStock" in avail
                if not data["sku"]:
                    sku_val = offer.get("sku")
                    if isinstance(sku_val, str) and sku_val:
                        data["sku"] = sku_val

            if not data["isbn"]:
                gtin = ld.get("gtin13") or ld.get("isbn")
                if isinstance(gtin, str) and gtin:
                    data["isbn"] = gtin

    spec_block = re.search(
        r'<div[^>]*class="[^"]*product-full-width__description-specs[^"]*"[^>]*>(.*?)</div>',
        html,
        re.DOTALL,
    )
    spec_html = spec_block.group(1) if spec_block else ""
    pairs = re.findall(
        r'<span class="product-full-width__description-specs-name">\s*'
        r"([^<]+?)\s*</span>\s*([^<]*?)</p>",
        spec_html,
        re.DOTALL,
    )
    specs = {
        label.rstrip(":").strip(): html_module.unescape(value).strip()
        for label, value in pairs
    }

    if "ISBN kodas" in specs and not data["isbn"]:
        data["isbn"] = specs["ISBN kodas"] or None
    if "EAN kodas" in specs and not data["isbn"]:
        data["isbn"] = specs["EAN kodas"] or None
    if "SKU" in specs and not data["sku"]:
        data["sku"] = specs["SKU"] or None
    if "Puslapių skaičius" in specs:
        with contextlib.suppress(ValueError):
            data["pages"] = int(specs["Puslapių skaičius"])
    if "Viršelio tipas" in specs:
        data["cover_type"] = specs["Viršelio tipas"] or None
    if "Vertėjas" in specs:
        data["translator"] = specs["Vertėjas"] or None
    if "Leidimo metai" in specs:
        data["year"] = _parse_year_from_label(specs["Leidimo metai"])

    title_value = data.get("title")
    title_lower = title_value.lower() if isinstance(title_value, str) else ""
    is_ebook = "e.knyga" in title_lower or "epub" in title_lower

    if is_ebook:
        data["format"] = "ebook"
    elif data.get("cover_type"):
        cover = data["cover_type"]
        if isinstance(cover, str):
            data["format"] = format_from_cover_type(cover)
    elif data.get("pages") is not None:
        data["format"] = "book"

    data["schema_types"] = sorted(schema_types)

    classification = classify_book_product(data)
    data["is_book_product"] = classification.is_book_product
    data["book_score"] = classification.score
    data["book_score_reasons"] = classification.reasons

    if is_ebook and classification.is_book_product:
        data["type"] = "ebook"
    elif classification.is_book_product:
        data["type"] = "book"
    else:
        data["type"] = "non_book"

    return cast(ProductPageResult, data)
