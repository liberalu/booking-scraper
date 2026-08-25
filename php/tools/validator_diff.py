#!/usr/bin/env python
"""Compare the two validation layers on identical items.

    PYTHONPATH=. uv run python php/tools/validator_diff.py
    PYTHONPATH=. uv run python php/tools/validator_diff.py --verbose

No database, no network. The validation layer both REWRITES the item (year
unswapped, invalid ISBN dropped, description converted to Markdown, whitespace
trimmed) and records what it noticed, so a port that skips it does not merely
lose the issue log — it stores data the reference implementation refuses or
corrects. Every case below is fed to both layers and compared on all three
outputs: the rewritten item, the reject decision, and the issues.
"""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHP = "/opt/homebrew/opt/php@8.4/bin/php"

URL = "https://vaga.lt/a-book"

# One case per check, plus the combinations where checks interact.
CASES: list[tuple[str, dict, str]] = [
    ("clean item", {"title": "A Book", "price": "12.99", "in_stock": True}, URL),
    ("missing price in stock", {"title": "A Book", "in_stock": True}, URL),
    ("missing price out of stock", {"title": "A Book", "in_stock": False}, URL),
    ("missing price, stock unknown", {"title": "A Book"}, URL),
    ("zero price in stock", {"title": "A Book", "price": "0", "in_stock": True}, URL),
    ("zero price out of stock", {"title": "A Book", "price": "0", "in_stock": False}, URL),
    ("price above original", {"title": "A Book", "price": "20", "price_original": "10"}, URL),
    ("price equals original", {"title": "A Book", "price": "10", "price_original": "10"}, URL),
    ("original zero", {"title": "A Book", "price": "10", "price_original": "0"}, URL),
    ("unparseable price", {"title": "A Book", "price": "n/a"}, URL),
    ("unparseable original", {"title": "A Book", "price": "10", "price_original": "n/a"}, URL),
    ("price with scale", {"title": "A Book", "price": "12.30"}, URL),
    ("missing title", {"price": "10"}, URL),
    ("empty title", {"title": "", "price": "10"}, URL),
    ("one char title", {"title": "A", "price": "10"}, URL),
    ("long title", {"title": "x" * 301, "price": "10"}, URL),
    ("html in title", {"title": "A <b>Book</b>", "price": "10"}, URL),
    ("html in author", {"title": "A Book", "author": "<i>Someone</i>", "price": "10"}, URL),
    ("whitespace fields", {"title": "  A Book  ", "author": " Someone ",
                           "publisher": " Press ", "price": "10"}, URL),
    ("blank author", {"title": "A Book", "author": "   ", "price": "10"}, URL),
    ("valid isbn13", {"title": "A Book", "isbn": "9786090901595", "price": "10"}, URL),
    ("dashed isbn", {"title": "A Book", "isbn": "978-609-090-159-5", "price": "10"}, URL),
    ("invalid isbn", {"title": "A Book", "isbn": "1234567890123", "price": "10"}, URL),
    ("double prefixed isbn", {"title": "A Book", "isbn": "9789789609015", "price": "10"}, URL),
    ("year in range", {"title": "A Book", "year": 2024, "price": "10"}, URL),
    ("year as string", {"title": "A Book", "year": "2024", "price": "10"}, URL),
    ("year not a number", {"title": "A Book", "year": "n/a", "price": "10"}, URL),
    ("year too small", {"title": "A Book", "year": 1200, "price": "10"}, URL),
    ("year/pages swap in properties", {"title": "A Book", "year": 320,
                                       "properties": {"pages": 2019}, "price": "10"}, URL),
    # No "swap from a top-level `pages`" case: `pages` is not a ShopBookItem
    # field (scrapy raises KeyError on assignment), so that branch of
    # _validate_year is unreachable in the reference implementation. The PHP
    # side keeps the branch for parity but it cannot be exercised.
    ("year out of range, pages too", {"title": "A Book", "year": 320,
                                      "properties": {"pages": 400}, "price": "10"}, URL),
    ("audiobook with pages", {"title": "A Book", "format": "audiobook",
                              "properties": {"pages": 300}, "price": "10"}, URL),
    ("book with duration", {"title": "A Book", "format": "book",
                            "properties": {"duration": "3h"}, "price": "10"}, URL),
    ("paperback with duration", {"title": "A Book", "format": "paperback",
                                 "properties": {"duration": "3h"}, "price": "10"}, URL),
    ("audiobook with duration", {"title": "A Book", "format": "audiobook",
                                 "properties": {"duration": "3h"}, "price": "10"}, URL),
    ("html description", {"title": "A Book", "price": "10",
                          "description": "<p>Hello <b>world</b></p>"}, URL),
    ("plain description", {"title": "A Book", "price": "10", "description": "Hello"}, URL),
    ("empty html description", {"title": "A Book", "price": "10",
                                "description": "<p></p>"}, URL),
    ("bad url", {"title": "A Book", "price": "10"}, "not-a-url"),
    ("empty url", {"title": "A Book", "price": "10"}, ""),
    ("ftp url", {"title": "A Book", "price": "10"}, "ftp://vaga.lt/a"),
    ("everything wrong", {"title": "A", "author": "<b>x</b>", "isbn": "111",
                          "year": 999, "price": "0", "price_original": "0",
                          "format": "audiobook", "properties": {"pages": 10},
                          "in_stock": True}, URL),
]

