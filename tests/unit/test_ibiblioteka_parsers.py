from pathlib import Path

from book_scraper.spiders.ibiblioteka.parsers import (
    parse_ibiblioteka_search_response,
    parse_product_page,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ibiblioteka"
_BASE_URL = "https://ibiblioteka.lt/metis-api/bibliographic-records/public/"


# ── search response ────────────────────────────────────────────────────────

def test_parse_search_response_returns_product_urls():
    json_text = (FIXTURES / "search_response.json").read_text(encoding="utf-8")
    result = parse_ibiblioteka_search_response(json_text)

    products = result["products"]
    assert len(products) == 10
    for p in products:
        assert p["url"].startswith(_BASE_URL)
        # URL ends with a numeric ID
        assert p["url"].split("/")[-1].isdigit()


def test_parse_search_response_products_have_title_and_year():
    json_text = (FIXTURES / "search_response.json").read_text(encoding="utf-8")
    result = parse_ibiblioteka_search_response(json_text)

    products = result["products"]
    # Every product should have a title from titleView
    assert all(p.get("title") for p in products)
    # Every product should have a year parsed from publicationView
    assert all(p.get("year") for p in products)
    # is_book_product should be set for all
    assert all(p.get("is_book_product") for p in products)


def test_parse_search_response_total_is_none():
    json_text = (FIXTURES / "search_response.json").read_text(encoding="utf-8")
    result = parse_ibiblioteka_search_response(json_text)
    # Chained pagination — total is intentionally not exposed
    assert result["total"] is None


def test_parse_search_response_handles_empty_json():
    result = parse_ibiblioteka_search_response("{}")
    assert result["products"] == []
    assert result["total"] is None


def test_parse_search_response_handles_invalid_json():
    result = parse_ibiblioteka_search_response("Bad request")
    assert result["products"] == []


# ── translated printed book ────────────────────────────────────────────────

def test_parse_product_page_emits_canonical_book():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["_emit_as"] == "book"
    assert data["data_source"] == "ibiblioteka"
    assert data["libis_code"] == "LIBIS000000411913"


def test_parse_product_page_translated_book_isbn():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    isbns = [i["isbn"] for i in data["isbns"]]
    assert "978-9955-717-09-6" in isbns


def test_parse_product_page_translated_book_title():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["title"] == "Didžios meilės troškimas"


def test_parse_product_page_translated_book_publisher():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["publisher"] == "Kultūros vystymo ir švietimo viešoji įstaiga"


def test_parse_product_page_translated_book_year():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["year"] == 2024


def test_parse_product_page_translated_book_translators():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    translator_names = [a["name"] for a in data["authors"] if a["role"] == "translator"]
    assert any("Karpauskaitė" in n for n in translator_names)
    assert any("Kriščiūnas" in n for n in translator_names)


def test_parse_product_page_translated_book_format():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["type"] == "book"


def test_parse_product_page_translated_book_cover():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["cover_url"] is not None
    assert data["cover_url"].startswith("https://ibiblioteka.lt/")
    assert data["cover_url"].endswith(".jpg")


def test_parse_product_page_translated_book_is_book_product():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["is_book_product"] is True
    assert data["book_score"] > 0


def test_parse_product_page_translated_book_pages():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["pages"] == 122


# ── audio book ─────────────────────────────────────────────────────────────

def test_parse_product_page_audio_type():
    json_text = (FIXTURES / "product_detail_audio.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["type"] == "audio"
    # canonical format = LIBIS publicationFormat (PRINTED/ELECTRONIC)
    assert data["format"] == "ELECTRONIC"


def test_parse_product_page_audio_isbn():
    json_text = (FIXTURES / "product_detail_audio.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    isbns = [i["isbn"] for i in data["isbns"]]
    assert "978-609-491-262-7" in isbns


def test_parse_product_page_audio_author():
    json_text = (FIXTURES / "product_detail_audio.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    author_names = [a["name"] for a in data["authors"] if a["role"] == "author"]
    assert any("Mildažytė" in n for n in author_names)


def test_parse_product_page_audio_narrator():
    json_text = (FIXTURES / "product_detail_audio.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    narrator_names = [a["name"] for a in data["authors"] if a["role"] == "narrator"]
    assert any("Mildažytė" in n for n in narrator_names)


def test_parse_product_page_audio_duration():
    json_text = (FIXTURES / "product_detail_audio.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["duration"] is not None
    assert "val" in data["duration"]


def test_parse_product_page_audio_no_pages():
    json_text = (FIXTURES / "product_detail_audio.json").read_text(encoding="utf-8")
    data = parse_product_page(json_text)
    assert data["pages"] is None


# ── URL helpers ────────────────────────────────────────────────────────────

def test_ibiblioteka_url_round_trip():
    from book_scraper.spiders.ibiblioteka_api_urls import (
        advance_ibiblioteka_url,
        parse_ibiblioteka_url_params,
    )

    base = (
        "https://ibiblioteka.lt"
        "/metis-api/bibliographic-records/public/detailed-search"
        "?psi=0&ps=100&yf=2024&yt=2025"
    )
    psi, ps, yf, yt = parse_ibiblioteka_url_params(base)
    assert psi == 0
    assert ps == 100
    assert yf == 2024
    assert yt == 2025

    next_url = advance_ibiblioteka_url(base, 100)
    psi2, ps2, yf2, yt2 = parse_ibiblioteka_url_params(next_url)
    assert psi2 == 100
    assert ps2 == ps
    assert yf2 == yf
    assert yt2 == yt


def test_ibiblioteka_post_body_contains_year_range():
    import json as json_mod

    from book_scraper.spiders.ibiblioteka_api_urls import (
        build_ibiblioteka_post_request_kwargs,
    )

    url = (
        "https://ibiblioteka.lt"
        "/metis-api/bibliographic-records/public/detailed-search"
        "?psi=200&ps=100&yf=2023&yt=2024"
    )
    kwargs = build_ibiblioteka_post_request_kwargs(url)
    body = json_mod.loads(kwargs["body"])

    assert body["pageStartIndex"] == 200
    assert body["pageSize"] == 100
    assert body["publicationDateRange"]["from"].startswith("2023-")
    assert body["publicationDateRange"]["to"].startswith("2024-")
    assert body["languages"][0]["code"] == "lit"


def test_build_seed_urls_covers_configured_range():
    from book_scraper.config_models import IbibliotekaApiConfig
    from book_scraper.spiders.ibiblioteka_api_urls import build_ibiblioteka_seed_urls

    conf = IbibliotekaApiConfig(year_from=2020, year_to=2027, page_size=100)
    urls = build_ibiblioteka_seed_urls(conf)

    assert len(urls) == 7  # 2020 … 2026 inclusive
    assert all("psi=0" in u for u in urls)
    assert any("yf=2020" in u for u in urls)
    assert any("yf=2026" in u for u in urls)
