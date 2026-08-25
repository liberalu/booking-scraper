#!/usr/bin/env python
"""Regenerate php/src/Pegasas/CategoryNames.php from the Python map.

    PYTHONPATH=. uv run python php/tools/dump_pegasas_categories.py

LupaSearch returns only numeric category ids while the validator's
non-book keyword checks work on names, so the PHP side needs the same
~1,170-entry map. Generated rather than hand-copied: a hand-edited copy
would drift the moment someone refreshes the Python one.
"""

import pathlib

from book_scraper.spiders.pegasas.category_names import CATEGORY_NAMES

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "php" / "src" / "Pegasas" / "CategoryNames.php"


def php_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def main() -> None:
    entries = "\n".join(
        f"        {cid} => {php_string(name)}," for cid, name in sorted(CATEGORY_NAMES.items())
    )
    OUT.write_text(f'''<?php

declare(strict_types=1);

namespace BookScraper\\Pegasas;

/**
 * Magento category id -> name.
 *
 * GENERATED from book_scraper/spiders/pegasas/category_names.py by
 * php/tools/dump_pegasas_categories.py. Do not edit by hand.
 *
 * LupaSearch returns only numeric category ids, but the validator's
 * non-book keyword checks work on names — without this map, every
 * LupaSearch-discovered row would look category-less to them.
 */
final class CategoryNames
{{
    /** @var array<int, string> */
    public const MAP = [
{entries}
    ];

    public static function name(int $id): string
    {{
        // Falls back to the id so a category added upstream degrades to a
        // harmless label rather than vanishing. Regenerate to fix.
        return self::MAP[$id] ?? (string) $id;
    }}
}}
''')
    print(f"wrote {OUT.relative_to(ROOT)} with {len(CATEGORY_NAMES)} entries")


if __name__ == "__main__":
    main()
