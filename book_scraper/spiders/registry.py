import importlib
from types import ModuleType


def load_parsers(shop_name: str) -> ModuleType:
    """Dynamically load the parsers module for a shop.

    Looks for book_scraper.spiders.<shop_name>.parsers
    Raises ImportError if the shop's parser module doesn't exist.
    """
    module_path = f"book_scraper.spiders.{shop_name}.parsers"
    return importlib.import_module(module_path)
