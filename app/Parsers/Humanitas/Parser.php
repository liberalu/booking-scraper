<?php

declare(strict_types=1);

namespace App\Parsers\Humanitas;

use App\Books\BookClassifier;
use App\Crawler\CrawlerTypes;
use App\Parsers\DiscoveryParser;
use App\Parsers\ProductParser;
use App\Support\CoverType;
use App\Support\Isbn;

/** @phpstan-import-type ParsedItem from CrawlerTypes */
final class Parser implements DiscoveryParser, ProductParser
{
    private const string BASE_URL = 'https://www.humanitas.lt';

    private const string PRODUCT_ANCHOR = '/<a\b(?=[^>]*\bclass="[^"]*\bbook-item\b[^"]*")[^>]*\bhref="([^"]+)"/i';

    private const string CARD_OPENING = '/<a\b(?=[^>]*\bclass="[^"]*\bbook-item\b[^"]*")[^>]*\bhref="([^"]+)"[^>]*>/si';

    private const string LANG_LITHUANIAN = 'Lietuvių';

    private const string TITLE_SUFFIX = '/\s*-\s*Humanitas\s*$/i';

    private const string BOOK_INFO_BLOCK = '/<div\s+class="book-info">(.*?)<\/div>/si';

    private const string BOOK_INFO_ROW = '/<b>\s*([^<]+?)\s*:?\s*<\/b>\s*([^<]+?)\s*(?:<br|<b>|<\/div>)/si';

    private const string PRICE = '/([\d ]+[.,]\d+)\s*€/u';

    private const string SCRIPT_BLOCK = '/<script\b.*?<\/script>/si';

    private const string OOS_PRICE_HIDDEN = '/<div\s+class="cart-price\s+price-hidden\b/i';

    private const string OOS_CART_DISABLED = '/<a\b[^>]*\bclass="[^"]*\bext_button\b[^"]*\bdisabled\b/i';

    private const string CART_PRICE_BLOCK_OPEN = '/<div\s+class="cart-price[^"]*"[^>]*>/i';

    private const string PRICE_CONTAINER = '/<div\s+class="price-container"/i';

    private const string CARD_TITLE = '/<div\s+class="title"[^>]*>\s*([^<]+?)\s*<\/div>/i';

    private const string CARD_AUTHOR = '/<div\s+class="author"[^>]*>\s*([^<]+?)\s*<\/div>/i';

    private const string CARD_PRICE_PAIR = '/<div\s+class="price-container"[^>]*>\s*'
        .'<div\s+class="discount"[^>]*>\s*([^<]+?)\s*<\/div>\s*'
        .'<div\s+class="price"[^>]*>\s*([^<]+?)\s*<\/div>/si';

    private const string CARD_SINGLE_PRICE = '/<div\s+class="price"[^>]*>\s*([\d ]+[.,]\d+\s*€)\s*<\/div>/i';

    private const string CARD_IMG = '/<img\s[^>]*\bsrc="([^"]+)"/i';

    private const int CART_PRICE_WINDOW = 600;

    /** @return list<string> */
    public static function parseSitemapUrls(string $html, ?callable $fetchChild = null): array
    {
        preg_match_all(self::PRODUCT_ANCHOR, $html, $matches);

        $out = [];
        foreach ($matches[1] as $raw) {
            $url = self::canonicalProductUrl($raw);
            if ($url !== null) {
                $out[] = $url;
            }
        }

        return $out;
    }

    /** @return array{products: list<ParsedItem>, total: int|null} */
    public static function parseCategoryPage(string $html): array
    {
        preg_match_all(self::CARD_OPENING, $html, $openings, PREG_OFFSET_CAPTURE | PREG_SET_ORDER);

        $products = [];
        $seen = [];
        $count = count($openings);

        for ($i = 0; $i < $count; $i++) {
            $opening = $openings[$i];
            $bodyStart = $opening[0][1] + strlen($opening[0][0]);
            $bodyEnd = $i + 1 < $count ? $openings[$i + 1][0][1] : strlen($html);

            $product = self::parseCard(
                $opening[1][0],
                substr($html, $bodyStart, $bodyEnd - $bodyStart)
            );
            if ($product === null || isset($seen[$product['url']])) {
                continue;
            }
            $seen[$product['url']] = true;
            $products[] = $product;
        }

        return ['products' => $products, 'total' => null];
    }

