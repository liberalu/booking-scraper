"""URL/body helpers for the LupaSearch JSON discovery strategy.

LupaSearch is a POST endpoint with a JSON body, but our DB-backed queue
stores URLs only. To keep the queue schema unchanged we encode all
request inputs (offset, limit, category_ids) into the URL's query string
and reconstruct the JSON body at request-build time. The seed URL goes
through the same path as the next-page URLs, so resume after a crash
works without special cases.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from book_scraper.config_models import LupaSearchConfig

# The site's own UI uses these defaults; replicating them keeps the
# returned ordering predictable so resumed runs see the same items in
# the same positions.
_DEFAULT_SORT: list[dict[str, str]] = [
    {"in_stock": "desc"},
    {"in_store_only": "desc"},
    {"profit": "desc"},
    {"sku": "desc"},
]


def build_lupasearch_seed_url(conf: LupaSearchConfig) -> str:
    """Synthetic URL carrying offset/limit/category_ids in the query string.

    Example: ``https://api.lupasearch.com/v1/query/abc?offset=0&limit=42&category_ids=5107%2C7352``
    """
    params: list[tuple[str, str]] = [
        ("offset", "0"),
        ("limit", str(conf.page_size)),
        ("category_ids", ",".join(conf.category_ids)),
    ]
    if conf.extra_filters:
        # Sorted to keep URLs deterministic across runs.
        for key in sorted(conf.extra_filters.keys()):
            params.append((f"f.{key}", ",".join(conf.extra_filters[key])))
    return conf.endpoint + "?" + urlencode(params)


def parse_lupasearch_url_offsets(url: str) -> tuple[int, int]:
    """Return (offset, limit) parsed from a LupaSearch synthetic URL."""
    qs = parse_qs(urlparse(url).query)
    offset = int(qs.get("offset", ["0"])[0])
    limit = int(qs.get("limit", ["42"])[0])
    return offset, limit


def advance_lupasearch_url(url: str, new_offset: int) -> str:
    """Return the same URL with `offset` replaced."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    qs["offset"] = [str(new_offset)]
    # Flatten back to (k, v) pairs preserving original key order.
    flat: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for key in ("offset", "limit", "category_ids"):
        if key in qs:
            flat.append((key, qs[key][0]))
            seen_keys.add(key)
    for key, values in qs.items():
        if key in seen_keys:
            continue
        for value in values:
            flat.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(flat)))


def build_lupasearch_post_request_kwargs(url: str) -> dict[str, Any]:
    """Reconstruct the POST body + headers from a synthetic LupaSearch URL.

    Returned as kwargs for ``scrapy.Request`` (``method``, ``body``,
    ``headers``). The query string is the source of truth so that a
    resumed run rebuilds the exact same request the original run sent.
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    offset = int(qs.get("offset", ["0"])[0])
    limit = int(qs.get("limit", ["42"])[0])
    category_ids_raw = qs.get("category_ids", [""])[0]
    category_ids = [c for c in category_ids_raw.split(",") if c]

    filters: dict[str, list[str]] = {"category_ids": category_ids}
    for key, values in qs.items():
        if not key.startswith("f."):
            continue
        filter_name = key[2:]
        flat: list[str] = []
        for value in values:
            flat.extend(part for part in value.split(",") if part)
        if flat:
            filters[filter_name] = flat

    body_obj = {
        "searchText": "",
        "offset": offset,
        "limit": limit,
        "sort": _DEFAULT_SORT,
        "filters": filters,
    }
    body = json.dumps(body_obj, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.pegasas.lt",
        "Referer": "https://www.pegasas.lt/",
    }
    return {"method": "POST", "body": body, "headers": headers}
