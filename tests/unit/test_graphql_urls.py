"""Unit tests for the Magento GraphQL URL builder + parser.

Round-trip is what the discover spider's adaptive subdivision relies
on — `build_graphql_page_url` writes pageSize/currentPage/_sub into the
URL, and `parse_graphql_page_url` reads them back so the spider can
compute the right sub-range for a failed request.
"""

from __future__ import annotations

from book_scraper.config_models import GraphQLConfig
from book_scraper.spiders.graphql_urls import (
    build_graphql_page_url,
    parse_graphql_page_url,
)


def _conf(page_size: int = 50) -> GraphQLConfig:
    return GraphQLConfig(category_ids=["5107", "5125"], page_size=page_size)


class TestBuildGraphqlPageUrl:
    def test_default_page_size_used(self) -> None:
        url = build_graphql_page_url("https://www.pegasas.lt", _conf(50), page=3)
        info = parse_graphql_page_url(url)
        assert info == {"page": 3, "page_size": 50, "subdivision_depth": 0}

    def test_page_size_override_takes_precedence(self) -> None:
        url = build_graphql_page_url(
            "https://www.pegasas.lt",
            _conf(50),
            page=12,
            page_size_override=10,
        )
        info = parse_graphql_page_url(url)
        assert info == {"page": 12, "page_size": 10, "subdivision_depth": 0}

    def test_subdivision_depth_marker_in_url(self) -> None:
        url = build_graphql_page_url(
            "https://www.pegasas.lt",
            _conf(50),
            page=86,
            page_size_override=10,
            subdivision_depth=1,
        )
        assert "_sub=1" in url
        info = parse_graphql_page_url(url)
        assert info["subdivision_depth"] == 1
        assert info["page_size"] == 10
        assert info["page"] == 86

    def test_zero_depth_omits_marker(self) -> None:
        """When depth=0 the URL should be byte-identical to a non-marker
        build, so unique-URL constraints on scrape_url_items don't trip."""
        a = build_graphql_page_url("https://www.pegasas.lt", _conf(50), page=3)
        b = build_graphql_page_url(
            "https://www.pegasas.lt", _conf(50), page=3, subdivision_depth=0
        )
        assert a == b
        assert "_sub" not in a


class TestParseGraphqlPageUrl:
    def test_unknown_url_returns_zeros(self) -> None:
        assert parse_graphql_page_url("https://example.com/unrelated") == {
            "page": 0,
            "page_size": 0,
            "subdivision_depth": 0,
        }

    def test_garbage_sub_param_treated_as_zero(self) -> None:
        url = build_graphql_page_url("https://x.lt", _conf(10), page=1) + "&_sub=foo"
        info = parse_graphql_page_url(url)
        assert info["subdivision_depth"] == 0
