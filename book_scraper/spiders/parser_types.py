"""Typed return shapes for the per-shop parser contract.

Discover/scan spiders dispatch into shop-specific parsers via
[book_scraper.spiders.registry] and read the result dict by key. Pinning
the shape with TypedDict gives mypy the reach to catch
key-typo / shape-drift bugs at the seams between generic spiders and
shop modules."""

from typing import Any, TypedDict


class CategoryPageResult(TypedDict):
    """Shape returned by `parse_category_page` and `parse_lupasearch_response`.

    `total` is `None` when the source doesn't expose a reliable count
    (vaga's HTML), in which case the spider falls back to per-page
    chained pagination. When set, the spider enqueues all remaining
    pages from page 1 so `concurrent_requests_per_domain` actually
    engages."""

    products: list[dict[str, Any]]
    total: int | None


class ProductPageResult(TypedDict):
    """Shape returned by `parse_product_page` for both vaga and pegasas.

    Both parsers normalise their respective sources (vaga HTML / pegasas
    GraphQL JSON) to the same flat dict so the scan spider's downstream
    pipeline doesn't need shop-specific branching."""

    title: str | None
    description: str | None
    price: str | None
    price_original: str | None
    in_stock: bool | None
    isbn: str | None
    sku: str | None
    publisher: str | None
    image_url: str | None
    categories: list[str]
    year: int | None
    pages: int | None
    author: str | None
    cover_type: str | None
    format: str | None
    duration: str | None
    narrator: str | None
    translator: str | None
    schema_types: list[str]
    is_book_product: bool
    book_score: int
    book_score_reasons: list[dict[str, object]]
    type: str
    planned_availability_date: str | None
    rating: float | None
    review_count: int | None
