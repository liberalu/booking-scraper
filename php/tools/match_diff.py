#!/usr/bin/env python
"""Run both matchers over identical data and compare the resulting linkage.

    PYTHONPATH=. uv run python php/tools/match_diff.py --shop vaga
    PYTHONPATH=. uv run python php/tools/match_diff.py --shop vaga --synthesis

Test database only. Matching MUTATES data (it writes book_id, match_status,
match_method and canonical_author_id), so the affected columns are
snapshotted and restored between the two passes.

--freeze writes the linkage as a characterisation golden, and only accepts
--shop synthetic. A copied real shop's linkage is not reproducible: it depends
on which canonicals the copy happens to carry. The synthetic shop is built from
nothing by php/src/Testing/SyntheticShop.php, which owns the canonical its
books link to and refuses to build if any of its ISBNs already belongs to
something else.
"""
import argparse, json, os, subprocess, sys
from pathlib import Path
import sqlalchemy as sa

# The test database is named in one place — see _testdb for why the PHP
# side cannot share the Python suite's database.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _testdb import TEST_DSN, php_dsn  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PHP = "/opt/homebrew/opt/php@8.4/bin/php"
FREEZE_TO = ROOT / "php" / "tests" / "golden" / "match_linkage.json"
#: The only shop whose linkage is reproducible — see the module docstring.
FREEZABLE_SHOP = "synthetic"


def engine():
    return sa.create_engine(TEST_DSN)


def snapshot_state():
    with engine().connect() as c:
        books = {r.id: (r.book_id, r.match_status, r.match_method)
                 for r in c.execute(sa.text(
                     "select id, book_id, match_status, match_method from shop_books"))}
        authors = {r.id: r.canonical_author_id
                   for r in c.execute(sa.text(
                       "select id, canonical_author_id from shop_authors"))}
        max_book = c.execute(sa.text("select coalesce(max(id),0) from books")).scalar()
    return books, authors, max_book


def restore(books, authors, max_book):
    with engine().begin() as c:
        # Synthesised books first: shop_books.book_id references them.
        c.execute(sa.text("delete from book_isbns where book_id > :m"), {"m": max_book})
        c.execute(sa.text("update shop_books set book_id = null where book_id > :m"), {"m": max_book})
        c.execute(sa.text("delete from books where id > :m"), {"m": max_book})
        for sid, (book_id, status, method) in books.items():
            c.execute(sa.text(
                "update shop_books set book_id=:b, match_status=:s, match_method=:m "
                "where id=:i and (book_id, match_status, match_method) is distinct from (:b,:s,:m)"),
                {"b": book_id, "s": status, "m": method, "i": sid})
        for aid, canon in authors.items():
            c.execute(sa.text(
                "update shop_authors set canonical_author_id=:c where id=:i "
                "and canonical_author_id is distinct from :c"), {"c": canon, "i": aid})


def result_state(shop, max_book):
    """Everything the matcher can have changed.

    Synthesised books are compared by CONTENT, not just count: the winning
    title/year/format comes from the highest-trust shop while the publisher
    is sticky to the first writer, and those two tiebreaks are exactly where
    a port drifts without the row count moving.
    """
    with engine().connect() as c:
        rows = [dict(r) for r in c.execute(sa.text(
            "select sb.url, sb.book_id is not null as linked, sb.match_status, sb.match_method "
            "from shop_books sb join shops s on s.id=sb.shop_id where s.name=:s order by sb.url"),
            {"s": shop}).mappings()]
        # Keyed on the author name, since ids differ between passes. Scoped to
        # THIS shop: shop_authors carries no shop of its own, so an unscoped
        # query returned every shop's links — which meant the copied
        # catalogue's authors ended up in a golden that is supposed to describe
        # a fixture.
        authors = [dict(r) for r in c.execute(sa.text(
            "select distinct sa.name, a.name as canonical_name from shop_authors sa "
            "join authors a on a.id = sa.canonical_author_id "
            "join shop_book_authors sba on sba.author_id = sa.id "
            "join shop_books sb on sb.id = sba.shop_book_id "
            "join shops s on s.id = sb.shop_id where s.name = :s "
            "order by sa.name, a.name"), {"s": shop}).mappings()]
        # Keyed on ISBN: the synthesised books' ids differ between passes.
        synthesised = [dict(r) for r in c.execute(sa.text(
            "select bi.isbn, b.title, b.year, b.type, b.format, p.name as publisher "
            "from books b join book_isbns bi on bi.book_id = b.id "
            "left join publishers p on p.id = b.publisher_id "
            "where b.id > :m order by bi.isbn"), {"m": max_book}).mappings()]
    return {
        "shop_books": rows,
        "author_links": authors,
        "synthesised": synthesised,
    }


