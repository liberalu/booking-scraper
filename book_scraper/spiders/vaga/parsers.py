import contextlib
import html as html_module
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from bs4 import BeautifulSoup

from book_scraper.book_types import BookType
from book_scraper.isbn import is_valid_isbn
from book_scraper.spiders.cover_type import format_from_cover_type


@dataclass(frozen=True)
class BookClassification:
    score: int
    is_book_product: bool
    reasons: list[dict[str, object]]
    has_primary_book_signal: bool

_BOOK_CATEGORY_LABELS = (
    "negrožinė literatūra",
    "grožinė literatūra",
    "knygos vaikams ir jaunimui",
    "knygos anglų kalba",
    "audioknygos",
)
_NON_BOOK_CATEGORY_KEYWORDS = ("žaisl", "žaidim", "dėlion", "puzzle", "lego")
_NON_BOOK_CATEGORY_LABELS = (
    "mokyklinės ir raštinės prekės",
    "dovanų idėjos",
    "žaislai ir žaidimai",
    "viskas namams",
)
_AUDIO_FORMATS = ("audiobook", "audio", "audiobookas")
_EBOOK_FORMATS = (
    "ebook",
    "e-book",
    "eknyga",
    "e-knyga",
    "elektroninė knyga",
)
_BOOK_FORMATS = ("book", "hardcover", "paperback")
_GAME_OR_TOY_PATTERNS = (
    r"^\s*stalo\s+žaidim",
    r"^\s*kort[ųu]\s+žaidim",
    r"^\s*edukacinis\s+žaidim",
    r"^\s*dėlion",
    r"\bpuzzle\b",
    r"\blego\b",
    r"^\s*žaislas\b",
)


def _unescape(value: object) -> object:
    """html.unescape on str values; pass through None and non-strings."""
    return html_module.unescape(value) if isinstance(value, str) else value


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_module.unescape(value).casefold()).strip()


def _categories_contain_keywords(categories: object, keywords: tuple[str, ...]) -> bool:
    if not isinstance(categories, list):
        return False
    normalized = [_normalize_text(c) for c in categories if isinstance(c, str)]
    return any(
        any(keyword in category for keyword in keywords) for category in normalized
    )


def _categories_contain_labels(categories: object, labels: tuple[str, ...]) -> bool:
    if not isinstance(categories, list):
        return False
    normalized = {_normalize_text(c) for c in categories if isinstance(c, str)}
    return any(label in normalized for label in labels)


def title_looks_like_game_or_toy(title: str | None) -> bool:
    if not title:
        return False
    normalized = _normalize_text(title)
    return any(re.search(pattern, normalized) for pattern in _GAME_OR_TOY_PATTERNS)


def classify_book_product(data: dict[str, object]) -> BookClassification:
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        return BookClassification(
            score=0,
            is_book_product=False,
            reasons=[{"key": "no_title", "points": 0}],
            has_primary_book_signal=False,
        )

    categories = data.get("categories")
    has_book_category = _categories_contain_labels(categories, _BOOK_CATEGORY_LABELS)
    has_non_book_category = _categories_contain_keywords(
        categories, _NON_BOOK_CATEGORY_KEYWORDS
    )
    has_non_book_category = has_non_book_category or _categories_contain_labels(
        categories, _NON_BOOK_CATEGORY_LABELS
    )
    isbn = data.get("isbn") if isinstance(data.get("isbn"), str) else None
    valid_isbn = is_valid_isbn(isbn)
    author = data.get("author")
    has_author = isinstance(author, str) and bool(author.strip())
    reasons: list[dict[str, object]] = []
    has_book_metadata = any(
        data.get(field) not in (None, "")
        for field in (
            "pages",
            "cover_type",
            "year",
            "translator",
            "narrator",
            "duration",
            "format",
        )
    )
    title_is_non_book = title_looks_like_game_or_toy(title)

    signals: tuple[tuple[str, bool, int], ...] = (
        ("book_categories", has_book_category, 3),
        ("valid_isbn", valid_isbn, 3),
        ("author_present", has_author, 2),
        ("book_metadata", has_book_metadata, 2),
        ("game_toy_title", title_is_non_book, -3),
        ("non_book_categories", has_non_book_category, -4),
    )
    score = 0
    for key, fired, points in signals:
        awarded = points if fired else 0
        score += awarded
        reasons.append({"key": key, "points": awarded})

    if has_non_book_category and not (has_book_category or valid_isbn or has_author):
        reasons.append({"key": "blocked_non_book_category", "points": 0})
        return BookClassification(
            score=score,
            is_book_product=False,
            reasons=reasons,
            has_primary_book_signal=False,
        )
    if title_is_non_book and not (has_book_category or valid_isbn or has_book_metadata):
        reasons.append({"key": "blocked_game_toy_title", "points": 0})
        return BookClassification(
            score=score,
            is_book_product=False,
            reasons=reasons,
            has_primary_book_signal=False,
        )

    has_primary_book_signal = has_book_category or valid_isbn
    if has_author and has_book_metadata:
        has_primary_book_signal = True
    return BookClassification(
        score=score,
        is_book_product=score >= 3 and has_primary_book_signal,
        reasons=reasons,
        has_primary_book_signal=has_primary_book_signal,
    )


