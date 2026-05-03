"""Unit tests for the LupaSearch URL/body helpers.

The DB-backed queue stores URLs only, so the round-trip
URL → POST request kwargs must be lossless.
"""

from __future__ import annotations

import json

import pytest

from book_scraper.config_models import LupaSearchConfig
from book_scraper.spiders.lupasearch_urls import (
    advance_lupasearch_url,
    build_lupasearch_post_request_kwargs,
    build_lupasearch_seed_url,
    parse_lupasearch_url_offsets,
)


@pytest.fixture
def conf() -> LupaSearchConfig:
    return LupaSearchConfig(
        endpoint="https://api.lupasearch.com/v1/query/abc",
        category_ids=["5107", "7352", "5125"],
        page_size=42,
    )


class TestSeedUrl:
    def test_includes_offset_limit_categories(self, conf: LupaSearchConfig) -> None:
        url = build_lupasearch_seed_url(conf)
        assert url.startswith("https://api.lupasearch.com/v1/query/abc?")
        offset, limit = parse_lupasearch_url_offsets(url)
        assert offset == 0
        assert limit == 42

    def test_extra_filters_are_emitted(self) -> None:
        conf = LupaSearchConfig(
            endpoint="https://api.lupasearch.com/v1/query/abc",
            category_ids=["1"],
            page_size=10,
            extra_filters={"is_new": ["1"]},
        )
        url = build_lupasearch_seed_url(conf)
        assert "f.is_new=1" in url


class TestAdvance:
    def test_replaces_offset_only(self, conf: LupaSearchConfig) -> None:
        seed = build_lupasearch_seed_url(conf)
        advanced = advance_lupasearch_url(seed, 84)
        offset, limit = parse_lupasearch_url_offsets(advanced)
        assert offset == 84
        assert limit == conf.page_size
        # category_ids preserved
        assert "category_ids=" in advanced

    def test_preserves_category_order(self, conf: LupaSearchConfig) -> None:
        seed = build_lupasearch_seed_url(conf)
        advanced = advance_lupasearch_url(seed, 42)
        seed_kwargs = build_lupasearch_post_request_kwargs(seed)
        adv_kwargs = build_lupasearch_post_request_kwargs(advanced)
        seed_filters = json.loads(seed_kwargs["body"])["filters"]
        adv_filters = json.loads(adv_kwargs["body"])["filters"]
        assert seed_filters == adv_filters


class TestPostRequestKwargs:
    def test_method_and_headers(self, conf: LupaSearchConfig) -> None:
        url = build_lupasearch_seed_url(conf)
        kwargs = build_lupasearch_post_request_kwargs(url)
        assert kwargs["method"] == "POST"
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["headers"]["Origin"] == "https://www.pegasas.lt"

    def test_body_is_valid_json(self, conf: LupaSearchConfig) -> None:
        url = build_lupasearch_seed_url(conf)
        kwargs = build_lupasearch_post_request_kwargs(url)
        body = json.loads(kwargs["body"])
        assert body["searchText"] == ""
        assert body["offset"] == 0
        assert body["limit"] == 42
        assert body["filters"]["category_ids"] == ["5107", "7352", "5125"]
        assert isinstance(body["sort"], list) and body["sort"]

    def test_advanced_offset_in_body(self, conf: LupaSearchConfig) -> None:
        url = advance_lupasearch_url(build_lupasearch_seed_url(conf), 84)
        body = json.loads(build_lupasearch_post_request_kwargs(url)["body"])
        assert body["offset"] == 84

    def test_extra_filter_round_trips_into_body(self) -> None:
        conf = LupaSearchConfig(
            endpoint="https://api.lupasearch.com/v1/query/abc",
            category_ids=["1"],
            page_size=10,
            extra_filters={"is_new": ["1"]},
        )
        url = build_lupasearch_seed_url(conf)
        body = json.loads(build_lupasearch_post_request_kwargs(url)["body"])
        assert body["filters"]["is_new"] == ["1"]
