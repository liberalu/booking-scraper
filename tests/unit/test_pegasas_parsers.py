"""Unit tests for the pegasas.lt parsers (GraphQL + LupaSearch).

Both parsers must produce dicts with the same keys so the discover
spider's `_emit_products` can route them through one path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from book_scraper.spiders.pegasas.parsers import (
    derive_book_type,
    parse_category_page,
    parse_lupasearch_response,
    parse_product_page,
    parse_sitemap_urls,
    rewrite_scan_url,
)

FIXTURES = Path(__file__).parents[2] / "fixtures"


@pytest.fixture
def graphql_text() -> str:
    return (FIXTURES / "pegasas_graphql_category.json").read_text()


@pytest.fixture
def lupasearch_text() -> str:
    return (FIXTURES / "pegasas_lupasearch_page1.json").read_text()


# ---------------------------------------------------------------------------
# GraphQL parser — product_page_attributes path
# ---------------------------------------------------------------------------


class TestParseCategoryPageGraphQL:
    def test_shape_includes_total(self, graphql_text: str) -> None:
        result = parse_category_page(graphql_text)
        assert set(result.keys()) == {"products", "total"}
        # Real LT total is ~45k — assert it's surfaced (powers upfront pagination).
        assert result["total"] > 1000

    def test_returns_a_product_per_item(self, graphql_text: str) -> None:
        result = parse_category_page(graphql_text)
        assert len(result["products"]) == 5

    def test_required_top_level_fields(self, graphql_text: str) -> None:
        for p in parse_category_page(graphql_text)["products"]:
            assert p["url"].startswith("https://www.pegasas.lt/")
            assert p["title"]
            assert p["sku"]
            assert p["price"]  # all 5 fixture items have a price
            assert p["type"] == "book"
            assert isinstance(p["in_stock"], bool)

    def test_majority_have_isbn_and_year(self, graphql_text: str) -> None:
        products = parse_category_page(graphql_text)["products"]
        with_isbn = sum(1 for p in products if p["isbn"])
        with_year = sum(1 for p in products if p["year"])
        # Phase 0 verified 100% on real LT fiction; tolerate one outlier.
        assert with_isbn >= len(products) - 1
        assert with_year >= len(products) - 1

    def test_publisher_is_trimmed(self, graphql_text: str) -> None:
        products = parse_category_page(graphql_text)["products"]
        publishers = [p["publisher"] for p in products if p["publisher"]]
        assert publishers, "expected at least one publisher"
        for pub in publishers:
            assert pub == pub.strip(), f"publisher not trimmed: {pub!r}"

    def test_properties_dict_includes_pages_and_cover_type(
        self, graphql_text: str
    ) -> None:
        products = parse_category_page(graphql_text)["products"]
        # At least one product should have both pages and cover_type populated
        # (sticker books in the fixture lack pages, so don't require all).
        has_pages = any(
            (p.get("properties") or {}).get("pages") is not None for p in products
        )
        has_cover = any((p.get("properties") or {}).get("cover_type") for p in products)
        assert has_pages, "expected at least one product with pages"
        assert has_cover, "expected at least one product with cover_type"

    def test_year_is_4_digit_int(self, graphql_text: str) -> None:
        products = parse_category_page(graphql_text)["products"]
        years = [p["year"] for p in products if p["year"] is not None]
        assert years
        for y in years:
            assert isinstance(y, int)
            assert 1900 <= y <= 2100

    def test_invalid_json_returns_empty(self) -> None:
        assert parse_category_page("not json") == {"products": [], "total": None}

    def test_missing_url_key_skipped(self) -> None:
        text = '{"data":{"products":{"items":[{"name":"x","sku":"s"}]}}}'
        result = parse_category_page(text)
        assert result["products"] == []

    def test_english_language_attribute_drops_product(self) -> None:
        """`Leidinio kalba: Anglų` must drop the product entirely.

        The shop mixes LT books with ~600k English drop-shipped imports
        under the same parent categories — only the language attribute
        is reliable enough to scope to LT-only.
        """
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Mike at Wrykyn",
                                "sku": "000000000002164476",
                                "url_key": "mike-at-wrykyn-2164476",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 2.75},
                                        "regular_price": {"value": 27.49},
                                    }
                                },
                                "product_page_attributes": [
                                    {
                                        "primary_attributes": [],
                                        "secondary_attributes": [
                                            {
                                                "label": "Leidinio kalba",
                                                "value": "Anglų",
                                            },
                                            {
                                                "label": "ISBN kodas",
                                                "value": "9781841591773",
                                            },
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        assert parse_category_page(text)["products"] == []

    def test_lithuanian_language_kept(self) -> None:
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Lietuviška knyga",
                                "sku": "1",
                                "url_key": "k-1",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 10.0},
                                        "regular_price": {"value": 10.0},
                                    }
                                },
                                "product_page_attributes": [
                                    {
                                        "primary_attributes": [],
                                        "secondary_attributes": [
                                            {
                                                "label": "Leidinio kalba",
                                                "value": "Lietuvių",
                                            },
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        assert len(parse_category_page(text)["products"]) == 1

    def test_ebook_detected_via_category_id(self) -> None:
        """Magento has no `is_ebook` flag — we infer from cat 6122
        ("Elektroninės knygos"). Without this fix every e-book shows
        up as type='book' (e.g. shop-book/26841 "Miesto dykuma. E.knyga").
        """
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Miesto dykuma. E.knyga",
                                "sku": "000000000011004377",
                                "url_key": "miesto-dykuma-e-knyga-11004377",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "is_audio_book": False,
                                "categories": [
                                    {"id": 6122, "name": "Elektroninės knygos"},
                                    {"id": 6137, "name": "Negrožinė literatūra"},
                                ],
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 5.0},
                                        "regular_price": {"value": 5.0},
                                    }
                                },
                                "product_page_attributes": [
                                    {
                                        "primary_attributes": [],
                                        "secondary_attributes": [
                                            {
                                                "label": "Leidinio kalba",
                                                "value": "Lietuvių",
                                            },
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        product = parse_category_page(text)["products"][0]
        assert product["type"] == "ebook"
        assert product["format"] == "ebook"

    def test_extra_attributes_captured(self) -> None:
        """`Matmenys`, `Pav. originalo kalba`, `Spalvingumas` should
        flow into `properties` — they're rendered on product pages
        and worth keeping for downstream display."""
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Test",
                                "sku": "1",
                                "url_key": "k-1",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "categories": [
                                    {"id": 5107, "name": "Grožinė literatūra"}
                                ],
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 10.0},
                                        "regular_price": {"value": 10.0},
                                    }
                                },
                                "product_page_attributes": [
                                    {
                                        "primary_attributes": [
                                            {"label": "Matmenys", "value": "21x14,5x4"},
                                        ],
                                        "secondary_attributes": [
                                            {
                                                "label": "Leidinio kalba",
                                                "value": "Lietuvių",
                                            },
                                            {
                                                "label": "Pav. originalo kalba",
                                                "value": "Original Title",
                                            },
                                            {
                                                "label": "Spalvingumas",
                                                "value": "Spalvotas",
                                            },
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        product = parse_category_page(text)["products"][0]
        props = product["properties"] or {}
        assert props["dimensions"] == "21x14,5x4"
        assert props["original_title"] == "Original Title"
        assert props["color"] == "Spalvotas"

    def test_non_isbn_ean_does_not_become_isbn(self) -> None:
        """pegasas's `EAN kodas` field carries non-book GTIN-13 codes
        (sticker kits, puzzles, etc., often `40100706...`). These must
        NOT be stored as ISBN — only 978/979 prefixes are valid."""
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Lipdukų rinkinys",
                                "sku": "1",
                                "url_key": "k-1",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "categories": [{"id": 5125, "name": "Vaikų"}],
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 10.0},
                                        "regular_price": {"value": 10.0},
                                    }
                                },
                                "product_page_attributes": [
                                    {
                                        "primary_attributes": [],
                                        "secondary_attributes": [
                                            {
                                                "label": "Leidinio kalba",
                                                "value": "Lietuvių",
                                            },
                                            {"label": "ISBN kodas", "value": ""},
                                            {
                                                "label": "EAN kodas",
                                                "value": "4010070394080",
                                            },
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        product = parse_category_page(text)["products"][0]
        assert product["isbn"] is None
        # EAN preserved separately so downstream tools still have the GTIN.
        assert (product["properties"] or {}).get("ean") == "4010070394080"

    def test_structured_data_fallback_does_not_smuggle_ean_as_isbn(self) -> None:
        """Magento puts the EAN-13 GTIN in the Schema.org `isbn` slot of
        `structured_data`, even for non-book products. The fallback path
        that reads from structured_data when product_page_attributes is
        empty must run that value through `_coerce_isbn` too — otherwise
        sticker-kit GTINs like `4770833862422` slip past the attribute
        filter and trigger downstream `invalid_isbn` validation noise.
        """
        sd = json.dumps(
            {
                "@type": "ItemPage",
                "mainEntity": {
                    "@type": ["Book", "Product"],
                    "isbn": "4770833862422",  # non-book GTIN
                    "publisher": {"name": "Some publisher"},
                    "numberOfPages": 12,
                    "datePublished": "2024-01-01",
                },
            }
        )
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Sticker kit",
                                "sku": "1",
                                "url_key": "k-1",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "categories": [{"id": 5125, "name": "Vaikų"}],
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 5.0},
                                        "regular_price": {"value": 5.0},
                                    }
                                },
                                "product_page_attributes": [],  # empty → fallback fires
                                "structured_data": sd,
                            }
                        ]
                    }
                }
            }
        )
        product = parse_category_page(text)["products"][0]
        assert product["isbn"] is None
        # Other fallback fields still populate.
        assert product["publisher"] == "Some publisher"
        assert (product["properties"] or {}).get("pages") == 12
        assert product["year"] == 2024

    def test_real_isbn_in_ean_field_picked_up(self) -> None:
        """Some books have the ISBN-13 in `EAN kodas` only (because EAN
        and ISBN-13 are the same number for books). Accept it when the
        prefix is 978/979."""
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Knyga",
                                "sku": "1",
                                "url_key": "k-1",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "categories": [{"id": 5107, "name": "Grožinė"}],
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 10.0},
                                        "regular_price": {"value": 10.0},
                                    }
                                },
                                "product_page_attributes": [
                                    {
                                        "primary_attributes": [],
                                        "secondary_attributes": [
                                            {
                                                "label": "Leidinio kalba",
                                                "value": "Lietuvių",
                                            },
                                            {"label": "ISBN kodas", "value": ""},
                                            {
                                                "label": "EAN kodas",
                                                "value": "9786094795145",
                                            },
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        product = parse_category_page(text)["products"][0]
        assert product["isbn"] == "9786094795145"

    def test_translator_skipped_when_empty(self) -> None:
        """Magento returns empty strings for translator on shops where
        the field isn't applicable (e.g. Lithuanian-original works).
        Drop empty strings instead of storing them."""
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Test",
                                "sku": "1",
                                "url_key": "k-1",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "categories": [
                                    {"id": 5107, "name": "Grožinė literatūra"}
                                ],
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 10.0},
                                        "regular_price": {"value": 10.0},
                                    }
                                },
                                "product_page_attributes": [
                                    {
                                        "primary_attributes": [
                                            {"label": "Vertėjas", "value": ""},
                                        ],
                                        "secondary_attributes": [],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        product = parse_category_page(text)["products"][0]
        props = product["properties"] or {}
        assert "translator" not in props

    def test_missing_language_attribute_kept(self) -> None:
        """Items without a language attribute fall through.

        ~1% of Magento records are missing the attribute — dropping
        them outright would lose legitimate LT books, so we only filter
        when language is *populated* and clearly non-LT.
        """
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "No-lang item",
                                "sku": "1",
                                "url_key": "n-1",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 10.0},
                                        "regular_price": {"value": 10.0},
                                    }
                                },
                                "product_page_attributes": [],
                            }
                        ]
                    }
                }
            }
        )
        assert len(parse_category_page(text)["products"]) == 1

    def test_invalid_isbn_check_digit_recovered_as_isbn13(self) -> None:
        """When `ISBN kodas` has a wrong check digit, `_coerce_isbn` must
        recover the correct ISBN-13 from the 9-digit core rather than
        discarding it or falling through to the (different) EAN.

        Real-world case: pegasas product 1100242 ("Dina gėdytojos duktė")
        has ISBN kodas = 9955082484 (ISBN-10 check digit wrong — sum 326,
        mod11=7 ≠ 0).  The correct ISBN-13 derived from the core 995508248
        is 9789955082484 (mod10=0).  The EAN kodas = 9789955232407 is a
        different book entirely and must NOT win.
        """
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Dina gėdytojos duktė",
                                "sku": "000000000001100242",
                                "url_key": "dina-gedytojos-dukte-1100242",
                                "stock_status": "OUT_OF_STOCK",
                                "is_book": True,
                                "categories": [{"id": 5107, "name": "Grožinė"}],
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 0.0},
                                        "regular_price": {"value": 0.0},
                                    }
                                },
                                "product_page_attributes": [
                                    {
                                        "primary_attributes": [],
                                        "secondary_attributes": [
                                            {"label": "Leidinio kalba", "value": "Lietuvių"},
                                            # Bad ISBN-10 check digit: sum=326, mod11=7 ≠ 0
                                            {"label": "ISBN kodas", "value": "9955082484"},
                                            # Valid ISBN-13: sum=120, mod10=0
                                            {"label": "EAN kodas", "value": "9789955232407"},
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        product = parse_category_page(text)["products"][0]
        # The bad ISBN-10 core must be recovered as its ISBN-13 equivalent.
        # The EAN kodas (9789955232407) is a different book and must NOT win.
        assert product["isbn"] == "9789955082484"

    def test_typo_isbn10_with_correct_ean_uses_ean(self) -> None:
        """When the ISBN field has a typo'd ISBN-10 but the EAN field has
        a strictly valid ISBN-13 sharing the same publisher prefix, the
        EAN wins — it's the corrected version of the same book.

        Real-world case: pegasas "Rikiki skalbia" (sb#37915).
        - ISBN kodas = 9986028368 — typo'd ISBN-10 (bad check digit,
          recovers to 9789986028369 which is a non-existent ISBN).
        - EAN kodas = 9789986028383 — valid ISBN-13 matching the
          canonical book #2322 in the books table.
        Both share the publisher prefix `978-9986-02` (first 9 digits),
        so the EAN is treated as the corrected ISBN.
        """
        text = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Rikiki skalbia",
                                "sku": "000000000001106280",
                                "url_key": "rikiki-skalbia-1106280",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "categories": [{"id": 5107, "name": "Grožinė"}],
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 4.0},
                                        "regular_price": {"value": 4.0},
                                    }
                                },
                                "product_page_attributes": [
                                    {
                                        "primary_attributes": [],
                                        "secondary_attributes": [
                                            {"label": "Leidinio kalba", "value": "Lietuvių"},
                                            # Typo'd ISBN-10 (bad check digit)
                                            {"label": "ISBN kodas", "value": "9986028368"},
                                            # Valid ISBN-13 with same publisher prefix
                                            {"label": "EAN kodas", "value": "9789986028383"},
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        product = parse_category_page(text)["products"][0]
        # EAN wins because it shares publisher prefix with the recovered
        # ISBN — the broken ISBN field is a typo, the EAN has the truth.
        assert product["isbn"] == "9789986028383"


# ---------------------------------------------------------------------------
# LupaSearch parser
# ---------------------------------------------------------------------------


class TestParseLupasearchResponse:
    def test_shape(self, lupasearch_text: str) -> None:
        result = parse_lupasearch_response(lupasearch_text)
        assert set(result.keys()) == {"products", "total"}
        assert result["total"] > 1000  # real LT total is ~45k
        assert len(result["products"]) == 10

    def test_required_top_level_fields(self, lupasearch_text: str) -> None:
        result = parse_lupasearch_response(lupasearch_text)
        for p in result["products"]:
            assert p["url"].startswith("https://www.pegasas.lt/")
            assert p["title"]
            assert p["sku"]
            assert p["price"]
            assert p["type"] in {"book", "audio", "ebook", "non_book"}
            # ISBN/year/pages are not in LupaSearch payload — must be None
            assert p["isbn"] is None
            assert p["year"] is None
            # `properties.pages` must not be invented either
            assert (p.get("properties") or {}).get("pages") is None

    def test_price_original_only_when_different(self, lupasearch_text: str) -> None:
        result = parse_lupasearch_response(lupasearch_text)
        # All fixture items are discounted, so price_original must be set.
        with_orig = sum(1 for p in result["products"] if p["price_original"])
        assert with_orig == len(result["products"])
        for p in result["products"]:
            assert float(p["price_original"]) != float(p["price"])

    def test_categories_are_strings(self, lupasearch_text: str) -> None:
        result = parse_lupasearch_response(lupasearch_text)
        for p in result["products"]:
            assert all(isinstance(c, str) for c in p["categories"])

    def test_is_new_is_round_tripped(self, lupasearch_text: str) -> None:
        result = parse_lupasearch_response(lupasearch_text)
        flagged = [
            p
            for p in result["products"]
            if (p.get("properties") or {}).get("is_new") is True
        ]
        # The fixture was captured with the default "in_stock desc, sku desc"
        # ordering which surfaces fresh stock first; >0 should be is_new.
        assert flagged, "expected at least one is_new=True product"

    def test_invalid_json_returns_empty(self) -> None:
        result = parse_lupasearch_response("not json")
        assert result == {"products": [], "total": 0}

    def test_english_category_drops_product(self) -> None:
        """Membership in cat 8128 (Knygos anglų kalba) drops the item.

        LupaSearch doesn't return the language attribute, so we use
        category membership as a proxy.
        """
        text = (
            '{"items":[{"url":"https://www.pegasas.lt/x-1/","name":"Mike at Wrykyn",'
            '"sku":"s","price":"2.75","is_book":1,"in_stock":1,'
            '"category_ids":[8128, 5051, 8129]}],"total":1}'
        )
        result = parse_lupasearch_response(text)
        assert result["products"] == []
        assert result["total"] == 1  # total still reflects unfiltered count

    def test_lt_only_category_kept(self) -> None:
        text = (
            '{"items":[{"url":"https://www.pegasas.lt/k-1/","name":"Lietuviška",'
            '"sku":"s","price":"10","is_book":1,"in_stock":1,'
            '"category_ids":[5107, 5051, 6293]}],"total":1}'
        )
        result = parse_lupasearch_response(text)
        assert len(result["products"]) == 1

    def test_dash_publisher_treated_as_missing(self) -> None:
        text = (
            '{"items":[{"url":"https://www.pegasas.lt/x-1/","name":"x","sku":"s",'
            '"leidykla":"-","price":"1","is_book":1,"in_stock":1}],"total":1}'
        )
        result = parse_lupasearch_response(text)
        assert result["products"][0]["publisher"] is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestDeriveBookType:
    def test_book(self) -> None:
        assert derive_book_type(1, 0) == "book"
        assert derive_book_type(True, False) == "book"

    def test_audio(self) -> None:
        assert derive_book_type(1, 1) == "audio"
        assert derive_book_type(0, 1) == "audio"

    def test_ebook(self) -> None:
        assert derive_book_type(0, 0, 1) == "ebook"

    def test_non_book(self) -> None:
        assert derive_book_type(0, 0) == "non_book"
        assert derive_book_type(False, False, False) == "non_book"

    def test_has_book_category_overrides_is_book_false(self) -> None:
        """When Magento's is_book is False but category evidence says
        otherwise, fall back to type='book'. Real cases: 11 pegasas
        products on 2026-05-19 (e.g. 'Vyrai ir moterys. Ką sako
        neuromokslai' had is_book=False yet sits in 'Knygos' /
        'Mokslo literatūra')."""
        assert (
            derive_book_type(False, False, has_book_category=True) == "book"
        )

    def test_has_book_category_does_not_override_audio(self) -> None:
        """is_audio_book=True still wins over the category fallback —
        audiobooks have book-like categories too."""
        assert (
            derive_book_type(False, True, has_book_category=True) == "audio"
        )

    def test_has_book_category_does_not_override_ebook(self) -> None:
        assert (
            derive_book_type(False, False, True, has_book_category=True) == "ebook"
        )

    def test_has_book_category_default_false(self) -> None:
        """Default `has_book_category=False` preserves the legacy
        behaviour: when nothing indicates a book, classify as non_book."""
        assert derive_book_type(False, False) == "non_book"


class TestCategoriesIndicateBook:
    def test_knygos_signal(self) -> None:
        from book_scraper.spiders.pegasas.parsers import _categories_indicate_book

        assert _categories_indicate_book(["Knygos"]) is True
        assert _categories_indicate_book(["Knygos vaikams iki 6 metų"]) is True
        assert _categories_indicate_book(["Knygelės"]) is True

    def test_literature_signal(self) -> None:
        from book_scraper.spiders.pegasas.parsers import _categories_indicate_book

        assert _categories_indicate_book(["Grožinė literatūra"]) is True
        assert _categories_indicate_book(["Mokslo literatūra"]) is True
        assert _categories_indicate_book(["Mokomoji literatūra"]) is True

    def test_textbook_signal(self) -> None:
        from book_scraper.spiders.pegasas.parsers import _categories_indicate_book

        assert _categories_indicate_book(["Vadovėliai"]) is True
        assert _categories_indicate_book(["Vadovėliai ir pratybos pagal klases"]) is True
        assert _categories_indicate_book(["Pratybos"]) is True

    def test_diacritic_insensitive(self) -> None:
        from book_scraper.spiders.pegasas.parsers import _categories_indicate_book

        # Lithuanian shops sometimes drop diacritics in category strings.
        assert _categories_indicate_book(["knygos"]) is True
        assert _categories_indicate_book(["grozine literatura"]) is True
        assert _categories_indicate_book(["KNYGOS"]) is True

    def test_non_book_categories(self) -> None:
        from book_scraper.spiders.pegasas.parsers import _categories_indicate_book

        assert _categories_indicate_book(["Žaislai"]) is False
        assert _categories_indicate_book(["Saldainiai"]) is False
        assert _categories_indicate_book(["Dėlionės", "Žaidimai"]) is False

    def test_unresolved_numeric_ids_do_not_signal(self) -> None:
        """When a category-ID failed to resolve to a name and was
        stringified (e.g. '10301'), it must not accidentally match a
        keyword prefix — the prefixes are alphabetic so digit-only
        strings can't match anyway, but verify the contract."""
        from book_scraper.spiders.pegasas.parsers import _categories_indicate_book

        assert _categories_indicate_book(["10301", "6208"]) is False

    def test_empty_or_none(self) -> None:
        from book_scraper.spiders.pegasas.parsers import _categories_indicate_book

        assert _categories_indicate_book(None) is False
        assert _categories_indicate_book([]) is False


