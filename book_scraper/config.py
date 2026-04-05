import tomllib
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_default_config() -> dict:
    path = CONFIG_DIR / "default.toml"
    if path.exists():
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}


def load_shop_config(shop_name: str) -> dict:
    path = CONFIG_DIR / "shops" / f"{shop_name}.toml"
    if path.exists():
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}
