#!/usr/bin/env python
"""Dump the validator's predicate outputs over real catalogue rows.

    PYTHONPATH=. uv run python php/tools/dump_validate_golden.py

These predicates decide which data-quality issues fire. They lean on
Unicode normalisation, Lithuanian diacritics and regexes — exactly where a
PHP port drifts silently — so the corpus is drawn from the live catalogue
(deterministically ordered) rather than hand-written.
"""

import json
import os
import pathlib

import sqlalchemy as sa

from book_scraper.services.validate import (
    _categories_indicate_non_book,
    _is_genuine_url_alias,
    _looks_diacritic_lossy,
    _should_flag_slug_title,
    _title_indicates_non_book,
    _tokenize,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "php" / "tests" / "golden" / "validate_predicates.json"
DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper"
)

# Hand-picked cases pinning the documented behaviours, kept alongside the
# sampled rows so the corpus still covers them if the catalogue changes.
EXTRA_SLUG_TITLE = [
    ("kale-du-pu-ga-2196148", "Kalėdų pūga"),          # buggy generator
    ("kaledu-puga", "Kalėdų pūga"),                     # correct transliteration
    ("sidhartha2", "Sidhartha"),                        # WooCommerce dedup digit
    ("kaledu-puga-2-as-leidimas", "Kalėdų pūga"),       # extra text, not lossy
    ("kaledu-puga", "Kalėdų pūga…"),                    # truncated title
    ("as-del-to", "Aš dėl to"),                         # short particles
    ("visiskai-kitas-dalykas", "Kalėdų pūga"),          # genuine mismatch
    ("e-knyga-menulio-geles", "„Mėnulio“ gėlės"),       # LT typography
]

EXTRA_ALIASES = [
    ("https://vaga.lt/misku-x", "https://vaga.lt/mi%C5%A1ku-x"),
    ("https://vaga.lt/a", "https://vaga.lt/index.php?route=product/product&product_id=5"),
    ("https://vaga.lt/a", "https://vaga.lt/index.php?route=product%2Fproduct&product_id=5"),
    ("https://vaga.lt/a", "https://vaga.lt/a/"),
    ("https://vaga.lt/a", "https://vaga.lt/a?search=x"),
    ("https://vaga.lt/a", "https://vaga.lt/b"),
]


def sample() -> tuple[list, list]:
    """Deterministic slices of the catalogue: md5 ordering, not random()."""
    try:
        engine = sa.create_engine(DB_URL)
        with engine.connect() as conn:
            books = [
                (r.url, r.title, list(r.categories or []))
                for r in conn.execute(
                    sa.text(
                        "select url, title, categories from shop_books "
                        "where title is not null order by md5(url) limit 400"
                    )
                )
            ]
            # Rows whose titles carry diacritics exercise the lossy path.
            books += [
                (r.url, r.title, list(r.categories or []))
                for r in conn.execute(
                    sa.text(
                        "select url, title, categories from shop_books "
                        "where title ~ '[ąčęėįšųūžĄČĘĖĮŠŲŪŽ]' "
                        "order by md5(url) limit 400"
                    )
                )
            ]
        engine.dispose()
        return books, []
    except Exception as exc:  # noqa: BLE001 — sample is a bonus
        print(f"skipping catalogue sample: {exc}")
        return [], []


def main() -> None:
    books, _ = sample()

    slug_title = []
    seen = set()
    for url, title, _cats in books:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        key = (slug, title)
        if key in seen:
            continue
        seen.add(key)
        slug_title.append(key)
    for pair in EXTRA_SLUG_TITLE:
        if pair not in seen:
            slug_title.append(pair)

    out = {
        "tokenize": [
            {"input": value, "tokens": sorted(_tokenize(value))}
            for value in sorted({t for _u, t, _c in books} | {t for _s, t in EXTRA_SLUG_TITLE})
        ],
        "slug_title": [
            {
                "slug": slug,
                "title": title,
                "should_flag": _should_flag_slug_title(slug, title),
                "diacritic_lossy": _looks_diacritic_lossy(slug, title),
            }
            for slug, title in slug_title
        ],
        "non_book_title": [
            {"title": title, "result": _title_indicates_non_book(title)}
            for title in sorted({t for _u, t, _c in books})
        ],
        "non_book_categories": [
            {"categories": cats, "result": _categories_indicate_non_book(cats)}
            for cats in sorted(
                {tuple(c) for _u, _t, c in books if c}, key=lambda t: json.dumps(t)
            )
        ],
        "url_alias": [
            {"canon": canon, "alias": alias, "genuine": _is_genuine_url_alias(canon, alias)}
            for canon, alias in EXTRA_ALIASES
        ],
    }
    # tuples -> lists for stable JSON
    out["non_book_categories"] = [
        {"categories": list(row["categories"]), "result": row["result"]}
        for row in out["non_book_categories"]
    ]

    GOLDEN.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    counts = {k: len(v) for k, v in out.items()}
    print(f"wrote {GOLDEN.relative_to(ROOT)}: {counts}")
    flagged = sum(1 for r in out["slug_title"] if r["should_flag"])
    lossy = sum(1 for r in out["slug_title"] if r["diacritic_lossy"])
    print(f"  slug_title: {flagged} would flag, {lossy} diacritic-lossy")


if __name__ == "__main__":
    main()
