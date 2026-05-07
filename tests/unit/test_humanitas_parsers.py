from pathlib import Path

import pytest

from book_scraper.spiders.humanitas.parsers import (
    parse_category_page,
    parse_index_page,
    parse_product_page,
    parse_sitemap_urls,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "humanitas"


def test_parse_sitemap_urls_extracts_product_links_from_index_page():
    html = (FIXTURES / "index_page.html").read_text(encoding="utf-8")
    urls = parse_sitemap_urls(html)
    assert urls, "expected at least one product URL"
    # Every URL must be on the LT product permalink namespace.
    assert all(
        u.startswith("https://www.humanitas.lt/produktas/") for u in urls
    ), "non-product URL leaked into sitemap output"
    # The recon snapshot of the homepage's swiper rendered ~31 product
    # cards via `<a class="book-item">`. Production catalogue pages
    # render up to `m575a2product_limit` (capped at 5 000) cards.
    assert len(urls) >= 10


def test_parse_index_page_returns_list_of_url_dicts():
    html = (FIXTURES / "index_page.html").read_text(encoding="utf-8")
    items = parse_index_page(html)
    assert items
    assert items[0]["url"].startswith("https://www.humanitas.lt/produktas/")


def test_parse_category_page_extracts_per_card_fields():
    """Listing cards carry url + title + author + price + image.

    Discover then emits both `DiscoveredUrlItem` and `ShopBookItem`
    per card, persisting Price rows for the whole LT catalogue in a
    single FlareSolverr round trip. The detail page is only needed
    for first-sight metadata enrichment (ISBN/year/pages/format).
    """
    html = (FIXTURES / "index_page.html").read_text(encoding="utf-8")
    result = parse_category_page(html)
    assert result["total"] is None
    products = result["products"]
    assert len(products) >= 10

    # Find the canonical Wittgensteino meilužė card — its values are
    # known from the live recon snapshot.
    wittgenstein = next(
        (p for p in products if "wittgensteino-meiluze" in p["url"]),
        None,
    )
    assert wittgenstein is not None, "expected wittgensteino-meiluze in fixture"
    assert wittgenstein["title"] == "Wittgensteino meilužė"
    assert wittgenstein["author"] == "David Markson"
    assert wittgenstein["price"] == "14.25"          # final / discounted
    assert wittgenstein["price_original"] == "15.00"  # pre-discount
    assert wittgenstein["image_url"]
    assert wittgenstein["image_url"].startswith("https://www.humanitas.lt/uploads/")
    # Listings hide OOS books, so default to in_stock=True for the
    # pipeline's NOT NULL constraint.
    assert wittgenstein["in_stock"] is True


def test_parse_category_page_dedupes_repeated_card_urls():
    """If the listing renders the same product twice (sort/swiper edges),
    we emit it once."""
    html = (
        '<a class="book-item" href="/produktas/x/foo/?cntnt01page=1">'
        '<div class="title">Foo</div></a>'
        '<a class="book-item" href="/produktas/x/foo/?cntnt01page=1">'
        '<div class="title">Foo</div></a>'
    )
    products = parse_category_page(html)["products"]
    assert len(products) == 1
    assert products[0]["url"] == "https://www.humanitas.lt/produktas/x/foo/"


def test_parse_category_page_handles_card_without_discount():
    """Some listings render only one price (no discount split)."""
    html = (
        '<a class="book-item" href="/produktas/x/foo/">'
        '<div class="author">Some Author</div>'
        '<div class="title">Foo</div>'
        '<div class="price"><div class="normal">'
        '<div class="price">19.99 €</div>'
        '</div></div></a>'
    )
    products = parse_category_page(html)["products"]
    assert len(products) == 1
    assert products[0]["price"] == "19.99"
    assert products[0]["price_original"] is None


def test_parse_category_page_drops_book_item_anchors_outside_product_namespace():
    """`<a class="book-item">` styled but pointing at /krepselis/ etc."""
    html = (
        '<a class="book-item" href="/krepselis/">cart</a>'
        '<a class="book-item" href="/produktas/x/real/">'
        '<div class="title">Real</div></a>'
    )
    products = parse_category_page(html)["products"]
    assert len(products) == 1
    assert products[0]["url"] == "https://www.humanitas.lt/produktas/x/real/"


def test_parse_sitemap_urls_handles_relative_hrefs_with_cntnt01page():
    """Paginated category cards render relative URLs with `?cntnt01page=N`."""
    html = (
        '<a class="book-item" href="/produktas/visos-kategorijos/foo/'
        '?cntnt01page=4">…</a>'
        '<a class="book-item" href="https://www.humanitas.lt/produktas/'
        'visos-kategorijos/bar/">…</a>'
    )
    urls = parse_sitemap_urls(html)
    assert urls == [
        "https://www.humanitas.lt/produktas/visos-kategorijos/foo/",
        "https://www.humanitas.lt/produktas/visos-kategorijos/bar/",
    ]


def test_parse_sitemap_urls_ignores_non_product_book_item_anchors():
    """The selector should still drop hrefs outside the product namespace."""
    html = (
        '<a class="book-item" href="/krepselis/">cart</a>'
        '<a class="book-item" href="/produktas/x/y/">book</a>'
    )
    urls = parse_sitemap_urls(html)
    assert urls == ["https://www.humanitas.lt/produktas/x/y/"]


def test_parse_product_page_extracts_full_book_info():
    html = (FIXTURES / "product_with_book_info.html").read_text(encoding="utf-8")
    data = parse_product_page(html)

    assert data["title"] == "Paraščių vaikai"
    assert data["sku"] == "189415"
    # Default availability is True; the parser only flips it when the
    # cart block carries the explicit "Likutis nepakankamas" notice.
    assert data["in_stock"] is True
    assert data["isbn"] == "9786094802966"
    assert data["author"] == "Loreta Tamulaitienė"
    assert data["publisher"] == "Lietuvos rašytojų sąjungos leidykla"
    assert data["year"] == 2022
    assert data["pages"] == 344
    assert data["cover_type"] == "Kieti viršeliai"
    # Lithuanian-language gate stays verbatim under properties.language.
    props = data.get("properties")
    assert isinstance(props, dict)
    assert props.get("language") == "Lietuvių"

    # Pricing — `Pilna kaina` is 15.90 €, `Kaina` (with the flat 5 %
    # online discount) is 15.10 €.
    assert data["price"] == "15.10"
    assert data["price_original"] == "15.90"

    # OG fallbacks.
    assert data["image_url"]
    assert data["image_url"].startswith("https://www.humanitas.lt/uploads/")
    assert data["description"] is not None
    assert "Paraščių" in (data["description"] or "") or len(
        data["description"] or ""
    ) > 50

    # Book classifier should fire (ISBN + author + book metadata).
    assert data["is_book_product"] is True
    assert data["type"] == "book"


def test_parse_product_page_tolerates_missing_book_info_block():
    """Recon found one product (Nuodingieji…) without the book-info block.

    The parser must still emit title / image / sku / price from OG
    metadata + the cart block, and must NOT raise.
    """
    html = (FIXTURES / "product_without_book_info.html").read_text(encoding="utf-8")
    data = parse_product_page(html)

    assert data["title"] == "Nuodingieji augalai šalia mūsų"
    assert data["image_url"]
    assert data["image_url"].startswith("https://www.humanitas.lt/uploads/")
    # Description from OG meta — long marketing blurb.
    assert data["description"] is not None
    assert len(data["description"] or "") > 100
    # No ISBN/author/publisher/year/pages because the block is absent —
    # we tolerate that rather than failing the row.
    assert data["isbn"] is None
    assert data["author"] is None
    assert data["publisher"] is None
    assert data["year"] is None
    assert data["pages"] is None
    # SKU should still be available from the cart container even
    # without the metadata block (verified on the recon snapshot).
    # The cart container may render the same data-product-id as
    # zeroed-out for some legacy products; allow either a non-empty
    # string or None.
    if data["sku"] is not None:
        assert data["sku"]


def test_parse_product_page_strips_humanitas_title_suffix():
    html = (
        '<html><head><title>Test Book - Humanitas</title>'
        '<meta property="og:title" content="Test Book">'
        "</head><body></body></html>"
    )
    data = parse_product_page(html)
    assert data["title"] == "Test Book"


def test_parse_product_page_rejects_non_isbn_gtin():
    """Lesson from pegasas — only Bookland prefixes are real ISBNs."""
    html = (
        '<html><head><title>Sticker pack - Humanitas</title>'
        '<meta property="og:title" content="Sticker pack">'
        '</head><body><div class="book-info">'
        "<b>ISBN:</b> 4010070123456 <br>"
        "</div></body></html>"
    )
    data = parse_product_page(html)
    assert data["isbn"] is None  # rejected — not a 978/979 prefix


def test_parse_product_page_validates_real_isbn_checksum():
    """A 978-prefixed but checksum-broken value must also be rejected."""
    html = (
        '<html><head><title>x</title>'
        '<meta property="og:title" content="x">'
        '</head><body><div class="book-info">'
        # Same prefix as the real fixture but flip the last digit.
        "<b>ISBN:</b> 9786094802961 <br>"
        "</div></body></html>"
    )
    data = parse_product_page(html)
    assert data["isbn"] is None


def test_parse_product_page_accepts_old_lt_isbn10():
    """Pre-2007 LT books carry ISBN-10 (e.g. 9986… country prefix).

    Verified live during humanitas full-catalogue scan: rows like
    `9986767156` are valid LT pre-2007 ISBNs and the parser must
    accept them (not just 978/979 Bookland 13-digit codes).
    """
    html = (
        '<html><head><title>x</title>'
        '<meta property="og:title" content="x">'
        '</head><body><div class="book-info">'
        "<b>ISBN:</b> 9986767156 <br>"
        "</div></body></html>"
    )
    data = parse_product_page(html)
    assert data["isbn"] == "9986767156"


def test_parse_product_page_extracts_translator_when_present():
    html = (
        '<html><head><title>x</title><meta property="og:title" content="x">'
        '</head><body><div class="book-info">'
        "<b>ISBN:</b> 9786094802966 <br>"
        "<b>Vertėjas:</b> Jane Doe <br>"
        "</div></body></html>"
    )
    data = parse_product_page(html)
    assert data["translator"] == "Jane Doe"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("15.90 €", "15.90"),
        ("15,90 €", "15.90"),
        ("1 234,56 €", "1234.56"),
        ("15.90", None),  # missing € → no match
    ],
)
def test_price_parsing_normalises_lithuanian_format(raw: str, expected: str | None):
    from book_scraper.spiders.humanitas.parsers import _parse_price

    assert _parse_price(raw) == expected


