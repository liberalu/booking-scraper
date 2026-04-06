from unittest.mock import patch

from book_scraper.config import CONFIG_DIR, load_default_config, load_shop_config


def test_load_default_config():
    config = load_default_config()
    assert isinstance(config, dict)
    assert "scrapy" in config
    assert "database" in config


def test_load_default_config_missing_file(tmp_path):
    with patch("book_scraper.config.CONFIG_DIR", tmp_path / "nonexistent"):
        result = load_default_config()
        assert result == {}


def test_load_shop_config():
    config = load_shop_config("vaga")
    assert isinstance(config, dict)
    assert config["shop"]["name"] == "vaga"
    assert "scraping" in config
    assert "discover" in config


def test_load_shop_config_missing_shop():
    config = load_shop_config("nonexistent_shop")
    assert config == {}


def test_config_dir_points_to_config():
    assert CONFIG_DIR.name == "config"
    assert (CONFIG_DIR / "default.toml").exists()
