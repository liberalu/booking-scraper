import contextlib
import html as html_module
import json
import re
import xml.etree.ElementTree as ET


def _unescape(value: object) -> object:
    """html.unescape on str values; pass through None and non-strings."""
    return html_module.unescape(value) if isinstance(value, str) else value


_ALLOWED_DESCRIPTION_TAGS = frozenset(
    {"p", "br", "strong", "em", "b", "i", "u", "ul", "ol", "li"}
)


def _sanitize_description_html(markup: str) -> str:
    """Strip all tags except a small allowlist used by vaga descriptions.

    Attributes are dropped; `<script>` / `<style>` blocks are removed
    with their contents. Output is safe to feed into a Jinja `|safe`
    filter for rendering.
    """
    # Drop entire script/style blocks (content + tags).
    markup = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Drop HTML comments.
    markup = re.sub(r"<!--.*?-->", "", markup, flags=re.DOTALL)

    def _filter(match: re.Match[str]) -> str:
        slash, tag = match.group(1), match.group(2).lower()
        if tag in _ALLOWED_DESCRIPTION_TAGS:
            return f"<{slash}{tag}>"
        return ""

    markup = re.sub(
        r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>",
        _filter,
        markup,
    )
    return markup.strip()


def parse_sitemap_urls(xml_content: str) -> list[str]:
    """Extract all URLs from a vaga.lt sitemap XML string."""
    root = ET.fromstring(xml_content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [loc.text for loc in root.findall(".//s:loc", ns) if loc.text is not None]


def parse_category_page(html: str) -> list[dict[str, str | None]]:
    """Parse product cards from a vaga.lt category listing page.

    Returns list of dicts with keys: url, title, price, price_original, image_url.
    Prices are in Lithuanian format: '16,32€' -> '16.32'.
    URLs have query parameters stripped (e.g. '?limit=100' removed).
    """
    products = []
    segments = re.split(r'class="product-item-container product-\d+"', html)[1:]
    for seg in segments:
        name_match = re.search(r'<p class="name"><a href="([^"]+)">([^<]+)', seg)
        if not name_match:
            continue
        url = name_match.group(1).split("?")[0].strip()
        title = html_module.unescape(name_match.group(2).strip())

        author = None
        author_match = re.search(
            r'<p class="Autorius">\s*([^<]+?)\s*</p>',
            seg,
        )
        if author_match:
            author = html_module.unescape(author_match.group(1).strip())

        price = None
        price_match = re.search(r'class="price coupon">([0-9,]+)€', seg)
        if price_match:
            price = price_match.group(1).replace(",", ".")

        price_original = None
        original_match = re.search(r'class="price-old">([0-9,]+)€', seg)
        if original_match:
            price_original = original_match.group(1).replace(",", ".")

        image_url = None
        img_match = re.search(r'data-src="([^"]+)"', seg)
        if img_match:
            image_url = img_match.group(1)

        products.append(
            {
                "url": url,
                "title": title,
                "author": author,
                "price": price,
                "price_original": price_original,
                "image_url": image_url,
            }
        )
    return products


def parse_product_page(html: str) -> dict[str, object]:
    """Parse a vaga.lt product page using JSON-LD and HTML property spans.

    Returns dict with keys: title, description, price, price_original,
    in_stock, isbn, sku, publisher, image_url, categories,
    year, pages, cover_type.
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
    }

    # Parse author: <div class="brand"><span>Autorius </span><a>Name</a></div>
    author_match = re.search(
        r'class="brand">\s*<span>Autorius\s*</span>\s*<a[^>]*>([^<]+)</a>',
        html,
    )
    if author_match:
        data["author"] = html_module.unescape(author_match.group(1).strip())

    # Parse JSON-LD blocks
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

        # Product/Book data
        ld_type = ld.get("@type", "")
        if isinstance(ld_type, list):
            is_product = "Product" in ld_type or "Book" in ld_type
        else:
            is_product = ld_type in ("Product", "Book")

        if is_product:
            data["title"] = _unescape(ld.get("name"))
            data["description"] = _unescape(ld.get("description"))
            data["sku"] = ld.get("sku")
            offers = ld.get("offers", {})
            data["price"] = offers.get("price")
            data["in_stock"] = "InStock" in offers.get("availability", "")
            related = ld.get("isRelatedTo", {})
            data["isbn"] = related.get("isbn")
            brand = ld.get("brand", {})
            data["publisher"] = _unescape(brand.get("name"))
            images = ld.get("image", [])
            if images:
                data["image_url"] = images[0] if isinstance(images, list) else images

        # Breadcrumb -> categories
        if ld.get("@type") == "BreadcrumbList":
            items = ld.get("itemListElement", [])
            data["categories"] = [
                html_module.unescape(item.get("name", ""))
                for item in items
                if item.get("name")
            ]

    # Some products show a "price-new special" promotional price that's
    # DIFFERENT from JSON-LD offers.price. The user-facing page shows the
    # "price-new special" value and no secondary/original price, so treat
    # it as authoritative and DROP the JSON-LD price rather than promote
    # it — vaga's JSON-LD carries a non-public wholesale/club price in
    # that layout and it would mislead users as a strikethrough "was"
    # price.
    # "price-new special" and "price-new coupon" both carry the actual
    # displayed price on product pages; JSON-LD on these layouts is a
    # non-public value and should be ignored.
    special_match = re.search(
        r'class="price-new (?:special|coupon)"[^>]*>\s*([\d,]+)€',
        html,
    )
    if special_match:
        data["price"] = special_match.group(1).replace(",", ".")

    # Extract original/bookstore price from HTML (not in JSON-LD)
    original_match = re.search(r'class="price-knygyne">([0-9,]+)€', html)
    if original_match:
        data["price_original"] = original_match.group(1).replace(",", ".")

    # Prefer the rich-text description block over the flat JSON-LD value.
    # vaga.lt keeps paragraph markup here in <p>..</p> form.
    desc_block = re.search(
        r'<div[^>]*id=["\']collapse-description["\'][^>]*>(.*?)</div>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if desc_block:
        rich = _sanitize_description_html(desc_block.group(1))
        if rich:
            data["description"] = html_module.unescape(rich)

    # Parse HTML property spans (note: class has typo "propery")
    props = re.findall(
        r'<span class="propery-title">(.*?)</span>'
        r'\s*<span class="propery-des">(.*?)</span>',
        html,
    )
    prop_map = {k.strip(): html_module.unescape(v.strip()) for k, v in props}
    if "ISBN" in prop_map:
        data["isbn"] = data["isbn"] or prop_map["ISBN"]
    if "Metai" in prop_map:
        with contextlib.suppress(ValueError):
            data["year"] = int(prop_map["Metai"])
    if "Puslapiai" in prop_map:
        with contextlib.suppress(ValueError):
            data["pages"] = int(prop_map["Puslapiai"])
    if "Viršelis" in prop_map:
        data["cover_type"] = prop_map["Viršelis"]
    if "Leidykla" in prop_map:
        data["publisher"] = data["publisher"] or prop_map["Leidykla"]
    if "Trukmė" in prop_map:
        data["duration"] = prop_map["Trukmė"]
    if "Įgarsino" in prop_map:
        data["narrator"] = prop_map["Įgarsino"]
    if "Vertėjas" in prop_map:
        data["translator"] = prop_map["Vertėjas"]

    # Auto-detect format from available properties
    if "Trukmė" in prop_map:
        data["format"] = "audiobook"
    elif "Viršelis" in prop_map:
        cover = prop_map["Viršelis"].lower()
        if "kiet" in cover:
            data["format"] = "hardcover"
        elif "minkšt" in cover:
            data["format"] = "paperback"
        else:
            data["format"] = cover
    elif "Puslapiai" in prop_map:
        data["format"] = "book"

    return data
