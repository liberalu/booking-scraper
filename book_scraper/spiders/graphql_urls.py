"""Build Magento 2 GraphQL GET URLs for category product pages."""

from urllib.parse import parse_qs, urlencode, urlparse

from book_scraper.config_models import GraphQLConfig

# Marker query param: when present, the URL is a subdivided retry — we
# won't recurse subdivision on it again. Magento ignores unknown query
# params, so passing this through to the backend is harmless.
_SUB_PARAM = "_sub"

# Fields fetched per product on every category page request.
#
# `product_page_attributes` returns rich primary/secondary attribute pairs
# (ISBN, year, pages, publisher, translator, cover type) — verified against
# pegasas.lt at pageSize=10/25/50 with full-payload responses completing in
# 1.4–6.8s and 100% ISBN/year/pages coverage on Lithuanian fiction.
#
# `structured_data` is kept as a fallback because earlier shops relied on
# its JSON-LD payload for rating/review counts and image URLs.
# GraphQL field lists must stay on single lines — splitting inside the
# braces breaks the query syntax. Long lines are intentional.
# fmt: off
# ruff: noqa: E501
_PRODUCT_FIELDS = (
    "name sku url_key "
    "image{url} "
    "price_range{minimum_price{final_price{value currency}regular_price{value currency}}} "
    "stock_status is_book is_audio_book narrator "
    "author{author_label} "
    "anotacija "
    "categories{id name breadcrumbs{category_name}} "
    "product_page_attributes{primary_attributes{label value}secondary_attributes{label value}} "
    "structured_data"
)
# fmt: on


def _format_category_filter(category_ids: list[str]) -> str:
    """Render the Magento `category_id` filter clause.

    A single id renders as `{eq:"X"}` for compatibility with shops that
    indexed legacy single-category configs; a list renders as `{in:[...]}`
    which Magento accepts on any version with the standard ProductFilter
    schema (verified against pegasas.lt).
    """
    if len(category_ids) == 1:
        return f'category_id:{{eq:"{category_ids[0]}"}}'
    quoted = ",".join(f'"{cid}"' for cid in category_ids)
    return f"category_id:{{in:[{quoted}]}}"


def build_graphql_page_url(
    base_url: str,
    conf: GraphQLConfig,
    page: int,
    *,
    page_size_override: int | None = None,
    subdivision_depth: int = 0,
) -> str:
    """Return a Magento 2 GraphQL GET URL for the given page of a category.

    `page_size_override` lets the caller request a smaller pageSize than
    `conf.page_size` — used by the adaptive subdivision path when a
    full-size request returned 5xx. `subdivision_depth` adds a marker
    so the spider knows the URL is already a retry and won't subdivide
    it again.
    """
    page_size = page_size_override if page_size_override is not None else conf.page_size
    filter_clause = _format_category_filter(conf.category_ids)
    query = (
        f"{{products("
        f"filter:{{{filter_clause}}},"
        f"pageSize:{page_size},"
        f"currentPage:{page}"
        f"){{total_count items{{{_PRODUCT_FIELDS}}}}}}}"
    )
    params: list[tuple[str, str]] = [("query", query)]
    if subdivision_depth > 0:
        params.append((_SUB_PARAM, str(subdivision_depth)))
    return base_url.rstrip("/") + "/graphql?" + urlencode(params)


def parse_graphql_page_url(url: str) -> dict[str, int]:
    """Extract page, pageSize, and subdivision_depth from a GraphQL URL.

    Returns ``{"page": ..., "page_size": ..., "subdivision_depth": ...}``.
    Used by the discover spider to know what range a failing request
    covered, so it can compute the right sub-range and detect already-
    subdivided requests.
    """
    qs = parse_qs(urlparse(url).query)
    query_text = qs.get("query", [""])[0]
    page_size = _extract_int(query_text, "pageSize:")
    page = _extract_int(query_text, "currentPage:")
    sub_raw = qs.get(_SUB_PARAM, ["0"])[0]
    try:
        subdivision_depth = int(sub_raw)
    except ValueError:
        subdivision_depth = 0
    return {
        "page": page,
        "page_size": page_size,
        "subdivision_depth": subdivision_depth,
    }


def _extract_int(text: str, marker: str) -> int:
    idx = text.find(marker)
    if idx == -1:
        return 0
    start = idx + len(marker)
    end = start
    while end < len(text) and text[end].isdigit():
        end += 1
    if end == start:
        return 0
    return int(text[start:end])
