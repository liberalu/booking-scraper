"""Unit tests for typed config models."""

import pytest

from book_scraper.config_models import (
    DefaultConfig,
    GraphQLConfig,
    LupaSearchConfig,
    ShopConfig,
)


class TestShopConfig:
    def test_minimal_config(self):
        data = {
            "shop": {"name": "test", "base_url": "https://test.lt"},
        }
        config = ShopConfig.model_validate(data)
        assert config.shop.name == "test"
        assert config.shop.base_url == "https://test.lt"
        assert config.scraping.batch_size == 100  # default
        assert config.scraping.download_delay == 1.0  # default
        assert config.scraping.httpx_client_reset_after_requests == 80  # default

    def test_httpx_client_reset_override(self):
        data = {
            "shop": {"name": "fast", "base_url": "https://fast.example"},
            "scraping": {"httpx_client_reset_after_requests": 200},
        }
        config = ShopConfig.model_validate(data)
        assert config.scraping.httpx_client_reset_after_requests == 200

    def test_full_vaga_config(self):
        data = {
            "shop": {"name": "vaga", "base_url": "https://vaga.lt"},
            "scraping": {
                "download_delay": 0.2,
                "concurrent_requests_per_domain": 8,
                "batch_size": 100,
                "batch_pause": 15,
                "max_retries": 2,
                "connect_timeout": 5,
                "read_timeout": 10,
                "hard_timeout": 30,
                "batch_timeout": 300,
            },
            "discover": {
                "sitemap": {
                    "url": "https://vaga.lt/sitemap.xml",
                    "max_age_hours": 168,
                },
                "categories": {
                    "url": "https://vaga.lt/knygos?limit=100&page={page}",
                    "max_age_hours": 672,
                },
                "full_crawl": {"start_url": "https://vaga.lt"},
            },
        }
        config = ShopConfig.model_validate(data)
        assert config.scraping.download_delay == 0.2
        assert config.scraping.concurrent_requests_per_domain == 8
        assert config.discover.sitemap is not None
        assert config.discover.sitemap.url == "https://vaga.lt/sitemap.xml"
        assert config.discover.categories is not None
        assert config.discover.categories.max_age_hours == 672
        assert config.discover.full_crawl is not None
        assert config.discover.full_crawl.start_url == "https://vaga.lt"

    def test_invalid_config_missing_shop(self):
        with pytest.raises(ValueError):
            ShopConfig.model_validate({"scraping": {}})

    def test_url_include_pattern(self):
        data = {
            "shop": {"name": "test", "base_url": "https://test.lt"},
            "discover": {
                "url_include_pattern": r"^https://test\.lt/[a-z]+-\d+$",
            },
        }
        config = ShopConfig.model_validate(data)
        assert config.discover.url_include_pattern is not None


class TestGraphQLConfig:
    def test_requires_non_empty_category_ids(self):
        with pytest.raises(ValueError):
            GraphQLConfig.model_validate({"category_ids": []})

    def test_accepts_single_category(self):
        c = GraphQLConfig.model_validate({"category_ids": ["5051"]})
        assert c.category_ids == ["5051"]
        assert c.page_size == 100  # default

    def test_accepts_multiple_categories(self):
        c = GraphQLConfig.model_validate(
            {"category_ids": ["5107", "7352"], "page_size": 50}
        )
        assert c.category_ids == ["5107", "7352"]
        assert c.page_size == 50


class TestLupaSearchConfig:
    def test_requires_endpoint_and_categories(self):
        c = LupaSearchConfig.model_validate(
            {
                "endpoint": "https://api.lupasearch.com/v1/query/abc",
                "category_ids": ["5107"],
            }
        )
        assert c.endpoint.endswith("/abc")
        assert c.page_size == 42  # default

    def test_rejects_empty_categories(self):
        with pytest.raises(ValueError):
            LupaSearchConfig.model_validate(
                {
                    "endpoint": "https://api.lupasearch.com/v1/query/abc",
                    "category_ids": [],
                }
            )

    def test_extra_filters_round_trip(self):
        c = LupaSearchConfig.model_validate(
            {
                "endpoint": "https://api.lupasearch.com/v1/query/abc",
                "category_ids": ["5107"],
                "extra_filters": {"is_new": ["1"]},
            }
        )
        assert c.extra_filters == {"is_new": ["1"]}


class TestPegasasConfigLoads:
    def test_pegasas_config_has_both_strategies(self):
        from book_scraper.config import load_shop_config

        config = load_shop_config("pegasas")
        assert config.discover.graphql is not None
        # LT-only subtree. 7352 and 5206 were dropped because their
        # English-language children leak through the membership-based
        # filter (~95% English by row count).
        assert config.discover.graphql.category_ids == ["5107", "5125", "6122"]
        assert config.discover.lupasearch is not None
        assert config.discover.lupasearch.endpoint.startswith(
            "https://api.lupasearch.com"
        )
        assert config.discover.lupasearch.category_ids == ["5107", "5125", "6122"]


class TestDefaultConfig:
    def test_minimal(self):
        data = {
            "scrapy": {"robotstxt_obey": True},
            "database": {"url": "postgresql+asyncpg://localhost/test"},
        }
        config = DefaultConfig.model_validate(data)
        assert config.scrapy.robotstxt_obey is True
        assert config.database.url == "postgresql+asyncpg://localhost/test"

    def test_defaults(self):
        config = DefaultConfig.model_validate({})
        assert config.scrapy.robotstxt_obey is True
        assert config.scrapy.download_delay == 1.0
