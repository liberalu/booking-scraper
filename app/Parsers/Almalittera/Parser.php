<?php

declare(strict_types=1);

namespace App\Parsers\Almalittera;

use App\Books\BookClassifier;
use App\Crawler\CrawlerTypes;
use App\Parsers\DiscoveryParser;
use App\Parsers\ProductParser;
use App\Support\CoverType;

/** @phpstan-import-type ParsedItem from CrawlerTypes */
final class Parser implements DiscoveryParser, ProductParser
{
    private const BASE_URL = 'https://almalittera.lt';

    private const PLACEHOLDER_VENDORS = ['nėra autoriaus', 'nera autoriaus'];

    private const EBOOK_MARKERS = ['EPUB'];

    private const AUDIO_TYPES = ['MP3', 'AUDIOBOOK'];

    /** @return list<string> */
    public static function parseSitemapUrls(string $xml, ?callable $fetchChild = null): array
    {
        return [];
    }

    /** @return array{products: list<ParsedItem>, total: int|null} */
    public static function parseCategoryPage(string $body): array
    {
        $data = json_decode($body, true);
        $raw = is_array($data) ? ($data['products'] ?? null) : null;
        if (! is_array($raw)) {
            return ['products' => [], 'total' => null];
        }

        $products = [];
        foreach ($raw as $item) {
            if (! is_array($item)) {
                continue;
            }
            $handle = $item['handle'] ?? null;
            if (! is_string($handle) || $handle === '') {
                continue;
            }

            $variants = is_array($item['variants'] ?? null) ? $item['variants'] : [];
            $variant = is_array($variants[0] ?? null) ? $variants[0] : [];

            $tags = self::tagList($item['tags'] ?? null);
            $properties = $tags === [] ? [] : ['shopify_tags' => $tags];

            $products[] = [
                'url' => self::BASE_URL.'/products/'.$handle,
                'title' => self::unescape($item['title'] ?? null),
                'author' => self::vendorToAuthor($item['vendor'] ?? null),
                'price' => self::stringOrNull($variant['price'] ?? null),
                'price_original' => self::stringOrNull($variant['compare_at_price'] ?? null),
                'in_stock' => (bool) ($variant['available'] ?? false),
                'sku' => self::trimmedOrNull($variant['sku'] ?? null),
                'image_url' => self::firstImageSrc($item['images'] ?? null),
                'type' => self::bookTypeFromShopify($item['product_type'] ?? null, $item['tags'] ?? null),
                'categories' => [],
                'properties' => $properties === [] ? null : $properties,
            ];
        }

        return ['products' => $products, 'total' => null];
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

        $schemaTypes = [];
        preg_match_all(
            '/<script type="application\/ld\+json">\s*(.*?)\s*<\/script>/us',
            $html,
            $blocks
        );

        foreach ($blocks[1] as $block) {
            $cleaned = preg_replace('/[\x00-\x1f]+/', ' ', trim($block)) ?? '';
            $ld = json_decode($cleaned, true);
            if (! is_array($ld) || array_is_list($ld)) {
                continue;
            }

            $ldTypes = self::stringList($ld['@type'] ?? null);
            $schemaTypes = [...$schemaTypes, ...$ldTypes];

            if (! in_array('Product', $ldTypes, true) && ! in_array('Book', $ldTypes, true)) {
                continue;
            }

            $data['title'] ??= self::unescape($ld['name'] ?? null);
            $data['description'] ??= self::unescape($ld['description'] ?? null);

            $brand = $ld['brand'] ?? null;
            if (is_array($brand) && $data['author'] === null) {
                $data['author'] = self::vendorToAuthor($brand['name'] ?? null);
            }

            if ($data['image_url'] === null) {
                $image = $ld['image'] ?? null;
                if (is_string($image)) {
                    $data['image_url'] = $image;
                } elseif (is_array($image) && is_string($image[0] ?? null)) {
                    $data['image_url'] = $image[0];
                }
            }

            $offersRaw = $ld['offers'] ?? null;
            $offer = [];
            if (is_array($offersRaw)) {
                $offer = array_is_list($offersRaw)
                    ? (is_array($offersRaw[0] ?? null) ? $offersRaw[0] : [])
                    : $offersRaw;
            }
            if ($offer !== []) {
                $data['price'] ??= self::stringOrNull($offer['price'] ?? null);
                if ($data['in_stock'] === null && is_string($offer['availability'] ?? null)) {
                    $data['in_stock'] = str_contains($offer['availability'], 'InStock');
                }
                if ($data['sku'] === null && is_string($offer['sku'] ?? null) && $offer['sku'] !== '') {
                    $data['sku'] = $offer['sku'];
                }
            }

            if ($data['isbn'] === null) {
                $gtin = self::stringOrNull($ld['gtin13'] ?? null)
                    ?? self::stringOrNull($ld['isbn'] ?? null);
                if ($gtin !== null) {
                    $data['isbn'] = $gtin;
                }
            }
        }

        $specs = self::parseSpecs($html);

        $data['isbn'] ??= self::stringOrNull($specs['ISBN kodas'] ?? null);
        $data['isbn'] ??= self::stringOrNull($specs['EAN kodas'] ?? null);
        $data['sku'] ??= self::stringOrNull($specs['SKU'] ?? null);
        if (isset($specs['Puslapių skaičius'])) {
            $data['pages'] = self::intOrNull($specs['Puslapių skaičius']);
        }
        if (isset($specs['Viršelio tipas'])) {
            $data['cover_type'] = self::stringOrNull($specs['Viršelio tipas']);
        }
        if (isset($specs['Vertėjas'])) {
            $data['translator'] = self::stringOrNull($specs['Vertėjas']);
        }
        if (isset($specs['Leidimo metai'])) {
            $data['year'] = self::yearFromLabel($specs['Leidimo metai']);
        }

        $titleLower = is_string($data['title']) ? mb_strtolower($data['title'], 'UTF-8') : '';
        $isEbook = str_contains($titleLower, 'e.knyga') || str_contains($titleLower, 'epub');

        if ($isEbook) {
            $data['format'] = 'ebook';
        } elseif (is_string($data['cover_type'])) {
            $data['format'] = CoverType::toFormat($data['cover_type']);
        } elseif ($data['pages'] !== null) {
            $data['format'] = 'book';
        }

        $schemaTypes = array_values(array_unique($schemaTypes));
        sort($schemaTypes);
        $data['schema_types'] = $schemaTypes;

        $classification = BookClassifier::classify($data);
        $data['is_book_product'] = $classification['is_book_product'];
        $data['book_score'] = $classification['score'];
        $data['book_score_reasons'] = $classification['reasons'];

        if ($isEbook && $classification['is_book_product']) {
            $data['type'] = 'ebook';
        } elseif ($classification['is_book_product']) {
            $data['type'] = 'book';
        } else {
            $data['type'] = 'non_book';
        }

        return $data;
    }

