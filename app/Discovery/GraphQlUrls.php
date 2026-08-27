<?php

declare(strict_types=1);

namespace App\Discovery;

/**
 * Magento 2 GraphQL GET URLs for category product pages.
 *
 * The whole query travels in the query string, so a queued URL is a complete
 * request — that is what lets a crashed run resume from the database without
 * storing method/body/headers anywhere.
 */
final class GraphQlUrls
{
    /**
     * Marker for a subdivided retry. Magento ignores unknown query params, so
     * carrying it to the backend is harmless — and it stops the spider from
     * subdividing an already-subdivided request forever.
     */
    private const SUB_PARAM = '_sub';

    /**
     * Fields fetched per product. Must stay on one line each: a newline inside
     * the braces is a syntax error in the GraphQL query.
     */
    private const PRODUCT_FIELDS = 'name sku url_key '
        . 'image{url} '
        . 'price_range{minimum_price{final_price{value currency}regular_price{value currency}}} '
        . 'stock_status is_book is_audio_book narrator '
        . 'author{author_label} '
        . 'anotacija '
        . 'categories{id name breadcrumbs{category_name}} '
        . 'product_page_attributes{primary_attributes{label value}secondary_attributes{label value}} '
        . 'structured_data';

    /**
     * @param list<string> $categoryIds
     */
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

        return rtrim($baseUrl, '/') . '/graphql?' . http_build_query($params);
    }

    /**
     * page, pageSize and subdivision depth read back off a built URL.
     *
     * The spider needs to know which range a failing request covered before it
     * can split that range into smaller ones.
     *
     * @return array{page: int, page_size: int, subdivision_depth: int}
     */
    public static function parsePageUrl(string $url): array
    {
        $params = QueryString::parse($url);
        $text = (string) ($params['query'] ?? '');

        return [
            'page' => self::intAfter($text, 'currentPage:'),
            'page_size' => self::intAfter($text, 'pageSize:'),
            'subdivision_depth' => (int) ($params[self::SUB_PARAM] ?? 0),
        ];
    }

    /**
     * A single id renders as `{eq:"X"}` — shops with a legacy single-category
     * config indexed that form; a list renders as `{in:[…]}`.
     *
     * @param list<string> $categoryIds
     */
    private static function categoryFilter(array $categoryIds): string
    {
        if (count($categoryIds) === 1) {
            return 'category_id:{eq:"' . $categoryIds[0] . '"}';
        }
        $quoted = implode(',', array_map(static fn (string $id): string => '"' . $id . '"', $categoryIds));

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
            if (!ctype_digit($text[$i])) {
                break;
            }
            $digits .= $text[$i];
        }

        return $digits === '' ? 0 : (int) $digits;
    }
}