    /**
     * @return array{
     *     url: string,
     *     title?: string|null,
     *     author?: string|null,
     *     price?: string|null,
     *     price_original?: string|null,
     *     image_url?: string|null,
     *     in_stock?: bool
     * }|null
     */
    private static function parseCard(string $href, string $body): ?array
    {
        $url = self::canonicalProductUrl($href);
        if ($url === null) {
            return null;
        }

        $title = preg_match(self::CARD_TITLE, $body, $m) === 1 ? self::unescape($m[1]) : null;
        if ($title === null) {

            return ['url' => $url];
        }

        $price = null;
        $priceOriginal = null;
        if (preg_match(self::CARD_PRICE_PAIR, $body, $pair) === 1) {
            $price = self::parsePrice($pair[1]);
            $priceOriginal = self::parsePrice($pair[2]);
        } elseif (preg_match(self::CARD_SINGLE_PRICE, $body, $single) === 1) {

            $price = self::parsePrice($single[1]);
        }

        return [
            'url' => $url,
            'title' => $title,
            'author' => preg_match(self::CARD_AUTHOR, $body, $a) === 1 ? self::unescape($a[1]) : null,
            'price' => $price,
            'price_original' => $priceOriginal,
            'image_url' => preg_match(self::CARD_IMG, $body, $img) === 1 ? $img[1] : null,

            'in_stock' => true,
        ];
    }

    /** @return ParsedItem */
    public static function parseProductPage(string $html): array
    {
        $data = [
            'title' => null, 'description' => null, 'price' => null,
            'price_original' => null, 'in_stock' => null, 'isbn' => null,
            'sku' => null, 'publisher' => null, 'image_url' => null,
            'categories' => [], 'year' => null, 'pages' => null,
            'author' => null, 'cover_type' => null, 'format' => null,
            'duration' => null, 'narrator' => null, 'translator' => null,
            'schema_types' => [], 'is_book_product' => false, 'book_score' => 0,
            'book_score_reasons' => [], 'type' => 'book',
            'planned_availability_date' => null, 'rating' => null,
            'review_count' => null,
        ];

        $ogTitle = self::metaContent($html, 'og:title');
        $rawTitle = preg_match('/<title>([^<]*)<\/title>/si', $html, $t) === 1
            ? self::unescape($t[1])
            : null;
        $data['title'] = $ogTitle
            ?? ($rawTitle !== null ? preg_replace(self::TITLE_SUFFIX, '', $rawTitle) : null);

        $description = self::metaContent($html, 'og:description');
        if ($description !== null) {
            $data['description'] = $description;
        }
        $image = self::metaContent($html, 'og:image');
        if ($image !== null) {
            $data['image_url'] = $image;
        }

        if (preg_match('/data-product-id="([^"]+)"/', $html, $sku) === 1) {
            $data['sku'] = $sku[1];
        }

        [$price, $priceOriginal, $inStock] = self::extractPricePair($html);
        $data['price'] = $price;
        $data['price_original'] = $priceOriginal;
        $data['in_stock'] = $inStock;

        $properties = [];
        $info = self::extractBookInfo($html);

        if ($info !== []) {
            if (($info['ISBN'] ?? '') !== '') {

                $isbn = Isbn::normalize($info['ISBN']);
                if (Isbn::isValid($isbn)) {
                    $data['isbn'] = $isbn;
                }
            }
            $data['author'] = $info['Autorius'] ?? $data['author'];
            $data['publisher'] = $info['Leidėjas'] ?? $info['Leidykla'] ?? $data['publisher'];
            $data['year'] = self::intOrNull($info['Leidimo metai'] ?? null);
            $data['pages'] = self::intOrNull($info['Puslapių skaičius'] ?? null);
            $data['translator'] = $info['Vertėjas'] ?? $data['translator'];

            $cover = $info['Formatas'] ?? null;
            if ($cover !== null) {
                $looksLikeDimensions = preg_match('/^\s*\d+(?:[.,]\d+)?\s*[xX×]\s*\d+/u', $cover) === 1;
                $isPlaceholder = mb_strtolower(trim($cover), 'UTF-8') === 'pasirinkite';

                if (! $looksLikeDimensions && ! $isPlaceholder) {
                    $data['cover_type'] = $cover;
                    $data['format'] = CoverType::toFormat($cover);
                } elseif ($looksLikeDimensions) {

                    $properties['dimensions'] = $cover;
                }
            }
            if (isset($info['Matmenys'])) {
                $properties['dimensions'] = $info['Matmenys'];
            }
            if (($info['Leidinio kalba'] ?? '') !== '') {
                $properties['language'] = $info['Leidinio kalba'];
            }
        }

        if ($properties !== []) {
            $data['properties'] = $properties;
        }

        $classification = BookClassifier::classify($data);
        $data['is_book_product'] = $classification['is_book_product'];
        $data['book_score'] = $classification['score'];
        $data['book_score_reasons'] = $classification['reasons'];
        $data['type'] = BookClassifier::inferType($data);

        $language = $properties['language'] ?? null;
        if (is_string($language) && trim($language) !== ''
            && trim($language) !== self::LANG_LITHUANIAN) {
            $data['is_book_product'] = false;
            $data['book_score_reasons'][] = [
                'key' => 'blocked_non_lt_language',
                'points' => 0,
                'language' => trim($language),
            ];
        }

        return $data;
    }

