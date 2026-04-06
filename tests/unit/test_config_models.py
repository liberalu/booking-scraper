"""Unit tests for typed config models."""

import pytest

from book_scraper.config_models import (
    DefaultConfig,
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
        with pytest.raises(Exception):
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
