"""Parsers for patogupirkti.lt — Magento 1 with rich `itemprop` microdata.

The catalogue (~60 099 books) is exposed via a sitemap-of-sitemaps
(`/sitemap/sitemap.xml` → `sitemap_product.xml` + `sitemap_product-1.xml`).
Cloudflare fronts the site but only at the passive tier — plain HTTP
GETs with a desktop UA succeed, no FlareSolverr needed.

Field source on the product page (microdata + spec table):

  * `<h1>` / `<meta property="og:title">` — title.
  * `[itemprop=author]` — author. (Spec-table `Autorius:` is a fallback.)
  * `[itemprop="publisher brand"] [itemprop=name]` — publisher.
    (Spec-table `Leidėjas:` is the canonical fallback because the
    `[itemprop~=publisher]` selector matches the multi-token attribute
    `publisher brand` which is finicky with re-only parsing.)
  * `[itemprop=copyrightYear]` — year.
  * `[itemprop=numberOfPages]` — pages.
  * `[itemprop="isbn sku"]` — ISBN.
  * `[itemprop=price]` / `[itemprop=availability]` — price / stock.
  * `[itemprop=description]` — description.
  * `<table>` row `<td class="title">Label:</td><td class="value">Val</td>`
    — fallback + extras (`Formatas:`, `Žanras:`, `Vertėjas:`,
    `Iš kokios kalbos versta:`, `Pavadinimas originalo kalba:`).
  * Breadcrumbs via `[itemprop=itemListElement] [itemprop=name]` →
    `categories` (last entry is the product itself; we drop it).

Field source on a category card (`<div class="product">`):

  * Inline `var product_tracking_data_<id> = {...};` JS object —
    structured per-card data (id, name, brand=author, variant=publisher
    /year/format/pages, regular `price`, discount %, category). This is
    the Magento 1 equivalent of pegasas's GraphQL/LupaSearch fast-rescan
    paths.
  * Discounted (currently-displayed) price lives in the rendered HTML
    only — we mine the `<div class="discount-price">…</div>` /
    `<div class="full-price">…</div>` wrapper text for the pair.
  * `<a>` href — product URL.

Sitemap handling: when `parse_sitemap_urls` receives a `<sitemapindex>`
it fetches each child product sitemap synchronously via stdlib
`urllib.request`. Discover runs once a week; the extra blocking I/O is
~2–3 s for two child sitemaps and avoids the alternative of changing the
generic discover-spider contract just for one shop.
"""

from __future__ import annotations

import contextlib
import html as html_module
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, cast

from book_scraper.isbn import is_valid_isbn, normalize_isbn
from book_scraper.spiders.cover_type import format_from_cover_type
from book_scraper.spiders.parser_types import CategoryPageResult, ProductPageResult
from book_scraper.spiders.vaga.parsers import (
    classify_book_product,
    infer_shop_book_type,
)

_BASE_URL = "https://www.patogupirkti.lt"
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