def test_parse_product_page_skips_dimensions_in_formatas_field():
    """`Formatas:` overloads cover-type and dimensions — only the former is format."""
    html = (
        '<html><head><title>x</title>'
        '<meta property="og:title" content="x">'
        '</head><body><div class="book-info">'
        "<b>ISBN:</b> 9786094802966 <br>"
        "<b>Formatas:</b> 288 x 243 <br>"
        "</div></body></html>"
    )
    data = parse_product_page(html)
    assert data["format"] is None
    assert data["cover_type"] is None
    props = data.get("properties")
    assert isinstance(props, dict)
    assert props.get("dimensions") == "288 x 243"


@pytest.mark.parametrize(
    "raw",
    [
        "9.25×7.5",  # Unicode multiplication sign + decimal
        "170 × 230 mm",  # space + unit suffix
        "23,5x18 cm.",  # comma decimal + unit suffix
        "19.6×12.7",  # decimals
        "198×129",  # no whitespace
    ],
)
def test_parse_product_page_skips_dimension_variants_from_format(raw: str):
    """Dimensions show up in many shapes; none should leak into `format`."""
    html = (
        '<html><head><title>x</title>'
        '<meta property="og:title" content="x">'
        '</head><body><div class="book-info">'
        f"<b>Formatas:</b> {raw} <br>"
        "</div></body></html>"
    )
    data = parse_product_page(html)
    assert data["format"] is None
    assert data["cover_type"] is None