def run_python(shop, synthesis):
    script = (
        "from book_scraper.db.session import get_session_factory\n"
        "from book_scraper.services.match import MatchService\n"
        f"S = get_session_factory('{TEST_DSN}')\n"
        "with S() as s:\n"
        f"    c = MatchService(s).run('{shop}')\n"
        "    s.commit()\n"
        "print(c)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), "DATABASE_URL": TEST_DSN,
           "MATCH_SYNTHESIS_ENABLED": "1" if synthesis else "0"}
    r = subprocess.run(["uv", "run", "python", "-c", script], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    if r.returncode: sys.exit(f"python matcher failed:\n{r.stderr[-2500:]}")
    return r.stdout.strip()


def run_php(shop, synthesis):
    script = (
        '<?php require "%s/php/crawler/vendor/autoload.php";\n'
        'BookScraper\\Database::boot("%s");\n'
        'print_r((new BookScraper\\Services\\MatchService())->run("%s", %s));\n'
        % (ROOT, TEST_DSN.replace("+psycopg2", ""), shop, "true" if synthesis else "false")
    )
    f = ROOT / "php" / "crawler" / "_match_tmp.php"
    f.write_text(script)
    try:
        r = subprocess.run([PHP, str(f)], cwd=ROOT / "php" / "crawler",
                           capture_output=True, text=True)
        if r.returncode: sys.exit(f"php matcher failed:\n{r.stderr[-2500:]}")
        return r.stdout.strip()
    finally:
        f.unlink(missing_ok=True)


def diff(a, b, path=""):
    if type(a) is not type(b):
        return [f"{path}: type {type(a).__name__} vs {type(b).__name__}"]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a: out.append(f"{path}.{k}: extra in php")
            elif k not in b: out.append(f"{path}.{k}: MISSING IN PHP")
            else: out += diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list):
        out = []
        if len(a) != len(b): out.append(f"{path}: length {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)): out += diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [f"{path}: python={a!r} php={b!r}"]


def unlink(shop):
    """Clear the linkage so the matchers have real work.

    Without this the seeded catalogue is already fully matched and BOTH
    matchers do nothing — an identical result that proves nothing.
    """
    with engine().begin() as c:
        c.execute(sa.text(
            "update shop_books set book_id = null, match_status = 'unmatched', "
            "match_method = null where shop_id in (select id from shops where name = :s)"),
            {"s": shop})
        c.execute(sa.text("update shop_authors set canonical_author_id = null"))
        n = c.execute(sa.text(
            "select count(*) from shop_books sb join shops s on s.id = sb.shop_id "
            "where s.name = :s and sb.isbn is not null"), {"s": shop}).scalar()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default="vaga")
    ap.add_argument("--synthesis", action="store_true")
    ap.add_argument("--freeze", action="store_true",
                    help="write the linkage as a characterisation golden, if both "
                         "matchers agree. Only for --shop synthetic.")
    args = ap.parse_args()

    if args.freeze and args.shop != FREEZABLE_SHOP:
        sys.exit(
            f"refusing to freeze shop '{args.shop}': only '{FREEZABLE_SHOP}' is "
            "reproducible. A copied shop's linkage depends on which canonicals "
            "the copy carries."
        )
    if args.freeze and args.synthesis:
        sys.exit(
            "refusing to freeze a synthesis run: step 3 creates canonicals, so "
            "the second run of the same fixture has nothing left to synthesise "
            "and the golden would not replay."
        )

    if args.freeze:
        # Rebuild the fixture so the golden describes a known input rather than
        # whatever the last tool left behind. Owned by PHP because it has to
        # outlive Python.
        built = subprocess.run(
            [PHP, "bin/synthesize-validate-cases", f"--database={php_dsn()}"],
            cwd=ROOT / "php", capture_output=True, text=True)
        if built.returncode != 0:
            sys.exit(f"could not build the fixture:\n{built.stderr.strip()}")
        print(built.stdout.strip().splitlines()[0])

    if args.shop == FREEZABLE_SHOP:
        # The synthetic fixture is built in the state the matcher should act on
        # — one book unmatched with an ISBN whose canonical exists, one already
        # linked to a canonical that disagrees. Unlinking would erase the
        # second, and the replay test would have to reproduce a preparation
        # step that belongs to this tool rather than to the matcher.
        pending = 0
        print("  fixture shop: taken as built, not unlinked\n")
    else:
        pending = unlink(args.shop)
        print(f"  unlinked: {pending} shop_books with an ISBN now await matching\n")
    baseline = snapshot_state()
    print(f"comparing matchers on '{args.shop}' (synthesis={'on' if args.synthesis else 'off'})\n")

    max_book = baseline[2]

    restore(*baseline)
    print("  python:", run_python(args.shop, args.synthesis))
    py = result_state(args.shop, max_book)

    restore(*baseline)
    print("  php:   ", run_php(args.shop, args.synthesis))
    ph = result_state(args.shop, max_book)

    for name, state in (("python", py), ("php", ph)):
        print(f"  {name:<7} {sum(1 for r in state['shop_books'] if r['linked']):>6} linked  "
              f"{len(state['author_links']):>5} author links  "
              f"{len(state['synthesised']):>4} synthesised")

    # Guard against a vacuous pass. A previous run's side effects become the
    # next run's baseline, so synthesis silently has nothing left to do —
    # reseed to restore the work.
    if args.synthesis and not py["synthesised"] and not ph["synthesised"]:
        print(
            "\nINCONCLUSIVE — neither matcher synthesised anything, so step 3 was\n"
            "  not exercised. Every unmatched ISBN already has a canonical book,\n"
            "  most likely from an earlier run of this tool. Reseed first:\n"
            f"    PYTHONPATH=. uv run python php/tools/seed_test_db.py --shop {args.shop}"
        )
        return 1
    if not py["shop_books"] or all(not r["linked"] for r in py["shop_books"]):
        print(
            "\nINCONCLUSIVE — nothing was linked, so step 1 was not exercised.\n"
            f"  Seed the shop first: php/tools/seed_test_db.py --shop {args.shop}"
        )
        return 1

    # Put the linkage back. Matching rewrites book_id, match_status,
    # match_method and canonical_author_id across the whole shop; left as the
    # PHP pass wrote it, the next tool or test sees a catalogue that has been
    # re-matched, which moved /api/books?has_conflicts=true and failed a frozen
    # shape two packages away.
    restore(*baseline)
    print("  restored the linkage this tool found\n")

    d = diff(py, ph)
    print()
    if d:
        print(f"{len(d)} DIFFERENCES")
        for line in d[:20]: print("  ", line)
    else:
        print("identical — both matchers produced the same linkage")

    if args.freeze:
        if d:
            print("\nNOT frozen — the golden may only record agreed behaviour.")
        else:
            FREEZE_TO.parent.mkdir(parents=True, exist_ok=True)
            FREEZE_TO.write_text(
                json.dumps(ph, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
            print(f"\nfroze the linkage of {len(ph['shop_books'])} book(s) to {FREEZE_TO}")

    return len(d)


if __name__ == "__main__":
    sys.exit(main())
