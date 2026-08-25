#!/usr/bin/env python
"""Regenerate the PHP issue severity + description maps.

    PYTHONPATH=. uv run python php/tools/dump_issue_metadata.py

Both maps are the dashboard's source of truth for how an issue is labelled
and ranked. Generated rather than hand-copied: a new issue type added on the
Python side would otherwise silently render as "warning" with no description
in the PHP dashboard.
"""

import pathlib

from book_scraper.dashboard.queries import ISSUE_DESCRIPTIONS, ISSUE_SEVERITY

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "php" / "dashboard" / "app" / "Support" / "IssueMetadata.php"


def php_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def main() -> None:
    severity = "\n".join(
        f"        {php_string(k)} => {php_string(v)}," for k, v in sorted(ISSUE_SEVERITY.items())
    )
    descriptions = "\n".join(
        f"        {php_string(k)} => {php_string(' '.join(v.split()))},"
        for k, v in sorted(ISSUE_DESCRIPTIONS.items())
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(f'''<?php

declare(strict_types=1);

namespace App\\Support;

/**
 * Issue severity and human-readable descriptions.
 *
 * GENERATED from book_scraper/dashboard/queries.py by
 * php/tools/dump_issue_metadata.py. Do not edit by hand — a type added on
 * the Python side would otherwise render as an undescribed "warning" here.
 */
final class IssueMetadata
{{
    /** @var array<string, string> */
    public const SEVERITY = [
{severity}
    ];

    /** @var array<string, string> */
    public const DESCRIPTIONS = [
{descriptions}
    ];

    /** Unknown types default to `warning` — the same fallback Python uses. */
    public static function severity(string $issue): string
    {{
        return self::SEVERITY[$issue] ?? 'warning';
    }}

    public static function description(string $issue): string
    {{
        return self::DESCRIPTIONS[$issue] ?? '';
    }}

    /** @return list<string> issue types at the given severity */
    public static function typesWithSeverity(string $severity): array
    {{
        return array_keys(array_filter(
            self::SEVERITY,
            static fn (string $value): bool => $value === $severity
        ));
    }}
}}
''')
    print(
        f"wrote {OUT.relative_to(ROOT)}: "
        f"{len(ISSUE_SEVERITY)} severities, {len(ISSUE_DESCRIPTIONS)} descriptions"
    )


if __name__ == "__main__":
    main()
