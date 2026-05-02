"""Build Magento 2 GraphQL GET URLs for category product pages."""

from urllib.parse import urlencode

from book_scraper.config_models import GraphQLConfig

# Fields fetched per product on every category page request.
# structured_data (JSON-LD) is included for isbn/publisher/numberOfPages;
# however Magento only populates those fields in structured_data when
# product_page_attributes is also requested — and that field causes
# server-side timeouts on bulk (100-item) pages, so it is omitted here.
# isbn/publisher/pages are therefore not populated during discovery and
# would require a separate per-product scan if needed.
_PRODUCT_FIELDS = (
    "name sku url_key "
    "image{url} "
    "price_range{minimum_price{final_price{value currency}regular_price{value currency}}} "
    "stock_status is_book is_audio_book narrator "
    "author{author_label} "
    "anotacija "
    "categories{name breadcrumbs{category_name}}"
)


def build_graphql_page_url(base_url: str, conf: GraphQLConfig, page: int) -> str:
    """Return a Magento 2 GraphQL GET URL for the given page of a category."""
    query = (
        f"{{products("
        f"filter:{{category_id:{{eq:\"{conf.category_id}\"}}}},"
        f"pageSize:{conf.page_size},"
        f"currentPage:{page}"
        f"){{total_count items{{{_PRODUCT_FIELDS}}}}}}}"
    )
    return base_url.rstrip("/") + "/graphql?" + urlencode({"query": query})
