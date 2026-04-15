from pathlib import Path

from book_scraper.spiders.vaga.parsers import (
    parse_category_page,
    parse_product_page,
    parse_sitemap_urls,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_sitemap_urls():
    xml_content = (FIXTURES / "vaga_sitemap.xml").read_text()
    urls = parse_sitemap_urls(xml_content)
    assert len(urls) > 0
    assert all(url.startswith("https://vaga.lt/") for url in urls)


def test_parse_category_page():
    html = (FIXTURES / "vaga_category_page.html").read_text()
    products = parse_category_page(html)
    assert len(products) > 0
    first = products[0]
    assert "url" in first
    assert "title" in first
    assert "price" in first
    assert first["url"].startswith("https://vaga.lt/")


def test_parse_product_page():
    html = (FIXTURES / "vaga_product_page.html").read_text()
    data = parse_product_page(html)
    assert data["title"] is not None
    assert data["price"] is not None
    assert data["author"] is not None
    assert "isbn" in data
    assert "in_stock" in data
    assert "categories" in data


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
    products = parse_category_page(html_doc)
    assert products[0]["title"] == "Scythe & Sparrow"


def test_parse_product_page_unescapes_author():
    html_doc = """
    <div class="brand"><span>Autorius </span><a>Tom &amp; Jerry</a></div>
    """
    data = parse_product_page(html_doc)
    assert data["author"] == "Tom & Jerry"


def test_parse_product_page_price_new_special_overrides_jsonld():
    """When 'price-new special' is present, it's the true selling price;
    JSON-LD offers.price is the (higher) list price on that layout."""
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
    assert data["price_original"] == "26.14"


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