def test_parse_product_page_treats_pasirinkite_as_missing_format():
    html = (
        '<html><head><title>x</title>'
        '<meta property="og:title" content="x">'
        '</head><body><div class="book-info">'
        "<b>Formatas:</b> Pasirinkite <br>"
        "</div></body></html>"
    )
    data = parse_product_page(html)
    assert data["format"] is None
    assert data["cover_type"] is None


def test_parse_product_page_recognises_kieti_virseliai_as_hardcover():
    html = (
        '<html><head><title>x</title>'
        '<meta property="og:title" content="x">'
        '</head><body><div class="book-info">'
        "<b>Formatas:</b> Kieti viršeliai <br>"
        "</div></body></html>"
    )
    data = parse_product_page(html)
    assert data["cover_type"] == "Kieti viršeliai"
    assert data["format"] == "hardcover"


def test_parse_product_page_drops_non_lt_books_via_language_gate():
    """English (or any non-LT) book → is_book_product=False so scan skips it."""
    html = (
        '<html><head><title>An English Book - Humanitas</title>'
        '<meta property="og:title" content="An English Book">'
        '</head><body><div class="book-info">'
        "<b>ISBN:</b> 9780349439273 <br>"
        "<b>Autorius:</b> Chloe Walsh <br>"
        "<b>Leidimo metai:</b> 2023 <br>"
        "<b>Leidinio kalba:</b> Anglų <br>"
        "</div></body></html>"
    )
    data = parse_product_page(html)
    assert data["is_book_product"] is False
    # Reason surfaces the rejection so it's visible in the dashboard.
    reasons = data.get("book_score_reasons")
    assert isinstance(reasons, list)
    assert any(r.get("key") == "blocked_non_lt_language" for r in reasons)


