from book_scraper.config import load_shop_config


def test_vaga_config_has_discover_strategies():
    config = load_shop_config("vaga")
    assert "discover" in config
    assert "sitemap" in config["discover"]
    assert config["discover"]["sitemap"]["url"] == "https://vaga.lt/sitemap.xml"


def test_vaga_config_has_category_strategy():
    config = load_shop_config("vaga")
    assert "categories" in config["discover"]
    assert "url" in config["discover"]["categories"]


def test_vaga_config_has_max_age_hours():
    config = load_shop_config("vaga")
    assert "max_age_hours" in config["discover"]["sitemap"]
    assert config["discover"]["sitemap"]["max_age_hours"] == 168


def test_vaga_config_no_prices_section():
    config = load_shop_config("vaga")
    assert "prices" not in config
