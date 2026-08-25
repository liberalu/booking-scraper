#!/usr/bin/env python
"""Dump the URLs and POST bodies the Python discovery helpers produce.

    PYTHONPATH=. uv run python php/tools/dump_discovery_golden.py

The three JSON-API strategies (Magento GraphQL, LupaSearch, ibiblioteka)
encode every request input into a synthetic URL so the queue can store them
as plain strings. That makes them exactly comparable: same inputs in, same
URL and body out, or the port is wrong. Written to
php/tests/golden/discovery_urls.json and asserted by DiscoveryUrlsTest.
"""
from __future__ import annotations

import json
from pathlib import Path

from book_scraper.config_models import (
    GraphQLConfig,
    IbibliotekaApiConfig,
    LupaSearchConfig,
)
from book_scraper.spiders.graphql_urls import (
    build_graphql_page_url,
    parse_graphql_page_url,
)
from book_scraper.spiders.ibiblioteka_api_urls import (
    advance_ibiblioteka_url,
    build_ibiblioteka_post_request_kwargs,
    build_ibiblioteka_seed_urls,
    parse_ibiblioteka_url_params,
)
from book_scraper.spiders.lupasearch_urls import (
    advance_lupasearch_url,
    build_lupasearch_post_request_kwargs,
    build_lupasearch_seed_url,
    parse_lupasearch_url_offsets,
)

OUT = Path(__file__).resolve().parents[1] / "tests" / "golden" / "discovery_urls.json"


def kwargs_to_json(kwargs: dict) -> dict:
    return {
        "method": kwargs["method"],
        "body": kwargs["body"].decode("utf-8"),
        "headers": kwargs["headers"],
    }


def main() -> None:
    cases: dict[str, object] = {}

    # ── Magento GraphQL ────────────────────────────────────────────────
    graphql_cases = []
    for label, ids, page_size, page, override, depth in (
        ("multi_category_page1", ["5107", "5125", "6122"], 50, 1, None, 0),
        ("multi_category_page7", ["5107", "5125", "6122"], 50, 7, None, 0),
        ("single_category", ["5107"], 25, 3, None, 0),
        ("subdivided", ["5107", "5125"], 50, 4, 10, 1),
        ("page_size_one", ["5107"], 1, 9900, None, 0),
    ):
        conf = GraphQLConfig(
            url="https://www.pegasas.lt/graphql",
            category_ids=ids,
            page_size=page_size,
        )
        url = build_graphql_page_url(
            "https://www.pegasas.lt/",
            conf,
            page=page,
            page_size_override=override,
            subdivision_depth=depth,
        )
        graphql_cases.append({
            "label": label,
            "base_url": "https://www.pegasas.lt/",
            "category_ids": ids,
            "page_size": override if override is not None else page_size,
            "page": page,
            "subdivision_depth": depth,
            "url": url,
            "parsed": parse_graphql_page_url(url),
        })
    cases["graphql"] = graphql_cases

    # ── LupaSearch ─────────────────────────────────────────────────────
    lupa_cases = []
    for label, endpoint, ids, page_size, extra in (
        ("plain", "https://api.lupasearch.com/v1/query/pegasas", ["5107", "7352"], 42, {}),
        ("single_category", "https://api.lupasearch.com/v1/query/pegasas", ["5107"], 100, {}),
        (
            "with_filters",
            "https://api.lupasearch.com/v1/query/pegasas",
            ["5107", "5125"],
            42,
            {"publisher": ["Alma littera", "Baltos lankos"], "in_stock": ["1"]},
        ),
    ):
        conf = LupaSearchConfig(
            endpoint=endpoint,
            category_ids=ids,
            page_size=page_size,
            extra_filters=extra,
        )
        seed = build_lupasearch_seed_url(conf)
        advanced = advance_lupasearch_url(seed, page_size * 3)
        lupa_cases.append({
            "label": label,
            "endpoint": endpoint,
            "category_ids": ids,
            "page_size": page_size,
            "extra_filters": extra,
            "seed_url": seed,
            "offsets": list(parse_lupasearch_url_offsets(seed)),
            "advanced_url": advanced,
            "advanced_offsets": list(parse_lupasearch_url_offsets(advanced)),
            "seed_request": kwargs_to_json(build_lupasearch_post_request_kwargs(seed)),
            "advanced_request": kwargs_to_json(
                build_lupasearch_post_request_kwargs(advanced)
            ),
        })
    cases["lupasearch"] = lupa_cases

    # ── ibiblioteka ────────────────────────────────────────────────────
    ibib_cases = []
    for label, year_from, year_to, page_size in (
        ("one_year", 2024, 2025, 100),
        ("three_years", 2022, 2025, 500),
        ("year_boundary", 2019, 2021, 10),
    ):
        conf = IbibliotekaApiConfig(
            year_from=year_from, year_to=year_to, page_size=page_size
        )
        seeds = build_ibiblioteka_seed_urls(conf)
        advanced = advance_ibiblioteka_url(seeds[0], page_size * 2)
        legacy = (
            "https://ibiblioteka.lt/metis-api/bibliographic-records/public/"
            f"detailed-search/page?psi=300&ps={page_size}&yf={year_from}&yt={year_to}"
        )
        ibib_cases.append({
            "label": label,
            "year_from": year_from,
            "year_to": year_to,
            "page_size": page_size,
            "seed_urls": seeds,
            "params": list(parse_ibiblioteka_url_params(seeds[0])),
            "advanced_url": advanced,
            "advanced_params": list(parse_ibiblioteka_url_params(advanced)),
            "seed_request": kwargs_to_json(
                build_ibiblioteka_post_request_kwargs(seeds[0])
            ),
            "legacy_url": legacy,
            "legacy_params": list(parse_ibiblioteka_url_params(legacy)),
            "legacy_advanced": advance_ibiblioteka_url(legacy, 400),
            "legacy_request": kwargs_to_json(
                build_ibiblioteka_post_request_kwargs(legacy)
            ),
        })
    cases["ibiblioteka_api"] = ibib_cases

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")
    total = sum(len(v) for v in cases.values())  # type: ignore[arg-type]
    print(f"wrote {total} cases to {OUT}")


if __name__ == "__main__":
    main()
