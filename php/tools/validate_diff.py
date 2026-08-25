#!/usr/bin/env python
"""Run both validators over identical data and diff every finding.

    PYTHONPATH=. uv run python php/tools/validate_diff.py --shop vaga

Seed realistic data first (php/tools/seed_test_db.py) — the suppression
rules were tuned against real catalogue shapes, so an empty database proves
nothing.

Test database only. The validator MUTATES data (the non_product auto-heal
deactivates shop_books), so `is_active` is snapshotted and restored between
the two passes; otherwise the second validator sees a catalogue the first
one already healed. Both passes use the same run id so findings are
comparable row for row.

Exit code is the number of differences.

--freeze writes the findings as a characterisation golden, and only accepts
--shop synthetic. A copied real shop's findings are not reproducible: the
catalogue moves with every crawl, so the counts would drift and the replay
would fail for reasons that are not regressions. The synthetic shop is built
from nothing by php/src/Testing/SyntheticShop.php and fires all 20 issue types.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

# The test database is named in one place — see _testdb for why the PHP
# side cannot share the Python suite's database.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _testdb import TEST_DSN, php_dsn  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PHP = "/opt/homebrew/opt/php@8.4/bin/php"
FREEZE_TO = ROOT / "php" / "tests" / "golden" / "validate_findings.json"
#: The only shop whose findings are reproducible — see the module docstring.
FREEZABLE_SHOP = "synthetic"
RUN_ID_SENTINEL = 999_000  # a run id neither stack will allocate naturally


def engine() -> sa.Engine:
    return sa.create_engine(TEST_DSN)


def shop_id(name: str) -> int:
    with engine().connect() as conn:
        found = conn.execute(
            sa.text("select id from shops where name = :name"), {"name": name}
        ).scalar()
    if found is None:
        sys.exit(f"shop '{name}' not in the test database — run seed_test_db.py first")
    return int(found)


def ensure_run(sid: int) -> None:
    """A findings row references a run, so make the sentinel run exist."""
    with engine().begin() as conn:
        conn.execute(
            sa.text(
                "insert into scrape_runs (id, shop_id, phase, status, started_at, "
                "urls_processed, items_added, items_updated, errors_4xx, errors_5xx, "
                "error_count) values (:id, :shop, 'validate', 'running', now(), "
                "0, 0, 0, 0, 0, 0) on conflict (id) do nothing"
            ),
            {"id": RUN_ID_SENTINEL, "shop": sid},
        )


def snapshot_active(sid: int) -> dict[int, bool]:
    with engine().connect() as conn:
        return {
            row.id: row.is_active
            for row in conn.execute(
                sa.text("select id, is_active from shop_books where shop_id = :s"),
                {"s": sid},
            )
        }


def restore_active(active: dict[int, bool]) -> None:
    """Reset only what the auto-heal changed."""
    with engine().begin() as conn:
        rows = conn.execute(sa.text("select id, is_active from shop_books")).all()
        changed = [
            {"id": r.id, "flag": active[r.id]}
            for r in rows
            if r.id in active and r.is_active != active[r.id]
        ]
        for chunk_start in range(0, len(changed), 1000):
            for row in changed[chunk_start : chunk_start + 1000]:
                conn.execute(
                    sa.text(
                        "update shop_books set is_active = :flag, "
                        "inactive_since = case when :flag then null else inactive_since end "
                        "where id = :id"
                    ),
                    row,
                )
    if changed:
        print(f"  restored is_active on {len(changed)} row(s)")


def clear_issues() -> None:
    with engine().begin() as conn:
        conn.execute(sa.text("delete from validation_issues"))


def findings(sid: int) -> dict:
    """Everything the validator produced, ordered deterministically."""
    with engine().connect() as conn:
        # The linked book is reported by URL, not by id: ids are serials that
        # change every time the fixture is rebuilt, and a golden holding them
        # would fail on the next rebuild for no reason. The URL still asserts
        # the linkage points at the right row.
        issues = [
            dict(row)
            for row in conn.execute(
                sa.text(
                    "select vi.issue, vi.field, vi.url, vi.raw_value, "
                    "sb.url as shop_book_url, vi.lifecycle_state, vi.run_count, "
                    "vi.acknowledged_at is not null as acked "
                    "from validation_issues vi "
                    "left join shop_books sb on sb.id = vi.shop_book_id "
                    "where vi.shop_id = :s "
                    "order by vi.issue, vi.field, sb.url, vi.url"
                ),
                {"s": sid},
            ).mappings()
        ]
        deactivated = [
            row.id
            for row in conn.execute(
                sa.text(
                    "select id from shop_books where shop_id = :s and is_active = false "
                    "order by id"
                ),
                {"s": sid},
            )
        ]

    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue["issue"]] = counts.get(issue["issue"], 0) + 1

    return {
        "counts": dict(sorted(counts.items())),
        "issues": json.loads(json.dumps(issues, default=str)),
        "deactivated_count": len(deactivated),
    }


def run_python(shop: str, sid: int) -> None:
    script = (
        "from book_scraper.db.session import get_session_factory\n"
        "from book_scraper.services.validate import ValidateService\n"
        f"Session = get_session_factory('{TEST_DSN}')\n"
        "with Session() as s:\n"
        f"    counters = ValidateService(s).run({sid}, {RUN_ID_SENTINEL})\n"
        "    s.commit()\n"
        "print(sum(counters.values()), 'issues')\n"
    )
    result = subprocess.run(
        ["uv", "run", "python", "-c", script],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "DATABASE_URL": TEST_DSN},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"python validator failed:\n{result.stderr[-3000:]}")


def run_php(shop: str) -> None:
    result = subprocess.run(
        [PHP, "bin/validate", f"--shop={shop}", f"--run-id={RUN_ID_SENTINEL}"],
        cwd=ROOT / "php" / "crawler",
        env={**os.environ, "DATABASE_URL": TEST_DSN.replace("+psycopg2", "")},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"php validator failed:\n{result.stderr[-3000:]}")


def diff(a: object, b: object, path: str = "") -> list[str]:
    if type(a) is not type(b):
        return [f"{path}: type {type(a).__name__} vs {type(b).__name__}"]
    if isinstance(a, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: extra in php")
            elif key not in b:
                out.append(f"{path}.{key}: MISSING IN PHP")
            else:
                out += diff(a[key], b[key], f"{path}.{key}")
        return out
    if isinstance(a, list):
        out = []
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [f"{path}: python={a!r} php={b!r}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop", default="vaga")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="write the findings as a characterisation golden, if both stacks "
        "agree. Only for --shop synthetic.",
    )
    args = parser.parse_args()

    if args.freeze and args.shop != FREEZABLE_SHOP:
        sys.exit(
            f"refusing to freeze shop '{args.shop}': only '{FREEZABLE_SHOP}' is "
            "reproducible. Copied shops move with the catalogue, so a golden "
            "over one would fail for reasons that are not regressions."
        )

    if args.freeze:
        # Rebuild the fixture so the golden describes a known input rather than
        # whatever the last tool left behind. Owned by PHP because it has to
        # outlive Python.
        built = subprocess.run(
            [PHP, "bin/synthesize-validate-cases", f"--database={php_dsn()}"],
            cwd=ROOT / "php",
            capture_output=True,
            text=True,
        )
        if built.returncode != 0:
            sys.exit(f"could not build the fixture:\n{built.stderr.strip()}")
        print(built.stdout.strip().splitlines()[0])

    sid = shop_id(args.shop)
    ensure_run(sid)
    baseline = snapshot_active(sid)
    print(f"comparing validators on shop '{args.shop}' ({len(baseline)} books)\n")

    clear_issues()
    print("  running python validator…")
    run_python(args.shop, sid)
    python_found = findings(sid)

    restore_active(baseline)
    clear_issues()
    print("  running php validator…")
    run_php(args.shop)
    php_found = findings(sid)

    print()
    keys = sorted(set(python_found["counts"]) | set(php_found["counts"]))
    width = max((len(k) for k in keys), default=10)
    print(f"  {'issue':<{width}}  {'python':>8}  {'php':>8}")
    for key in keys:
        py = python_found["counts"].get(key, 0)
        ph = php_found["counts"].get(key, 0)
        flag = "" if py == ph else "   <-- differs"
        print(f"  {key:<{width}}  {py:>8}  {ph:>8}{flag}")
    print(
        f"  {'TOTAL':<{width}}  {sum(python_found['counts'].values()):>8}  "
        f"{sum(php_found['counts'].values()):>8}"
    )
    print(
        f"\n  auto-healed (deactivated): python {python_found['deactivated_count']}, "
        f"php {php_found['deactivated_count']}"
    )

    differences = diff(python_found, php_found)
    print()
    if differences:
        print(f"{len(differences)} DIFFERENCES")
        shown = differences if args.verbose else differences[:25]
        for line in shown:
            print(f"   {line}")
        if len(differences) > len(shown):
            print(f"   … {len(differences) - len(shown)} more (--verbose)")
    else:
        print("identical — both validators produced the same findings")

    # Leave no findings behind: 13,339 rows for vaga, which the dashboard's
    # issue lists read across all shops, so the next tool sees a database that
    # does not match what it expects. The counts above are the output; the rows
    # were only ever the means of producing them.
    clear_issues()

    # And the sentinel run. It is a fixed id (999000) that outlives every
    # reseed, which made it the NEWEST run in the database and put a
    # half-populated `validate` row at the top of the dashboard's recent-runs
    # list — changing a frozen API shape.
    with engine().begin() as conn:
        conn.execute(
            sa.text("delete from scrape_runs where id = :id"),
            {"id": RUN_ID_SENTINEL},
        )

    if args.freeze:
        if differences:
            print("\nNOT frozen — the golden may only record agreed behaviour.")
        else:
            FREEZE_TO.parent.mkdir(parents=True, exist_ok=True)
            FREEZE_TO.write_text(
                json.dumps(php_found, indent=1, ensure_ascii=False, sort_keys=True)
                + "\n"
            )
            print(
                f"\nfroze {sum(php_found['counts'].values())} findings to {FREEZE_TO}"
            )

    return len(differences)


if __name__ == "__main__":
    sys.exit(main())
