<?php

declare(strict_types=1);

namespace App\Discovery;

final class GraphQlUrls
{
    private const SUB_PARAM = '_sub';

    private const PRODUCT_FIELDS = 'name sku url_key '
        .'image{url} '
        .'price_range{minimum_price{final_price{value currency}regular_price{value currency}}} '
        .'stock_status is_book is_audio_book narrator '
        .'author{author_label} '
        .'anotacija '
        .'categories{id name breadcrumbs{category_name}} '
        .'product_page_attributes{primary_attributes{label value}secondary_attributes{label value}} '
        .'structured_data';

    /** @param list<string> $categoryIds */
    public static function buildPageUrl(
        string $baseUrl,
        array $categoryIds,
        int $pageSize,
        int $page,
        int $subdivisionDepth = 0,
    ): string {
        $query = sprintf(
            '{products(filter:{%s},pageSize:%d,currentPage:%d){total_count items{%s}}}',
            self::categoryFilter($categoryIds),
            $pageSize,
            $page,
            self::PRODUCT_FIELDS
        );
        $params = ['query' => $query];
        if ($subdivisionDepth > 0) {
            $params[self::SUB_PARAM] = (string) $subdivisionDepth;
        }

        return rtrim($baseUrl, '/').'/graphql?'.http_build_query($params);
    }

    /** @return array{page: int, page_size: int, subdivision_depth: int} */
    public static function parsePageUrl(string $url): array
    {
        $params = QueryString::parse($url);
        $text = $params['query'] ?? '';

        return [
            'page' => self::intAfter($text, 'currentPage:'),
            'page_size' => self::intAfter($text, 'pageSize:'),
            'subdivision_depth' => (int) ($params[self::SUB_PARAM] ?? 0),
        ];
    }

    /** @param list<string> $categoryIds */
    private static function categoryFilter(array $categoryIds): string
    {
        if (count($categoryIds) === 1) {
            return 'category_id:{eq:"'.$categoryIds[0].'"}';
        }
        $quoted = implode(',', array_map(static fn (string $id): string => '"'.$id.'"', $categoryIds));

        return "category_id:{in:[{$quoted}]}";
    }

    private static function intAfter(string $text, string $marker): int
    {
        $index = strpos($text, $marker);
        if ($index === false) {
            return 0;
        }
        $digits = '';
        for ($i = $index + strlen($marker); $i < strlen($text); $i++) {
            if (! ctype_digit($text[$i])) {
                break;
            }
            $digits .= $text[$i];
        }

        return $digits === '' ? 0 : (int) $digits;
    }
}