class TestStubs:
    def test_sitemap_returns_empty(self) -> None:
        assert parse_sitemap_urls("<x/>") == []

    def test_product_page_returns_non_product_stub_for_html(self) -> None:
        # Non-JSON body falls back to the React-shell stub.
        result = parse_product_page("<html></html>")
        assert result["is_book_product"] is False
        assert result["type"] == "non_book"
        assert result["book_score_reasons"][0]["key"] == "pwa_shell_no_data"


class TestFormatFromCoverType:
    """The pegasas parser maps Lithuanian cover-type labels to the same
    `format` values vaga uses, so the same physical book has the same
    `format` value regardless of which shop it came from.

    Without this mapping, a printed book on pegasas had `format=null`
    while the same book on vaga had `format='hardcover'` — visible
    inconsistency on the dashboard's shop-book detail view."""

    def test_kietas_maps_to_hardcover(self) -> None:
        from book_scraper.spiders.cover_type import format_from_cover_type

        assert format_from_cover_type("Kietas") == "hardcover"
        assert format_from_cover_type("Kieti viršeliai") == "hardcover"

    def test_minkstas_maps_to_paperback(self) -> None:
        from book_scraper.spiders.cover_type import format_from_cover_type

        assert format_from_cover_type("Minkštas") == "paperback"

    def test_unknown_cover_types_return_none(self) -> None:
        """Unknown labels are dropped rather than persisted raw — the
        previous "preserve raw label" behaviour leaked dimension strings
        like '15x22' into shop_books.format, driving the
        `format_is_dimensions` validator (~1,200 issues on patogupirkti).
        """
        from book_scraper.spiders.cover_type import format_from_cover_type

        assert format_from_cover_type("Kita") is None
        assert format_from_cover_type("Aplankas") is None
        assert format_from_cover_type("Dėžutė") is None

    def test_empty_or_none_returns_none(self) -> None:
        from book_scraper.spiders.cover_type import format_from_cover_type

        assert format_from_cover_type(None) is None
        assert format_from_cover_type("") is None

    def test_dimensions_only_returns_none(self) -> None:
        """Pure dimension strings must NOT be stored as `format`.

        Real-world patogupirkti `Formatas` values that hit this path:
        '17x24', '15x21', '170 x 205 mm', '21X30 cm'.
        """
        from book_scraper.spiders.cover_type import format_from_cover_type

        for s in ("17x24", "15x21", "170 x 205 mm", "21X30 cm", "13 x 20"):
            assert format_from_cover_type(s) is None, f"{s!r} should map to None"

    def test_mixed_dimensions_and_cover_type(self) -> None:
        """Comma-separated dimensions + cover-type ('15x22, minkšti
        viršeliai') should pick out the cover-type segment.
        """
        from book_scraper.spiders.cover_type import format_from_cover_type

        assert format_from_cover_type("15x22, minkšti viršeliai") == "paperback"
        assert format_from_cover_type("21x24, kieti viršeliai") == "hardcover"
        # Typo on patogupirkti: 'keti' instead of 'kieti'.
        assert format_from_cover_type("21x24, keti viršeliai") == "hardcover"
        # Half-hard cover ("puskiečiai") — mapped to hardcover bucket.
        assert format_from_cover_type("13x20, puskiečiai viršeliai") == "hardcover"

    def test_canonical_tokens_pass_through(self) -> None:
        from book_scraper.spiders.cover_type import format_from_cover_type

        assert format_from_cover_type("hardcover") == "hardcover"
        assert format_from_cover_type("paperback") == "paperback"
        assert format_from_cover_type("ebook") == "ebook"
        assert format_from_cover_type("cd") == "cd"