    /** @return array<string, string> */
    private static function parseSpecs(string $html): array
    {
        if (preg_match(
            '/<div[^>]*class="[^"]*product-full-width__description-specs[^"]*"[^>]*>(.*?)<\/div>/us',
            $html,
            $block
        ) !== 1) {
            return [];
        }

        preg_match_all(
            '/<span class="product-full-width__description-specs-name">\s*'
            .'([^<]+?)\s*<\/span>\s*([^<]*?)<\/p>/us',
            $block[1],
            $pairs,
            PREG_SET_ORDER
        );

        $specs = [];
        foreach ($pairs as $pair) {
            $label = trim(rtrim(trim($pair[1]), ':'));
            $specs[$label] = trim(html_entity_decode($pair[2], ENT_QUOTES | ENT_HTML5, 'UTF-8'));
        }

        return $specs;
    }

    public static function bookTypeFromShopify(mixed $productType, mixed $tags): string
    {
        $type = is_string($productType) ? strtoupper(trim($productType)) : '';
        $tagSet = array_map(static fn (string $tag): string => strtoupper($tag), self::tagList($tags));

        if ($type === 'EPUB' || array_intersect(self::EBOOK_MARKERS, $tagSet) !== []) {
            return 'ebook';
        }
        if (in_array($type, self::AUDIO_TYPES, true) || in_array('MP3', $tagSet, true)) {
            return 'audio';
        }

        return 'book';
    }

    /** @return list<string> */
    private static function tagList(mixed $tags): array
    {
        if (is_array($tags)) {
            $items = array_filter($tags, 'is_string');
        } elseif (is_string($tags) && $tags !== '') {
            $items = array_map('trim', explode(',', $tags));
        } else {
            return [];
        }

        return array_values(array_filter($items, static fn (string $t): bool => $t !== ''));
    }

    public static function vendorToAuthor(mixed $vendor): ?string
    {
        if (! is_string($vendor)) {
            return null;
        }
        $cleaned = trim($vendor);
        if ($cleaned === '') {
            return null;
        }

        return in_array(mb_strtolower($cleaned, 'UTF-8'), self::PLACEHOLDER_VENDORS, true)
            ? null
            : $cleaned;
    }

    private static function yearFromLabel(string $value): ?int
    {
        return preg_match('/^\s*(\d{4})/', $value, $m) === 1 ? (int) $m[1] : null;
    }

    private static function firstImageSrc(mixed $images): ?string
    {
        if (! is_array($images) || $images === []) {
            return null;
        }
        $first = $images[0] ?? null;

        return is_array($first) && is_string($first['src'] ?? null) ? $first['src'] : null;
    }

    private static function unescape(mixed $value): mixed
    {
        return is_string($value)
            ? html_entity_decode($value, ENT_QUOTES | ENT_HTML5, 'UTF-8')
            : $value;
    }

    private static function stringOrNull(mixed $value): ?string
    {
        if (is_string($value)) {
            return $value === '' ? null : $value;
        }

        return is_int($value) || is_float($value) ? (string) $value : null;
    }

    private static function trimmedOrNull(mixed $value): ?string
    {
        $string = self::stringOrNull($value);

        return $string === null ? null : trim($string);
    }

    private static function intOrNull(string $value): ?int
    {
        return preg_match('/^-?\d+$/', trim($value)) === 1 ? (int) trim($value) : null;
    }

    /** @return list<string> */
    private static function stringList(mixed $value): array
    {
        if (is_string($value)) {
            return [$value];
        }
        if (! is_array($value)) {
            return [];
        }

        return array_values(array_filter($value, is_string(...)));
    }
}