    /** @return list<array{url: string}> */
    public static function parseIndexPage(string $html): array
    {
        return array_map(
            static fn (string $url): array => ['url' => $url],
            self::parseSitemapUrls($html)
        );
    }

    /** @return array{string|null, string|null, bool} */
    private static function extractPricePair(string $html): array
    {
        $section = preg_match(
            '/<div\s+class="cart-container"[^>]*>(.*?)<\/div>\s*<\/div>\s*<\/div>/si',
            $html,
            $cart
        ) === 1 ? $cart[0] : $html;

        $price = null;
        $priceOriginal = null;

        if (preg_match(
            '/<div\s+class="price-container">.*?<div\s+class="discount">'
            .'\s*([^<]+)<\/div>\s*<div\s+class="price">\s*([^<]+)<\/div>/si',
            $section,
            $final
        ) === 1) {
            $price = self::parsePrice($final[1]);
            $priceOriginal = self::parsePrice($final[2]);
        }

        if ($price === null) {

            if (preg_match(
                '/<div\s+class="cart-price".*?(?:<div\s+class="label">[^<]*<\/div>)?'
                .'\s*([\d ]+[.,]\d+\s*€)/si',
                $section,
                $single
            ) === 1) {
                $price = self::parsePrice($single[1]);
            }
        }

        if ($priceOriginal === null) {
            if (preg_match(
                '/<div\s+class="full-price"[^>]*>.*?<div\s+class="label">[^<]*<\/div>'
                .'\s*([\d ]+[.,]\d+\s*€)/si',
                $html,
                $full
            ) === 1) {
                $priceOriginal = self::parsePrice($full[1]);
            }
        }

        $price ??= $priceOriginal;

        $visible = preg_replace(self::SCRIPT_BLOCK, '', $html) ?? $html;
        $inStock = ! (
            preg_match(self::OOS_PRICE_HIDDEN, $visible) === 1
            || preg_match(self::OOS_CART_DISABLED, $visible) === 1
            || self::cartPriceBlockIsEmpty($visible)
        );

        return [$price, $priceOriginal, $inStock];
    }

    private static function cartPriceBlockIsEmpty(string $html): bool
    {
        if (preg_match(self::CART_PRICE_BLOCK_OPEN, $html, $m, PREG_OFFSET_CAPTURE) !== 1) {
            return false;
        }
        $window = substr(
            $html,
            $m[0][1] + strlen($m[0][0]),
            self::CART_PRICE_WINDOW
        );

        return preg_match(self::PRICE_CONTAINER, $window) !== 1
            && preg_match(self::PRICE, $window) !== 1;
    }

    /** @return array<string, string> */
    private static function extractBookInfo(string $html): array
    {
        if (preg_match(self::BOOK_INFO_BLOCK, $html, $block) !== 1) {
            return [];
        }
        preg_match_all(self::BOOK_INFO_ROW, $block[1], $rows, PREG_SET_ORDER);

        $out = [];
        foreach ($rows as $row) {
            $label = trim(rtrim(trim(self::unescape($row[1]) ?? ''), ':'));
            $value = self::unescape($row[2]);
            if ($label !== '' && $value !== null) {
                $out[$label] = $value;
            }
        }

        return $out;
    }

    private static function canonicalProductUrl(string $href): ?string
    {
        $clean = rtrim(trim(explode('#', explode('?', $href, 2)[0], 2)[0]), '/');
        if ($clean === '') {
            return null;
        }
        if (str_starts_with($clean, '//')) {
            $clean = 'https:'.$clean;
        } elseif (str_starts_with($clean, '/')) {
            $clean = self::BASE_URL.$clean;
        }

        return str_starts_with($clean, self::BASE_URL.'/produktas/') ? $clean : null;
    }

    private static function metaContent(string $html, string $property): ?string
    {
        $pattern = sprintf(
            '/<meta[^>]+property=["\']%s["\'][^>]+content=["\']([^"\']*)["\']/i',
            preg_quote($property, '/')
        );

        return preg_match($pattern, $html, $m) === 1 ? self::unescape($m[1]) : null;
    }

    private static function parsePrice(?string $raw): ?string
    {
        if ($raw === null || preg_match(self::PRICE, $raw, $m) !== 1) {
            return null;
        }
        $value = str_replace([' ', ','], ['', '.'], $m[1]);

        return $value === '' ? null : $value;
    }

    private static function unescape(?string $value): ?string
    {
        if ($value === null) {
            return null;
        }
        $cleaned = html_entity_decode($value, ENT_QUOTES | ENT_HTML5, 'UTF-8');
        $cleaned = trim(preg_replace('/\s+/u', ' ', $cleaned) ?? $cleaned);

        return $cleaned === '' ? null : $cleaned;
    }

    private static function intOrNull(?string $value): ?int
    {
        if ($value === null) {
            return null;
        }
        $trimmed = trim($value);

        return preg_match('/^-?\d+$/', $trimmed) === 1 ? (int) $trimmed : null;
    }
}