class TestProductFormatFromGraphQL:
    """Integration: the format field on the product dict reflects
    cover-type for printed books, audio/ebook for the rest."""

    def _product(self, **overrides: object) -> dict[str, object]:
        from book_scraper.spiders.pegasas.parsers import _graphql_item_to_product

        item: dict[str, object] = {
            "name": "Test",
            "sku": "000000000001234567",
            "url_key": "test-1234567",
            "image": {"url": ""},
            "price_range": {
                "minimum_price": {
                    "final_price": {"value": 1.0, "currency": "EUR"},
                    "regular_price": {"value": 1.0, "currency": "EUR"},
                }
            },
            "stock_status": "IN_STOCK",
            "is_book": True,
            "is_audio_book": False,
            "anotacija": "",
            "categories": [{"id": 5107, "name": "Grožinė", "breadcrumbs": None}],
            "product_page_attributes": [
                {
                    "primary_attributes": [
                        {"label": "Viršelio tipas", "value": "Kietas"},
                    ],
                    "secondary_attributes": [],
                }
            ],
            "structured_data": "",
        }
        for k, v in overrides.items():
            item[k] = v
        return _graphql_item_to_product(item)  # type: ignore[return-value]

    def test_book_with_kietas_cover_is_hardcover(self) -> None:
        product = self._product()
        assert product is not None
        assert product["format"] == "hardcover"
        assert product["type"] == "book"

    def test_book_with_minkstas_cover_is_paperback(self) -> None:
        product = self._product(
            product_page_attributes=[
                {
                    "primary_attributes": [
                        {"label": "Viršelio tipas", "value": "Minkštas"}
                    ],
                    "secondary_attributes": [],
                }
            ]
        )
        assert product is not None
        assert product["format"] == "paperback"

    def test_book_with_no_cover_type_falls_back_to_book(self) -> None:
        product = self._product(product_page_attributes=[])
        assert product is not None
        assert product["format"] == "book"

    def test_audio_book_overrides_cover_type(self) -> None:
        product = self._product(is_audio_book=True)
        assert product is not None
        assert product["format"] == "audiobook"

    def test_audio_book_does_not_carry_pages(self) -> None:
        """Magento sometimes leaks the print edition's numberOfPages into
        the audiobook record.  The parser must discard it so we never
        get a format_mismatch 'audiobook with pages' validation issue."""
        product = self._product(
            is_audio_book=True,
            product_page_attributes=[
                {
                    "primary_attributes": [
                        {"label": "Puslapiai", "value": "320"},
                    ],
                    "secondary_attributes": [],
                }
            ],
        )
        assert product is not None
        assert product["type"] == "audio"
        props = product.get("properties") or {}
        assert "pages" not in props


