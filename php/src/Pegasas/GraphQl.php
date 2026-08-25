<?php

declare(strict_types=1);

namespace BookScraper\Pegasas;

/**
 * Magento GraphQL query fragments, ported from
 * book_scraper/spiders/graphql_urls.py.
 */
final class GraphQl
{
    /**
     * Fields requested for every product. Must stay in sync with the Python
     * constant: the parser reads exactly these keys, so dropping one here
     * silently nulls that column.
     */
    public const PRODUCT_FIELDS = 'name sku url_key '
        . 'image{url} '
        . 'price_range{minimum_price{final_price{value currency}regular_price{value currency}}} '
        . 'stock_status is_book is_audio_book narrator '
        . 'author{author_label} '
        . 'anotacija '
        . 'categories{id name breadcrumbs{category_name}} '
        . 'product_page_attributes{primary_attributes{label value}secondary_attributes{label value}} '
        . 'structured_data';
}
