import pytest
from unittest.mock import patch

from book_scraper.config import CONFIG_DIR, load_default_config, load_shop_config
from book_scraper.config_models import DefaultConfig, ShopConfig


def test_load_default_config():
    config = load_default_config()
    assert isinstance(config, DefaultConfig)
    assert config.scrapy.robotstxt_obey is True
    assert config.database.url is not None


def test_load_default_config_missing_file(tmp_path):
    with patch("book_scraper.config.CONFIG_DIR", tmp_path / "nonexistent"):
        result = load_default_config()
        assert isinstance(result, DefaultConfig)
        # Returns defaults when file missing
        assert result.scrapy.robotstxt_obey is True


def test_load_shop_config():
    config = load_shop_config("vaga")
    assert isinstance(config, ShopConfig)
    assert config.shop.name == "vaga"
    assert config.scraping.batch_size == 100
    assert config.discover.sitemap is not None


def test_load_shop_config_missing_shop():
    with pytest.raises(FileNotFoundError):
        load_shop_config("nonexistent_shop")


def test_config_dir_points_to_config():
    assert CONFIG_DIR.name == "config"
    assert (CONFIG_DIR / "default.toml").exists()
