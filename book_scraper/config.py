import tomllib
from pathlib import Path

from book_scraper.config_models import DefaultConfig, ShopConfig

CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_default_config() -> DefaultConfig:
    path = CONFIG_DIR / "default.toml"
    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return DefaultConfig.model_validate(data)
    return DefaultConfig()


def load_shop_config(shop_name: str) -> ShopConfig:
    path = CONFIG_DIR / "shops" / f"{shop_name}.toml"
    if not path.exists():
        raise FileNotFoundError(f"Shop config not found: {path}")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return ShopConfig.model_validate(data)
