import json
from pathlib import Path

from book_scraper.spiders.ibiblioteka.parsers import (
    parse_ibiblioteka_search_response,
    parse_product_page,
    rewrite_scan_url,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "ibiblioteka"
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


# ── author extraction ──────────────────────────────────────────────────────


def test_parse_product_page_reads_the_renamed_titlelt_name_field():
    # Live shape as of record 115594: LIBIS carries names in `titleLt`,
    # not the `value` / `name` keys the checked-in fixtures were captured with.
    record = {
        "authorViews": [
            {"code": "LNB:V*16233;=BB", "titleLt": "Maceina, Antanas (1908\u20131987)"}
        ],
        "persons": [
            {
                "code": "LNB:CgWX;=Bv",
                "titleLt": "Karpauskait\u0117, Gabija",
                "types": [{"code": "730"}],
            }
        ],
    }
    authors = parse_product_page(json.dumps(record))["authors"]

    assert authors == [
        {
            "name": "Maceina, Antanas (1908\u20131987)",
            "libis_code": "LNB:V*16233;=BB",
            "role": "author",
            "position": 0,
        },
        {
            "name": "Karpauskait\u0117, Gabija",
            "libis_code": "LNB:CgWX;=Bv",
            "role": "translator",
            "position": 0,
        },
    ]


# ── scan URL rewrite ───────────────────────────────────────────────────────


def test_rewrite_scan_url_asks_for_json_without_touching_the_url():
    # The detail endpoint content-negotiates: the browser Accept that
    # HttpxMiddleware injects gets the SPA shell, which has no title.
    url = _BASE_URL + "2097094"
    assert rewrite_scan_url(url) == {
        "url": url,
        "headers": {"Accept": "application/json"},
    }


# ── translated printed book ────────────────────────────────────────────────


def test_parse_product_page_emits_canonical_book():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(
        encoding="utf-8"
    )
    data = parse_product_page(json_text)
    assert data["_emit_as"] == "book"
    assert data["data_source"] == "ibiblioteka"
    assert data["libis_code"] == "LIBIS000000411913"


def test_parse_product_page_translated_book_isbn():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(
        encoding="utf-8"
    )
    data = parse_product_page(json_text)
    isbns = [i["isbn"] for i in data["isbns"]]
    assert "978-9955-717-09-6" in isbns


def test_parse_product_page_translated_book_title():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(
        encoding="utf-8"
    )
    data = parse_product_page(json_text)
    assert data["title"] == "Didžios meilės troškimas"


def test_parse_product_page_translated_book_publisher():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(
        encoding="utf-8"
    )
    data = parse_product_page(json_text)
    assert data["publisher"] == "Kultūros vystymo ir švietimo viešoji įstaiga"


def test_parse_product_page_translated_book_year():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(
        encoding="utf-8"
    )
    data = parse_product_page(json_text)
    assert data["year"] == 2024


def test_parse_product_page_translated_book_translators():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(
        encoding="utf-8"
    )
    data = parse_product_page(json_text)
    translator_names = [a["name"] for a in data["authors"] if a["role"] == "translator"]
    assert any("Karpauskaitė" in n for n in translator_names)
    assert any("Kriščiūnas" in n for n in translator_names)


def test_parse_product_page_translated_book_format():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(
        encoding="utf-8"
    )
    data = parse_product_page(json_text)
    assert data["type"] == "book"


def test_parse_product_page_translated_book_cover():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(
        encoding="utf-8"
    )
    data = parse_product_page(json_text)
    assert data["cover_url"] is not None
    assert data["cover_url"].startswith("https://ibiblioteka.lt/")
    assert data["cover_url"].endswith(".jpg")


def test_parse_product_page_translated_book_is_book_product():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(
        encoding="utf-8"
    )
    data = parse_product_page(json_text)
    assert data["is_book_product"] is True
    assert data["book_score"] > 0


def test_parse_product_page_translated_book_pages():
    json_text = (FIXTURES / "product_detail_translated.json").read_text(
        encoding="utf-8"
    )
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

    # New df/dt monthly format
    base = (
        "https://ibiblioteka.lt"
        "/metis-api/bibliographic-records/public/detailed-search"
        "?psi=0&ps=100&df=2024-03-01&dt=2024-04-01"
    )
    psi, ps, df, dt = parse_ibiblioteka_url_params(base)
    assert psi == 0
    assert ps == 100
    assert df == "2024-03-01"
    assert dt == "2024-04-01"

    next_url = advance_ibiblioteka_url(base, 100)
    psi2, ps2, df2, dt2 = parse_ibiblioteka_url_params(next_url)
    assert psi2 == 100
    assert ps2 == ps
    assert df2 == df
    assert dt2 == dt

    # Legacy yf/yt annual format — still accepted for backward compat
    legacy = (
        "https://ibiblioteka.lt"
        "/metis-api/bibliographic-records/public/detailed-search"
        "?psi=0&ps=100&yf=2024&yt=2025"
    )
    psi_l, ps_l, df_l, dt_l = parse_ibiblioteka_url_params(legacy)
    assert psi_l == 0
    assert ps_l == 100
    assert df_l == "2024-01-01"
    assert dt_l == "2025-01-01"


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
    assert body["languages"] == []


def test_ibiblioteka_targets_page_endpoint():
    """Regression: 2026-06 the bare …/detailed-search path started returning
    405 to POST; results moved to …/detailed-search/page. Seed URLs (the POST
    target) must carry the /page suffix."""
    from book_scraper.config_models import IbibliotekaApiConfig
    from book_scraper.spiders.ibiblioteka_api_urls import build_ibiblioteka_seed_urls

    conf = IbibliotekaApiConfig(year_from=2024, year_to=2025, page_size=100)
    urls = build_ibiblioteka_seed_urls(conf)

    assert urls, "expected at least one seed URL"
    for u in urls:
        path = u.split("?", 1)[0]
        assert path.endswith("/detailed-search/page"), path


def test_ibiblioteka_post_body_has_expanded_filter_schema():
    """Regression: the /page endpoint rejects (400) bodies missing any of the
    expanded selectedFilters keys the SPA now sends."""
    import json as json_mod

    from book_scraper.spiders.ibiblioteka_api_urls import (
        build_ibiblioteka_post_request_kwargs,
    )

    url = (
        "https://ibiblioteka.lt"
        "/metis-api/bibliographic-records/public/detailed-search/page"
        "?psi=0&ps=100&df=2024-01-01&dt=2024-02-01"
    )
    body = json_mod.loads(build_ibiblioteka_post_request_kwargs(url)["body"])

    required_filter_keys = {
        "audiences",
        "authors",
        "languages",
        "typeFilter",
        "subjects",
        "sources",
        "libraries",
        "releaseStatus",
        "rateAverages",
        "accessibleOnline",
        "accessiblePublications",
        "accessibilityFeatures",
        "mediaProperties",
        "recordStatuses",
        "dateRange",
    }
    assert required_filter_keys <= set(body["selectedFilters"])
    assert body["publicationTypes"] == ["BOOK"]


def test_build_seed_urls_covers_configured_range():
    from book_scraper.config_models import IbibliotekaApiConfig
    from book_scraper.spiders.ibiblioteka_api_urls import build_ibiblioteka_seed_urls

    conf = IbibliotekaApiConfig(year_from=2020, year_to=2027, page_size=100)
    urls = build_ibiblioteka_seed_urls(conf)

    assert len(urls) == 84  # 7 years × 12 months (2020-01 … 2026-12)
    assert all("psi=0" in u for u in urls)
    assert any("df=2020-01-01" in u for u in urls)
    assert any("dt=2027-01-01" in u for u in urls)


def test_multipart_parent_emits_part_urls():
    """When a record is multipart=True with parts[], parse_product_page
    must emit `_part_urls` so the scan spider can queue each volume for
    independent fetch (per-volume ISBNs only exist on the part records,
    not the parent — Ana Karenina T.1 + T.2 case)."""
    payload = {
        "code": "C1B0000814699",
        "title": "Ana Karenina",
        "titleFull": "Ana Karenina / Lev Tolstoj",
        "publicationDate": "2008",
        "publicationFormat": "PRINTED",
        "isbn": ["978-9955-08-782-3"],
        "multipart": True,
        "parts": [
            {"code": "C1B0000814700", "title": "[T.] 1"},
            {"code": "C1B0000814702", "title": "[T.] 2"},
        ],
        "allPhysicalAttributes": "2 t. ; 22 cm",
    }
    data = parse_product_page(json.dumps(payload))
    assert data["_emit_as"] == "book"
    assert data["_part_urls"] == [
        "https://ibiblioteka.lt/metis-api/bibliographic-records/public/C1B0000814700",
        "https://ibiblioteka.lt/metis-api/bibliographic-records/public/C1B0000814702",
    ]


def test_non_multipart_emits_empty_part_urls():
    """A single-volume record has no parts to follow."""
    payload = {
        "code": "C1B0000123456",
        "title": "Some Book",
        "publicationDate": "2020",
        "publicationFormat": "PRINTED",
        "isbn": ["9789955123456"],
        "multipart": False,
        "parts": [],
        "allPhysicalAttributes": "100 p. ; 22 cm",
    }
    data = parse_product_page(json.dumps(payload))
    assert data["_emit_as"] == "book"
    assert data["_part_urls"] == []