# Attribute-schema cases: no shop declares one today, so these are the only
# coverage that check has.
SCHEMA = {"allowed_keys": ["pages", "cover_type"],
          "rules": {"cover_type": {"enum": ["Kietas", "Minkštas"]},
                    "pages": {"pattern": r"\d+"}}}
SCHEMA_CASES: list[tuple[str, dict]] = [
    ("attributes ok", {"title": "A Book", "price": "10",
                       "properties": {"pages": "300", "cover_type": "Kietas"}}),
    ("attribute unknown key", {"title": "A Book", "price": "10",
                               "properties": {"weight": "1kg"}}),
    ("attribute bad enum", {"title": "A Book", "price": "10",
                            "properties": {"cover_type": "Squishy"}}),
    ("attribute bad pattern", {"title": "A Book", "price": "10",
                               "properties": {"pages": "many"}}),
    ("attribute null value", {"title": "A Book", "price": "10",
                              "properties": {"cover_type": None}}),
]


def run_python(item: dict, url: str, schema: dict | None) -> dict:
    from itemadapter import ItemAdapter
    from scrapy.exceptions import DropItem

    from book_scraper.items import ShopBookItem
    from book_scraper.pipelines import ValidationPipeline

    pipeline = ValidationPipeline()
    if schema is not None:
        # The pipeline reads the schema off the spider through the crawler;
        # stand in for both rather than booting scrapy.
        from book_scraper.config_models import AttributesConfig

        class _Conf:
            attributes = AttributesConfig.from_toml({
                "allowed_keys": schema["allowed_keys"],
                **schema["rules"],
            })

        class _Spider:
            conf = _Conf()

        class _Crawler:
            spider = _Spider()

        pipeline.crawler = _Crawler()  # type: ignore[assignment]

    shop_item = ShopBookItem()
    for key, value in item.items():
        shop_item[key] = value
    shop_item["url"] = url
    shop_item["shop_name"] = "vaga"

    reject = None
    try:
        pipeline.process_item(shop_item)
    except DropItem as error:
        reject = str(error)

    adapter = ItemAdapter(shop_item)
    return {
        "item": {k: v for k, v in dict(adapter).items()
                 if k not in ("url", "shop_name") and v is not None},
        "reject": reject,
        "issues": pipeline.drain_issues(),
    }


def run_php(item: dict, url: str, schema: dict | None) -> dict:
    payload = {"url": url, "item": item}
    if schema is not None:
        payload["attributes"] = schema
    result = subprocess.run(
        [PHP, "bin/validate-item"],
        cwd=ROOT / "php" / "crawler",
        input=json.dumps(payload).encode(),
        capture_output=True,
        check=True,
    )
    parsed = json.loads(result.stdout)
    parsed["item"] = {k: v for k, v in parsed["item"].items() if v is not None}

    return parsed


def normalise(result: dict) -> dict:
    """Comparable shape: issues sorted, numbers as numbers."""
    issues = sorted(
        (
            (i.get("issue"), i.get("field"), i.get("url"), i.get("raw_value"))
            for i in result["issues"]
        )
    )
    item = {}
    for key, value in result["item"].items():
        # Python keeps a Decimal string, PHP a numeric string; compare as text.
        item[key] = str(value) if isinstance(value, (int, float)) else value

    return {"item": item, "reject": result["reject"] is not None, "issues": issues}


def diff(a: object, b: object, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: extra in php ({b[key]!r})")
            elif key not in b:
                out.append(f"{path}.{key}: MISSING IN PHP ({a[key]!r})")
            else:
                out += diff(a[key], b[key], f"{path}.{key}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = [] if len(a) == len(b) else [f"{path}: {a!r} vs {b!r}"]
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    if isinstance(a, tuple) and isinstance(b, tuple):
        return [] if a == b else [f"{path}: python={a!r} php={b!r}"]

    return [] if a == b else [f"{path}: python={a!r} php={b!r}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    all_cases = [(label, item, url, None) for label, item, url in CASES]
    all_cases += [(label, item, URL, SCHEMA) for label, item in SCHEMA_CASES]

    failures = 0
    issues_seen = 0
    for label, item, url, schema in all_cases:
        # deepcopy, not dict(): the Python layer rewrites nested
        # `properties` in place, so a shallow copy lets the first run mutate
        # the input the second one gets — and the comparison silently tests
        # two different items.
        python = normalise(run_python(deepcopy(item), url, schema))
        php = normalise(run_php(deepcopy(item), url, schema))
        issues_seen += len(python["issues"])

        differences = diff(python, php)
        if differences:
            failures += 1
            print(f"  DIFFER {label}  ({len(differences)})")
            shown = differences if args.verbose else differences[:4]
            for line in shown:
                print(f"         {line}")
        else:
            found = ", ".join(sorted({i[0] for i in python["issues"]})) or "no issues"
            print(f"  OK     {label:34} {found}")

    print(f"\n{len(all_cases) - failures}/{len(all_cases)} cases identical "
          f"({issues_seen} issues compared)")
    if issues_seen == 0:
        print("INCONCLUSIVE — no case produced an issue, so this proves nothing.")
        return 1

    return failures


if __name__ == "__main__":
    sys.exit(main())
