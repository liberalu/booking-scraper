from pathlib import Path

import pytest

from book_scraper.spiders.vaga.parsers import (
    classify_book_product,
    infer_shop_book_type,
    is_book_product_page,
    parse_category_page,
    parse_product_page,
    parse_sitemap_urls,
    title_looks_like_game_or_toy,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_sitemap_urls():
    xml_content = (FIXTURES / "vaga_sitemap.xml").read_text()
    urls = parse_sitemap_urls(xml_content)
    assert len(urls) > 0
    assert all(url.startswith("https://vaga.lt/") for url in urls)


def test_parse_category_page():
    html = (FIXTURES / "vaga_category_page.html").read_text()
    result = parse_category_page(html)
    products = result["products"]
    assert len(products) > 0
    first = products[0]
    assert "url" in first
    assert "title" in first
    assert "price" in first
    assert first["url"].startswith("https://vaga.lt/")
    # OpenCart's "Rodoma nuo 1 iki 100 iš 9910" line carries the catalogue
    # total — the spider uses it to enqueue all pages upfront.
    assert result["total"] == 9910


def test_parse_product_page():
    html = (FIXTURES / "vaga_product_page.html").read_text()
    data = parse_product_page(html)
    assert data["title"] is not None
    assert data["price"] is not None
    assert data["author"] is not None
    assert "isbn" in data
    assert "in_stock" in data
    assert "categories" in data
    assert data["is_book_product"] is True
    assert data["type"] == "book"


def test_parse_product_page_unescapes_html_entities_in_title():
    """JSON-LD carries raw HTML entities like &amp; — unescape before storing."""
    ld = (
        '{"@type":"Book",'
        '"name":"Scythe &amp; Sparrow",'
        '"description":"A &quot;great&quot; read &lt;3",'
        '"sku":"1",'
        '"offers":{"price":"10","availability":"InStock"},'
        '"brand":{"name":"Tom &amp; Jerry Press"}}'
    )
    html_doc = (
        '<html><body><script type="application/ld+json">'
        + ld
        + "</script></body></html>"
    )
    data = parse_product_page(html_doc)
    assert data["title"] == "Scythe & Sparrow"
    assert data["description"] == 'A "great" read <3'
    assert data["publisher"] == "Tom & Jerry Press"


def test_parse_category_page_unescapes_html_entities_in_title():
    html_doc = """
    <div class="product-item-container product-1">
      <p class="name"><a href="https://vaga.lt/x">Scythe &amp; Sparrow</a></p>
      <span class="price coupon">10,00€</span>
    </div>
    """
    products = parse_category_page(html_doc)["products"]
    assert products[0]["title"] == "Scythe & Sparrow"


def test_parse_category_page_extracts_author():
    html_doc = """
    <div class="product-item-container product-1">
      <p class="name"><a href="https://vaga.lt/x">Title</a></p>
      <p class="Autorius">Paulo Coelho</p>
      <span class="price coupon">10,00€</span>
    </div>
    <div class="product-item-container product-2">
      <p class="name"><a href="https://vaga.lt/y">No Author</a></p>
      <span class="price coupon">5,00€</span>
    </div>
    """
    products = parse_category_page(html_doc)["products"]
    assert products[0]["author"] == "Paulo Coelho"
    assert products[1]["author"] is None


def test_parse_product_page_unescapes_author():
    html_doc = """
    <div class="brand"><span>Autorius </span><a>Tom &amp; Jerry</a></div>
    """
    data = parse_product_page(html_doc)
    assert data["author"] == "Tom & Jerry"


def test_parse_product_page_price_new_special_overrides_jsonld():
    """When 'price-new special' is present, it's the true selling price.
    The JSON-LD offers.price is a non-public value on that layout, so we
    drop it rather than surface it as a strikethrough 'was' price."""
    ld = (
        '{"@type":"Book","name":"X","sku":"1",'
        '"offers":{"price":"26.14","availability":"InStock"}}'
    )
    html_doc = (
        '<html><body><script type="application/ld+json">'
        + ld
        + '</script><div class="product-price-wrapper prices">'
        '<span class="price-new special"> 15,80€ </span></div>'
        "</body></html>"
    )
    data = parse_product_page(html_doc)
    assert data["price"] == "15.80"
    assert data["price_original"] is None


def test_parse_product_page_extracts_rich_description():
    """collapse-description block wins over flat JSON-LD description and
    retains allowed paragraph tags."""
    ld = (
        '{"@type":"Book","name":"X","sku":"1","description":"plain flat",'
        '"offers":{"price":"10","availability":"InStock"}}'
    )
    body = (
        '<div id="collapse-description" class="desc-collapse">'
        "<p>First para.</p><p>Second <strong>bold</strong> para.</p>"
        "<script>alert(1)</script>"
        '<span style="color:red">should strip</span>'
        "</div>"
    )
    html_doc = (
        '<html><body><script type="application/ld+json">'
        + ld
        + "</script>"
        + body
        + "</body></html>"
    )
    data = parse_product_page(html_doc)
    assert "First para." in data["description"]
    assert "<p>" in data["description"]
    assert "<strong>bold</strong>" in data["description"]
    assert "<script>" not in data["description"]
    assert "alert(1)" not in data["description"]
    assert "style=" not in data["description"]
    assert "should strip" in data["description"]  # tag stripped, text kept


def test_parse_product_page_price_new_coupon_also_overrides():
    """price-new coupon and price-new special share the same semantic."""
    ld = (
        '{"@type":"Book","name":"X","sku":"1",'
        '"offers":{"price":"15.50","availability":"InStock"}}'
    )
    html_doc = (
        '<html><body><script type="application/ld+json">'
        + ld
        + '</script><span class="price-new coupon">10,85€</span>'
        "</body></html>"
    )
    data = parse_product_page(html_doc)
    assert data["price"] == "10.85"


def test_parse_product_page_price_knygyne_still_wins_for_original():
    """price-knygyne represents the bookstore RRP and overrides the
    promoted JSON-LD value when both are present."""
    ld = (
        '{"@type":"Book","name":"X","sku":"1",'
        '"offers":{"price":"26.14","availability":"InStock"}}'
    )
    html_doc = (
        '<html><body><script type="application/ld+json">'
        + ld
        + '</script><span class="price-new special">15,80€</span>'
        '<div class="price-knygyne">18,90€</div></body></html>'
    )
    data = parse_product_page(html_doc)
    assert data["price"] == "15.80"
    assert data["price_original"] == "18.90"


def test_title_looks_like_game_or_toy():
    assert title_looks_like_game_or_toy("Stalo žaidimas „Teleloto“") is True
    assert title_looks_like_game_or_toy("Dėlionė vaikams") is True
    assert title_looks_like_game_or_toy("Knyga apie stalo žaidimus") is False


def test_parse_product_page_marks_board_game_as_non_book():
    ld = (
        '{"@type":"Product","name":"Stalo žaidimas \\"Teleloto\\"","sku":"1",'
        '"offers":{"price":"25.49","availability":"OutOfStock"},'
        '"brand":{"name":"Terra Publica"},'
        '"isRelatedTo":{"isbn":"4779054890696"}}'
    )
    breadcrumbs = (
        '{"@type":"BreadcrumbList","itemListElement":['
        '{"name":"Žaislai ir žaidimai"},'
        '{"name":"Stalo žaidimai"},'
        '{"name":"Šeimos stalo žaidimai"}]}'
    )
    html_doc = (
        "<html><body>"
        '<script type="application/ld+json">' + ld + "</script>"
        '<script type="application/ld+json">' + breadcrumbs + "</script>"
        "</body></html>"
    )
    data = parse_product_page(html_doc)
    assert data["title"] == 'Stalo žaidimas "Teleloto"'
    assert data["is_book_product"] is False
    assert data["book_score"] == -7
    assert any(
        r["key"] == "game_toy_title" and r["points"] == -3
        for r in data["book_score_reasons"]
    )
    assert any(
        r["key"] == "non_book_categories" and r["points"] == -4
        for r in data["book_score_reasons"]
    )
    assert data["type"] == "non_book"


def test_book_category_and_metadata_outweigh_game_like_title():
    data = {
        "title": "Knyga apie stalo žaidimus",
        "author": "Jonas Jonaitis",
        "isbn": None,
        "categories": ["Grožinė literatūra", "Laisvalaikis"],
        "pages": 240,
        "cover_type": "Minkštas",
        "year": 2024,
        "translator": None,
        "narrator": None,
        "duration": None,
        "format": "paperback",
        "schema_types": ["Product"],
    }
    assert is_book_product_page(data) is True


def test_classify_book_product_returns_score_and_reasons():
    data = {
        "title": "Stalo žaidimas „Teleloto“",
        "author": None,
        "isbn": "4779054890696",
        "categories": ["Žaislai ir žaidimai", "Stalo žaidimai"],
        "pages": None,
        "cover_type": None,
        "year": None,
        "translator": None,
        "narrator": None,
        "duration": None,
        "format": None,
        "schema_types": ["Product"],
    }
    result = classify_book_product(data)
    assert result.is_book_product is False
    assert result.score == -7
    assert any(
        r["key"] == "game_toy_title" and r["points"] == -3 for r in result.reasons
    )
    assert any(
        r["key"] == "non_book_categories" and r["points"] == -4 for r in result.reasons
    )


@pytest.mark.parametrize(
    "category",
    [
        "Negrožinė literatūra",
        "Grožinė literatūra",
        "Knygos vaikams ir jaunimui",
        "Knygos anglų kalba",
        "Audioknygos",
    ],
)
def test_top_level_book_categories_get_positive_score(category):
    data = {
        "title": "Neutral product title",
        "author": None,
        "isbn": None,
        "categories": [category],
        "pages": None,
        "cover_type": None,
        "year": None,
        "translator": None,
        "narrator": None,
        "duration": None,
        "format": None,
        "schema_types": ["Product"],
    }
    result = classify_book_product(data)
    assert result.is_book_product is True
    assert result.score == 3
    assert any(
        r["key"] == "book_categories" and r["points"] == 3 for r in result.reasons
    )


def test_infer_shop_book_type_prefers_audio_and_non_book():
    assert infer_shop_book_type({"title": "X", "format": "audiobook"}) == "audio"
    assert (
        infer_shop_book_type(
            {
                "title": "Envelope",
                "categories": ["Mokyklinės ir raštinės prekės"],
            }
        )
        == "non_book"
    )


def test_photo_album_category_triggers_non_book_signal():
    """Photo albums ("Nuotraukų albumai") should fire non_book_categories signal."""
    data = {
        "title": "Albumas GOLDBUCH Bella Vista artichoke, 200 lapų",
        "author": None,
        "isbn": None,
        "categories": ["Dovanų įdėjos", "Jaukiems namams", "Nuotraukų albumai"],
        "pages": None,
        "cover_type": None,
        "year": None,
        "translator": None,
        "narrator": None,
        "duration": None,
        "format": None,
        "schema_types": ["Product"],
    }
    result = classify_book_product(data)
    assert result.is_book_product is False
    assert any(
        r["key"] == "non_book_categories" and r["points"] == -4 for r in result.reasons
    )


def test_gift_category_alone_does_not_block_book():
    """'Dovanų idėjos' alone must not block a book that has a valid ISBN."""
    data = {
        "title": "Knyga kaip dovana",
        "author": "Jonas Jonaitis",
        "isbn": "9786090244739",
        "categories": ["Dovanų idėjos"],
        "pages": None,
        "cover_type": None,
        "year": None,
        "translator": None,
        "narrator": None,
        "duration": None,
        "format": None,
        "schema_types": ["Product"],
    }
    result = classify_book_product(data)
    assert result.is_book_product is True
    assert not any(
        r["key"] == "non_book_categories" and r["points"] != 0 for r in result.reasons
    )
