from book_scraper.config import load_shop_config


def test_vaga_config_has_discover_strategies():
    config = load_shop_config("vaga")
    assert config.discover is not None
    assert config.discover.sitemap is not None
    assert config.discover.sitemap.url == "https://vaga.lt/sitemap.xml"


def test_vaga_config_has_category_strategy():
    config = load_shop_config("vaga")
    assert config.discover.categories is not None
    assert config.discover.categories.url is not None


def test_vaga_config_has_max_age_hours():
    config = load_shop_config("vaga")
    assert config.discover.sitemap is not None
    assert config.discover.sitemap.max_age_hours == 168


def test_vaga_config_no_prices_section():
    config = load_shop_config("vaga")
    assert not hasattr(config, "prices")