# User-Agent for child-sitemap fetches — matches the desktop browser
# fingerprint used by the rest of the discovery pipeline. Cloudflare's
# passive tier on patogupirkti accepts plain GETs with this header.
_FETCH_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _unescape(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = html_module.unescape(value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _meta_content(html: str, prop: str) -> str | None:
    pat = (
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']'
        r'([^"\']*)["\']'
    )
    m = re.search(pat, html, re.I)
    return _unescape(m.group(1)) if m else None


# ─── sitemap ─────────────────────────────────────────────────────────


def _fetch_child_sitemap(url: str) -> str:
    """Fetch a child sitemap as text. Patched by tests."""
    req = urllib.request.Request(url, headers={"User-Agent": _FETCH_UA})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        body: bytes = resp.read()
    return body.decode("utf-8")


def _parse_urlset(xml_content: str) -> list[str]:
    root = ET.fromstring(xml_content)
    return [
        loc.text for loc in root.findall(f".//{_SITEMAP_NS}loc") if loc.text is not None
    ]


def parse_sitemap_urls(xml_content: str) -> list[str]:
    """Return all product URLs from a `<urlset>` or `<sitemapindex>`.

    Sitemap indexes recurse into child sitemaps whose `<loc>` contains
    `sitemap_product` — this skips the category/page/main/author/serial/
    manufacturer sub-sitemaps which don't carry product URLs we want to
    discover. Each child fetch goes through `_fetch_child_sitemap` (a
    sync stdlib HTTP call) so the discover spider doesn't need to know
    about the index format. Tests stub `_fetch_child_sitemap`.
    """
    root = ET.fromstring(xml_content)
    if root.tag.endswith("sitemapindex"):
        urls: list[str] = []
        for sm in root.findall(f"{_SITEMAP_NS}sitemap"):
            loc = sm.findtext(f"{_SITEMAP_NS}loc")
            if not loc or "sitemap_product" not in loc:
                continue
            child_xml = _fetch_child_sitemap(loc)
            urls.extend(_parse_urlset(child_xml))
        return urls
    return _parse_urlset(xml_content)


# ─── category page ───────────────────────────────────────────────────

# Per-card tracking object emitted as inline JS:
#   var product_tracking_data_62181 = {"name":"...","id":"62181",
#       "price":"15.39","category":"...","brand":"...","variant":"...",
#       "Product_Discount_in_Percent":"22.00%", ...};
# We capture the full object literal and parse it as JSON. Scope is the
# whole category response, then per-card content is keyed by id.
_TRACKING_DATA_RE = re.compile(
    r"var\s+product_tracking_data_(\d+)\s*=\s*(\{.*?\})\s*;",
    re.S,
)
# Card boundary: each `<div class="product">` block. We split the
# response on the opening tag so per-card field extraction doesn't bleed
# across siblings. Anchor the closing div by counting the matching pair
# isn't worth it — extracting from the next-card boundary is enough,
# falling back to the rest of the response for the final card.
_CARD_OPEN_RE = re.compile(r'<div\s+class="product">', re.I)
# Inside a card, the link to the product detail page.
_CARD_LINK_RE = re.compile(
    r'href="(https?://www\.patogupirkti\.lt/knyga/[^"]+\.html)"',
    re.I,
)
# Card price layout:
#
#   <div class="price-wrapper">
#     # Discounted state — both new and old price are present.
#     <div class="discounted">
#       <div class="new-price">
#         <strong class="…">12,05 <span>€</span></strong>
#       </div>
#       <strong class="… old-price">15,39 <span>€</span></strong>
#     </div>
#     # Non-discounted state — single price under price-wrapper, no
#     # `.discounted` wrapper. (Not observed on the LT-fiction snapshot,
#     # but the template falls through to a single `<strong>...€</strong>`
#     # for full-priced items.)
#   </div>
_PRICE_VALUE_RE = re.compile(r"([\d ]+[.,]\d+)\s*(?:<[^>]+>)?\s*€")
_NEW_PRICE_RE = re.compile(
    r'<div\s+class="new-price"[^>]*>(.*?)</div>',
    re.S | re.I,
)
_OLD_PRICE_RE = re.compile(
    r'<strong[^>]*\bclass="[^"]*\bold-price\b[^"]*"[^>]*>(.*?)</strong>',
    re.S | re.I,
)
# Stock status — patogupirkti emits one of:
#   <div class="instock stock-status …">Turime sandėlyje</div>
#   <div class="outstock stock-status …">Šiuo metu neturime</div>
_STOCK_RE = re.compile(r'<div\s+class="(instock|outstock)\s+stock-status', re.I)


def _normalize_price(raw: str | None) -> str | None:
    if raw is None:
        return None
    m = _PRICE_VALUE_RE.search(raw)
    if not m:
        return None
    return m.group(1).replace(" ", "").replace(",", ".") or None


def _safe_json_loads(payload: str) -> dict[str, Any] | None:
    """Accept the somewhat-loose JSON Magento 1 emits in tracking data.

    The payload is well-formed JSON in practice (string keys, escaped
    Unicode for Lithuanian characters), so a plain `json.loads` works.
    Wrap in try/except so a one-off broken card doesn't tank the whole
    category-page parse.
    """
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _split_cards(html: str) -> list[str]:
    """Return per-card HTML slices keyed by `<div class="product">`.

    The first slice is anything before the first card (no real card
    content) — we drop it.
    """
    parts = _CARD_OPEN_RE.split(html)
    return parts[1:] if len(parts) > 1 else []


def parse_category_page(html: str) -> CategoryPageResult:
    """Extract per-card products from a patogupirkti category listing.

    Each `<div class="product">` carries an inline `product_tracking_data`
    JS blob with structured fields (id/sku, name, regular price, brand=
    author, category) plus the rendered discounted price in the card
    body. We yield one product dict per card with both prices populated
    where available.

    `total` is `None` — patogupirkti's category pages don't surface a
    reliable count, so the discover spider chains pagination via `?p=N`
    until an empty page terminates the walk.
    """
    products: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for card_html in _split_cards(html):
        td_match = _TRACKING_DATA_RE.search(card_html)
        if not td_match:
            # Cards without tracking data are template scaffolding (e.g.
            # promo tiles). Skip.
            continue
        td = _safe_json_loads(td_match.group(2))
        if not td:
            continue

        link_match = _CARD_LINK_RE.search(card_html)
        if not link_match:
            continue
        url = link_match.group(1)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        magento_id = td_match.group(1)
        title = _unescape(str(td.get("name") or "")) or None
        if not title:
            continue
        author = _unescape(str(td.get("brand") or "")) or None
        price_original = (
            _normalize_price(str(td.get("price"))) if td.get("price") else None
        )

        # Discounted (currently-displayed) price from the rendered card
        # body. The `.new-price` wrapper carries the final price; the
        # `.old-price` strong is the pre-discount value. When no
        # discount is active the card lacks both, and we fall back to
        # the regular price from tracking data.
        new_block = _NEW_PRICE_RE.search(card_html)
        price = _normalize_price(new_block.group(1)) if new_block else None
        old_block = _OLD_PRICE_RE.search(card_html)
        if old_block:
            from_old = _normalize_price(old_block.group(1))
            if from_old is not None:
                price_original = from_old
        if price is None:
            price = price_original
            price_original = None  # no discount → redundant
        # Stock status from the card's status div.
        stock_m = _STOCK_RE.search(card_html)
        in_stock = stock_m.group(1).lower() == "instock" if stock_m else True

        # variant carries the publisher/year/format/pages joined: e.g.
        # "Jotema, 2026, 15x22, minkšti viršeliai, 352". Splitting it
        # is fragile (some titles have commas in the publisher), so we
        # store the raw value under properties.variant for later
        # cross-shop matching and let the scan phase fill in clean
        # year/pages/cover_type from the product page.
        properties: dict[str, Any] = {"magento_id": magento_id}
        variant = td.get("variant")
        if isinstance(variant, str) and variant.strip():
            properties["variant_raw"] = variant.strip()
        category = td.get("category")
        categories = (
            [str(category).strip()]
            if isinstance(category, str) and category.strip()
            else []
        )

        products.append(
            {
                "url": url,
                "title": title,
                "author": author,
                "price": price,
                "price_original": price_original,
                "in_stock": in_stock,
                "categories": categories,
                "properties": properties,
            }
        )

    return {"products": products, "total": None}


# ─── product page ────────────────────────────────────────────────────


# `[itemprop="<name>"]` capture — content from the element's text. The
# attribute may carry multiple space-separated tokens (e.g.
# `itemprop="isbn sku"`), so the regex matches the token surrounded by
# `"` or whitespace.
def _itemprop_text(html: str, prop: str) -> str | None:
    pat = (
        rf'itemprop=["\'][^"\']*\b{re.escape(prop)}\b[^"\']*["\'][^>]*>\s*'
        r"([^<]*)"
    )
    m = re.search(pat, html, re.I)
    return _unescape(m.group(1)) if m else None


def _itemprop_content(html: str, prop: str) -> str | None:
    """Same as `_itemprop_text` but pulls from a `content="..."` attribute.

    Used for `[itemprop=availability]` where the value is on the
    attribute (`<link itemprop="availability" href="...InStock">`) on
    some pages — but on patogupirkti it's the element text. Kept for
    completeness; preferred path stays `_itemprop_text`.
    """
    pat = (
        rf'itemprop=["\'][^"\']*\b{re.escape(prop)}\b[^"\']*["\'][^>]*'
        r'(?:content|href)=["\']([^"\']*)["\']'
    )
    m = re.search(pat, html, re.I)
    return _unescape(m.group(1)) if m else None


# Spec table rows live as <td class="title">Label:</td><td class="value">…</td>.
# Some values nest a span (e.g. `<span itemprop="isbn sku">…</span>`); we
# strip remaining tags from the value cell after match.
_SPEC_ROW_RE = re.compile(
    r'<td\s+class="title"[^>]*>\s*([^<]+?)\s*:?\s*</td>\s*'
    r'<td\s+class="value"[^>]*>(.*?)</td>',
    re.S | re.I,
)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _extract_spec_table(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_label, raw_value in _SPEC_ROW_RE.findall(html):
        label = _unescape(raw_label) or ""
        label = label.rstrip(":").strip()
        value = _unescape(_TAG_STRIP_RE.sub(" ", raw_value))
        if label and value:
            out[label] = value
    return out


# Breadcrumb chain: <li ...><span itemprop="itemListElement" ...>
# <a ...><span itemprop="name">Name</span></a><meta itemprop="position"
# content="N"></span></li>. We just collect the inner names in order.
_BREADCRUMB_RE = re.compile(
    r'itemprop=["\']itemListElement["\'][^>]*>.*?'
    r'itemprop=["\']name["\'][^>]*>\s*([^<]+?)\s*<',
    re.S | re.I,
)


def _extract_categories(html: str) -> list[str]:
    matches = [
        unescaped
        for raw in _BREADCRUMB_RE.findall(html)
        if (unescaped := _unescape(raw))
    ]
    # The last breadcrumb is the product title itself ("Pirmas → … →
    # Pelynų medus. Mano istorija") — drop it so `categories` only
    # carries the actual category chain.
    if len(matches) > 1:
        matches = matches[:-1]
    # Drop the universal root "Pirmas" (Lithuanian for "Home") — its
    # presence on every product is just noise and would muddle the
    # `_BOOK_CATEGORY_LABELS` lookup downstream.
    return [c for c in matches if c.lower() != "pirmas"]


def parse_product_page(html: str) -> ProductPageResult:
    """Parse a patogupirkti.lt product page response."""
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

    # Title — prefer h1 (clean), fall back to og:title which carries
    # a trailing " - <author> | Patogupirkti.lt" suffix we strip.
    h1_m = re.search(r"<h1[^>]*>\s*([^<]+?)\s*</h1>", html, re.I)
    if h1_m:
        title = _unescape(h1_m.group(1))
    else:
        og_title = _meta_content(html, "og:title")
        if og_title:
            og_title = re.sub(r"\s*\|\s*Patogupirkti\.lt\s*$", "", og_title)
            og_title = re.sub(r"\s+-\s+[^-]+$", "", og_title)
        title = og_title
    data["title"] = title

    # Microdata fields.
    if (author := _itemprop_text(html, "author")) is not None:
        data["author"] = author
    if (description := _itemprop_text(html, "description")) is not None:
        data["description"] = description
    elif (og_desc := _meta_content(html, "og:description")) is not None:
        data["description"] = og_desc
    if (year_raw := _itemprop_text(html, "copyrightYear")) is not None:
        with contextlib.suppress(ValueError):
            data["year"] = int(year_raw.strip())
    if (pages_raw := _itemprop_text(html, "numberOfPages")) is not None:
        with contextlib.suppress(ValueError):
            data["pages"] = int(pages_raw.strip())
    if (isbn_raw := _itemprop_text(html, "isbn")) is not None:
        normalized = normalize_isbn(isbn_raw)
        if is_valid_isbn(normalized):
            data["isbn"] = normalized
            data["sku"] = normalized
    if (price_raw := _itemprop_text(html, "price")) is not None:
        # `[itemprop=price]` carries a clean decimal already (e.g.
        # "23.84"). Normalise just in case future templates change it.
        data["price"] = _normalize_price(price_raw + " €") or price_raw.strip() or None
    availability = _itemprop_text(html, "availability") or _itemprop_content(
        html, "availability"
    )
    if availability is not None:
        data["in_stock"] = availability.strip().lower() == "instock"

    # og:image fallback for the cover.
    image_url = _meta_content(html, "og:image")
    if image_url:
        data["image_url"] = image_url

    # Spec table — fills in publisher, format/cover_type, translator,
    # and acts as a fallback for fields the microdata occasionally
    # misses on legacy product pages.
    spec = _extract_spec_table(html)
    if data["author"] is None and (s_author := spec.get("Autorius")):
        data["author"] = s_author
    publisher = spec.get("Leidėjas") or spec.get("Leidykla")
    if publisher:
        data["publisher"] = publisher
    if data["year"] is None and (year_s := spec.get("Išleidimo metai")):
        with contextlib.suppress(ValueError):
            data["year"] = int(year_s)
    if data["pages"] is None and (pages_s := spec.get("Knygos puslapių skaičius")):
        with contextlib.suppress(ValueError):
            data["pages"] = int(pages_s)
    if data["isbn"] is None and (isbn_s := spec.get("ISBN ar kodas")):
        normalized = normalize_isbn(isbn_s)
        if is_valid_isbn(normalized):
            data["isbn"] = normalized
            data["sku"] = normalized
    if (cover := spec.get("Formatas")) is not None:
        data["cover_type"] = cover
        data["format"] = format_from_cover_type(cover)
    if (translator := spec.get("Vertėjas")) is not None:
        data["translator"] = translator

    # Surface a few useful spec-table extras under properties so they
    # aren't silently lost — kept off the top-level schema since they
    # don't have first-class fields. `genre` (Žanras) gets folded into
    # `categories` so the classifier can use it as a book-signal source.
    properties: dict[str, Any] = {}
    if (orig_title := spec.get("Pavadinimas originalo kalba")) is not None:
        properties["original_title"] = orig_title
    if (source_lang := spec.get("Iš kokios kalbos versta")) is not None:
        properties["source_language"] = source_lang
    if (variant := properties.get("variant_raw")) is not None:
        properties["variant_raw"] = variant
    if properties:
        data["properties"] = properties

    # Categories from breadcrumbs + Žanras (genre) appended so the
    # classifier sees genre as a category signal too.
    categories = _extract_categories(html)
    if (genre := spec.get("Žanras")) is not None and genre not in categories:
        categories.append(genre)
    data["categories"] = categories

    # Classify book/non-book and infer type. Re-uses vaga's classifier
    # so the scoring is consistent across shops.
    classification = classify_book_product(data)
    data["is_book_product"] = classification.is_book_product
    data["book_score"] = classification.score
    data["book_score_reasons"] = classification.reasons
    data["type"] = infer_shop_book_type(data)

    return cast(ProductPageResult, data)