def is_book_product_page(data: dict[str, object]) -> bool:
    return classify_book_product(data).is_book_product


def infer_shop_book_type(data: dict[str, object]) -> BookType:
    format_value = data.get("format")
    normalized_format = (
        _normalize_text(format_value) if isinstance(format_value, str) else ""
    )

    if normalized_format in _AUDIO_FORMATS:
        return "audio"
    if normalized_format in _EBOOK_FORMATS:
        return "ebook"
    if normalized_format in _BOOK_FORMATS:
        return "book"

    categories = data.get("categories")
    if _categories_contain_keywords(categories, ("audioknyg", "audiokny")):
        return "audio"
    if _categories_contain_keywords(categories, ("e-knyg", "eknyg", "elektronin")):
        return "ebook"

    if classify_book_product(data).is_book_product:
        return "book"
    return "non_book"


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


def parse_category_page(html: str) -> dict[str, object]:
    """Parse product cards from a vaga.lt category page.

    Returns ``{"products": [...], "total": None}``. vaga.lt's category
    HTML doesn't expose a reliable total-count signal, so the spider
    falls back to per-page chained pagination — same behaviour as
    before the contract change. Each product dict keeps its previous
    keys (url, title, author, price, price_original, image_url).
    Prices are in Lithuanian format: '16,32€' -> '16.32'. URLs have
    query parameters stripped (e.g. '?limit=100' removed).
    """
    products: list[dict[str, str | None]] = []
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
    return {"products": products, "total": None}


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
            ld_types = [str(value) for value in ld_type]
        elif ld_type:
            ld_types = [str(ld_type)]
        else:
            ld_types = []
        schema_types.update(ld_types)
        is_product = "Product" in ld_types or "Book" in ld_types

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

    # Auto-detect format from available properties.
    # Only trust Trukmė (duration) when it's non-zero — vaga.lt leaves
    # the field on regular books with "0 val. 00 min." which would
    # otherwise misclassify textbooks as audiobooks.
    trukme = prop_map.get("Trukmė", "").strip()
    has_real_duration = bool(trukme and re.search(r"[1-9]", trukme))
    if has_real_duration:
        data["format"] = "audiobook"
    elif "Viršelis" in prop_map:
        data["format"] = format_from_cover_type(prop_map["Viršelis"])
    elif "Puslapiai" in prop_map:
        data["format"] = "book"

    # Parse planned_availability_date, rating, review_count using BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # planned_availability_date: "Planuojame turėti YYYY-MM-DD"
    avail_span = soup.select_one(".form-group.isankstine .information-content span")
    if avail_span is None:
        # Fallback: any span containing the Lithuanian phrase
        for span in soup.find_all("span"):
            if "Planuojame turėti" in (span.get_text() or ""):
                avail_span = span
                break
    if avail_span:
        avail_text = avail_span.get_text(strip=True)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", avail_text)
        if date_match:
            data["planned_availability_date"] = date_match.group(1)

    # rating: count filled fa-star icons inside .rating-box .fa-stack spans
    rating_box = soup.select_one(".rating-box")
    if rating_box:
        stacks = rating_box.select(".fa.fa-stack")
        if stacks:
            filled = sum(1 for s in stacks if s.select_one("i.fa-star:not(.fa-star-o)"))
            # Only set rating when at least one star is filled (i.e. there are ratings)
            if filled > 0:
                data["rating"] = float(filled)

    # review_count: leading integer from a.reviews_button text
    reviews_btn = soup.select_one("a.reviews_button")
    if reviews_btn:
        reviews_text = reviews_btn.get_text(strip=True)
        count_match = re.match(r"(\d+)", reviews_text)
        if count_match:
            data["review_count"] = int(count_match.group(1))

    data["schema_types"] = sorted(schema_types)
    classification = classify_book_product(data)
    data["is_book_product"] = classification.is_book_product
    data["book_score"] = classification.score
    data["book_score_reasons"] = classification.reasons
    data["type"] = infer_shop_book_type(data)
    return data