def test_parse_product_page_keeps_books_with_missing_language():
    """Items without a populated `Leidinio kalba` fall through (~legacy imports).

    Per the pegasas onboarding lesson: dropping these would cost
    legitimate LT books that just weren't tagged.
    """
    html = (
        '<html><head><title>Untagged - Humanitas</title>'
        '<meta property="og:title" content="Untagged">'
        '</head><body><div class="book-info">'
        "<b>ISBN:</b> 9786094802966 <br>"
        "<b>Autorius:</b> Some Author <br>"
        "<b>Leidimo metai:</b> 2023 <br>"
        "</div></body></html>"
    )
    data = parse_product_page(html)
    # No language tag → not blocked. Classifier may still decide it's
    # a book based on ISBN + author.
    reasons = data.get("book_score_reasons")
    assert isinstance(reasons, list)
    assert not any(r.get("key") == "blocked_non_lt_language" for r in reasons)


def test_parse_product_page_keeps_lithuanian_books():
    """`Leidinio kalba: Lietuvių` → standard classification, no override."""
    html = (FIXTURES / "product_with_book_info.html").read_text(encoding="utf-8")
    data = parse_product_page(html)
    assert data["is_book_product"] is True
    reasons = data.get("book_score_reasons")
    assert isinstance(reasons, list)
    assert not any(r.get("key") == "blocked_non_lt_language" for r in reasons)


def test_parse_product_page_marks_out_of_stock_when_likutis_present():
    """Cart block carries 'Likutis nepakankamas' → in_stock False."""
    html = (
        '<html><head><title>x</title>'
        '<meta property="og:title" content="x">'
        '</head><body>'
        '<div class="cart-container" data-product-id="42">'
        '  <div class="cart-price"><div class="label">Kaina:</div>'
        '    <div class="price-container"><div class="discount">'
        '15.10 €</div><div class="price">15.90 €</div></div></div>'
        '  <span>Likutis nepakankamas</span>'
        '</div></div></div></body></html>'
    )
    data = parse_product_page(html)
    assert data["in_stock"] is False
