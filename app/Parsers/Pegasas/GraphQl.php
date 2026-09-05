<?php

declare(strict_types=1);

namespace App\Parsers\Pegasas;

final class GraphQl
{
    public const string PRODUCT_FIELDS = 'name sku url_key '
        .'image{url} '
        .'price_range{minimum_price{final_price{value currency}regular_price{value currency}}} '
        .'stock_status is_book is_audio_book narrator '
        .'author{author_label} '
        .'anotacija '
        .'categories{id name breadcrumbs{category_name}} '
        .'product_page_attributes{primary_attributes{label value}secondary_attributes{label value}} '
        .'structured_data';
}
