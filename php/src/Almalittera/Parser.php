<?php

declare(strict_types=1);

namespace BookScraper\Almalittera;

use BookScraper\CoverType;
use BookScraper\Vaga\Parser as BookClassifier;

/**
 * Port of book_scraper/spiders/almalittera/parsers.py.
 *
 * Shopify store. Discovery reads the public `/products.json` (rich but no
 * ISBN/year/pages); the product page carries those in a JSON-LD block plus
 * an HTML spec table.
 *
 * The book/non-book classifier is shared with vaga — Python imports
 * `classify_book_product` from the vaga module for the same reason.
 */
final class Parser
{
    private const BASE_URL = 'https://almalittera.lt';

    /**
     * Shopify's vendor value for products with no author — notebooks,
     * stationery, planners. Treated as absent so the classifier can drop them.
     */
    private const PLACEHOLDER_VENDORS = ['nėra autoriaus', 'nera autoriaus'];

    /** Shopify product_type / tag values for non-paper editions. */
    private const EBOOK_MARKERS = ['EPUB'];
    private const AUDIO_TYPES = ['MP3', 'AUDIOBOOK'];

    // --------------------------------------------------------------- sitemap

    /** Discovery uses products.json, not a sitemap. */
    public static function parseSitemapUrls(string $xml): array
    {
        return [];
    }

    // -------------------------------------------------------- category page

    /**
     * A Shopify `/products.json` page.
     *
     * `total` is null: the endpoint exposes no count, so the spider chains
     * page by page exactly as it does for vaga's HTML.
     *
     * @return array{products: list<array<string, mixed>>, total: null}
     */
    public static function parseCategoryPage(string $body): array
    {
        $data = json_decode($body, true);
        $raw = is_array($data) ? ($data['products'] ?? null) : null;
        if (!is_array($raw)) {
            return ['products' => [], 'total' => null];
        }

        $products = [];
        foreach ($raw as $item) {
            if (!is_array($item)) {
                continue;
            }
            $handle = $item['handle'] ?? null;
            if (!is_string($handle) || $handle === '') {
                continue;
            }

            $variants = is_array($item['variants'] ?? null) ? $item['variants'] : [];
            $variant = is_array($variants[0] ?? null) ? $variants[0] : [];

            $tags = self::tagList($item['tags'] ?? null);
            $properties = $tags === [] ? [] : ['shopify_tags' => $tags];

            $products[] = [
                'url' => self::BASE_URL . '/products/' . $handle,
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

    // --------------------------------------------------------- product page

    /**
     * A product page. Two server-rendered sources:
     *
     *  - JSON-LD `Product`: title, description, image, price, availability,
     *    brand (author), gtin13 (= ISBN-13). `offers` is sometimes a list,
     *    one entry per variant; the first is used.
     *  - HTML spec block: ISBN/EAN, SKU, page count, cover type, year,
     *    translator.
     *
     * The page also carries a `BreadcrumbList`, but on this theme it is only
     * `Home → <product name>` — the leaf is the product itself, so it yields
     * no real category and is ignored.
     *
     * @return array<string, mixed>
     */
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
            if (!is_array($ld) || array_is_list($ld)) {
                continue;
            }

            $ldTypes = array_map('strval', (array) ($ld['@type'] ?? []));
            $schemaTypes = [...$schemaTypes, ...$ldTypes];

            if (!in_array('Product', $ldTypes, true) && !in_array('Book', $ldTypes, true)) {
                continue;
            }

            // First value wins throughout: a later block must not overwrite
            // what the canonical Product block already supplied.
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
                $gtin = ($ld['gtin13'] ?? null) ?: ($ld['isbn'] ?? null);
                if (is_string($gtin) && $gtin !== '') {
                    $data['isbn'] = $gtin;
                }
            }
        }

        $specs = self::parseSpecs($html);

        $data['isbn'] ??= ($specs['ISBN kodas'] ?? null) ?: null;
        $data['isbn'] ??= ($specs['EAN kodas'] ?? null) ?: null;
        $data['sku'] ??= ($specs['SKU'] ?? null) ?: null;
        if (isset($specs['Puslapių skaičius'])) {
            $data['pages'] = self::intOrNull($specs['Puslapių skaičius']);
        }
        if (isset($specs['Viršelio tipas'])) {
            $data['cover_type'] = $specs['Viršelio tipas'] ?: null;
        }
        if (isset($specs['Vertėjas'])) {
            $data['translator'] = $specs['Vertėjas'] ?: null;
        }
        if (isset($specs['Leidimo metai'])) {
            $data['year'] = self::yearFromLabel($specs['Leidimo metai']);
        }

        // The title is the only e-book signal on the product page — Shopify's
        // product_type is not rendered here.
        $titleLower = is_string($data['title']) ? mb_strtolower($data['title'], 'UTF-8') : '';
        $isEbook = str_contains($titleLower, 'e.knyga') || str_contains($titleLower, 'epub');

        if ($isEbook) {
            $data['format'] = 'ebook';
        } elseif (is_string($data['cover_type']) && $data['cover_type'] !== '') {
            $data['format'] = CoverType::toFormat($data['cover_type']);
        } elseif ($data['pages'] !== null) {
            $data['format'] = 'book';
        }

        $schemaTypes = array_values(array_unique($schemaTypes));
        sort($schemaTypes);
        $data['schema_types'] = $schemaTypes;

        // Shared with vaga on purpose — the Python module imports the same
        // classifier rather than duplicating the scoring.
        $classification = BookClassifier::classifyBookProduct($data);
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

    // -------------------------------------------------------------- helpers

    /**
     * Label => value pairs from the spec table.
     *
     * @return array<string, string>
     */
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
            . '([^<]+?)\s*<\/span>\s*([^<]*?)<\/p>/us',
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

    /**
     * Map Shopify product_type + tags to our `type`.
     *
     * Everything unrecognised starts as `book`; the scan phase's classifier
     * downgrades notebooks and stationery to non_book.
     */
    public static function bookTypeFromShopify(mixed $productType, mixed $tags): string
    {
        $type = is_string($productType) ? strtoupper(trim($productType)) : '';
        $tagSet = array_map('strtoupper', self::tagList($tags));

        if ($type === 'EPUB' || array_intersect(self::EBOOK_MARKERS, $tagSet) !== []) {
            return 'ebook';
        }
        if (in_array($type, self::AUDIO_TYPES, true) || in_array('MP3', $tagSet, true)) {
            return 'audio';
        }

        return 'book';
    }

    /**
     * Tags arrive as a list from products.json and as a comma-separated
     * string from the per-product endpoint.
     *
     * @return list<string>
     */
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
        if (!is_string($vendor)) {
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

    /** `Leidimo metai` renders as "YYYY MM DD"; only the year is stored. */
    private static function yearFromLabel(string $value): ?int
    {
        return preg_match('/^\s*(\d{4})/', $value, $m) === 1 ? (int) $m[1] : null;
    }

    private static function firstImageSrc(mixed $images): ?string
    {
        if (!is_array($images) || $images === []) {
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
        return ($value === null || $value === '') ? null : (string) $value;
    }

    private static function trimmedOrNull(mixed $value): ?string
    {
        return ($value === null || $value === '') ? null : trim((string) $value);
    }

    private static function intOrNull(string $value): ?int
    {
        return preg_match('/^-?\d+$/', trim($value)) === 1 ? (int) trim($value) : null;
    }
}