class TestParseProductPageGraphQL:
    """parse_product_page now expects per-SKU GraphQL JSON (after
    rewrite_scan_url has swapped the URL). Uses a synthetic single-SKU
    response built from the first item of the category fixture so the
    test stays in lockstep with real Magento payload shapes."""

    @pytest.fixture
    def single_sku_text(self, graphql_text: str) -> str:
        category = json.loads(graphql_text)
        first_item = category["data"]["products"]["items"][0]
        return json.dumps({"data": {"products": {"items": [first_item]}}})

    def test_returns_book_product_with_full_metadata(
        self, single_sku_text: str
    ) -> None:
        result = parse_product_page(single_sku_text)
        assert result["is_book_product"] is True
        assert result["title"]
        assert result["sku"]
        assert result["type"] in ("book", "audio", "ebook")
        assert result["book_score"] == 100

    def test_empty_items_marks_non_product(self) -> None:
        result = parse_product_page(json.dumps({"data": {"products": {"items": []}}}))
        assert result["is_book_product"] is False
        assert result["book_score_reasons"][0]["key"] == "graphql_no_match"

    def test_invalid_json_falls_back_to_stub(self) -> None:
        result = parse_product_page("not json")
        assert result["is_book_product"] is False
        assert result["book_score_reasons"][0]["key"] == "pwa_shell_no_data"


class TestRewriteScanUrl:
    def test_extracts_and_pads_sku_to_18_chars(self) -> None:
        result = rewrite_scan_url("https://www.pegasas.lt/some-book-title-1115331")
        assert result is not None
        assert "000000000001115331" in result["url"]
        assert result["url"].startswith("https://www.pegasas.lt/graphql?query=")

    def test_includes_accept_json_header(self) -> None:
        result = rewrite_scan_url("https://www.pegasas.lt/some-book-1234567")
        assert result is not None
        assert result["headers"] == {"Accept": "application/json"}

    def test_handles_e_book_slug(self) -> None:
        result = rewrite_scan_url("https://www.pegasas.lt/title-e-knyga-11004377")
        assert result is not None
        assert "000000000011004377" in result["url"]

    def test_strips_trailing_slash_before_extracting(self) -> None:
        result = rewrite_scan_url("https://www.pegasas.lt/title-1115331/")
        assert result is not None
        assert "000000000001115331" in result["url"]

    def test_returns_none_for_url_without_numeric_suffix(self) -> None:
        assert rewrite_scan_url("https://www.pegasas.lt/about-us") is None
        assert rewrite_scan_url("https://www.pegasas.lt/") is None
