<?php

declare(strict_types=1);

namespace App\Parsers\Pegasas;

use App\Crawler\CrawlerTypes;
use App\Parsers\DiscoveryParser;
use App\Parsers\LupaSearchParser;
use App\Parsers\ProductParser;
use App\Parsers\ScanUrlRewriter;
use App\Support\CoverType;
use App\Support\Isbn;
use Illuminate\Support\Str;
use Normalizer;

/**
 * @phpstan-import-type ParsedItem from CrawlerTypes
 *
 * @phpstan-type ParsedProduct array{
 *     url: string,
 *     title: string|null,
 *     author: string|null,
 *     sku: string|null,
 *     isbn: string|null,
 *     publisher: string|null,
 *     year: int|null,
 *     format: string|null,
 *     description: string|null,
 *     image_url: string|null,
 *     price: string|null,
 *     price_original: string|null,
 *     in_stock: bool,
 *     type: string,
 *     categories: list<string>,
 *     properties: array<string, mixed>|null
 * }
 */
final class Parser implements DiscoveryParser, LupaSearchParser, ProductParser, ScanUrlRewriter
{
    private const string BASE_URL = 'https://www.pegasas.lt';

    private const string SKU_FROM_SLUG = '/-(\d+)\/?$/';

    private const int MAGENTO_SKU_WIDTH = 18;

    private const string LABEL_PUBLISHER = 'Leidykla';

    private const string LABEL_TRANSLATOR = 'Vertėjas';

    private const string LABEL_YEAR = 'Leidimo metai';

    private const string LABEL_COVER = 'Viršelio tipas';

    private const string LABEL_PAGES = 'Puslapių skaičius';

    private const string LABEL_ISBN = 'ISBN kodas';

    private const string LABEL_EAN = 'EAN kodas';

    private const string LABEL_LANGUAGE = 'Leidinio kalba';

    private const string LABEL_DIMENSIONS = 'Matmenys';

    private const string LABEL_ORIGINAL_TITLE = 'Pav. originalo kalba';

    private const string LABEL_COLOR = 'Spalvingumas';

    private const string LANG_LITHUANIAN = 'Lietuvių';

    private const array ENGLISH_CATEGORY_IDS = [8128];

    private const array EBOOK_CATEGORY_IDS = [6122];

    private const array BOOK_CATEGORY_SUBSTRINGS = ['knyg', 'groz', 'literat', 'vadovel', 'pratyb'];

    private const array EMPTY_MARKERS = ['-', '—'];

    /** @return list<string> */
    public static function parseSitemapUrls(string $xml, ?callable $fetchChild = null): array
    {
        return [];
    }

    /** @return array{products: list<ParsedItem>, total: int|null} */
    public static function parseCategoryPage(string $body): array
    {
        $data = json_decode($body, true);
        if (! is_array($data)) {
            return ['products' => [], 'total' => null];
        }

        $dataNode = self::map($data['data'] ?? null);
        $node = self::map($dataNode['products'] ?? null);
        $items = self::listOfMaps($node['items'] ?? null);
        $total = self::integer($node['total_count'] ?? null);

        $products = [];
        foreach ($items as $item) {
            if (! is_string($item['url_key'] ?? null) || $item['url_key'] === '') {
                continue;
            }
            $product = self::graphqlItemToProduct($item);
            if ($product !== null) {
                $products[] = $product;
            }
        }

        return ['products' => $products, 'total' => $total];
    }

    /** @return array{products: list<ParsedItem>, total: int|null} */
    public static function parseLupasearchResponse(string $body): array
    {
        $data = json_decode($body, true);
        if (! is_array($data)) {
            return ['products' => [], 'total' => 0];
        }

        $products = [];
        foreach (self::listOfMaps($data['items'] ?? null) as $item) {
            $product = self::lupasearchItemToProduct($item);
            if ($product !== null) {
                $products[] = $product;
            }
        }

        return ['products' => $products, 'total' => self::integer($data['total'] ?? null) ?? 0];
    }

    /** @return ParsedItem */
    public static function parseProductPage(string $body): array
    {
        $data = json_decode($body, true);
        if (! is_array($data)) {
            return self::emptyProductPage('pwa_shell_no_data');
        }

        $dataNode = self::map($data['data'] ?? null);
        $productsNode = self::map($dataNode['products'] ?? null);
        $items = self::listOfMaps($productsNode['items'] ?? null);
        if ($items === []) {
            return self::emptyProductPage('graphql_no_match');
        }

        $product = self::graphqlItemToProduct($items[0]);
        if ($product === null) {

            return self::emptyProductPage('graphql_non_lt_filtered');
        }

        $properties = $product['properties'] ?? [];

        return [
            'title' => $product['title'],
            'description' => $product['description'],
            'price' => $product['price'],
            'price_original' => $product['price_original'],
            'in_stock' => $product['in_stock'],
            'isbn' => $product['isbn'],
            'sku' => $product['sku'],
            'publisher' => $product['publisher'],
            'image_url' => $product['image_url'],
            'categories' => $product['categories'],
            'year' => $product['year'],
            'pages' => $properties['pages'] ?? null,
            'author' => $product['author'],
            'cover_type' => $properties['cover_type'] ?? null,
            'format' => $product['format'],
            'duration' => $properties['duration'] ?? null,
            'narrator' => $properties['narrator'] ?? null,
            'translator' => $properties['translator'] ?? null,
            'schema_types' => [],
            'is_book_product' => in_array($product['type'], ['book', 'audio', 'ebook'], true),
            'book_score' => 100,
            'book_score_reasons' => [['key' => 'graphql_sku_match', 'points' => 100]],
            'type' => $product['type'] === '' ? 'non_book' : $product['type'],
            'planned_availability_date' => null,
            'rating' => null,
            'review_count' => null,
        ];
    }

    /** @return array{url: string, headers: array<string, string>}|null */
    public static function rewriteScanUrl(string $url): ?array
    {
        $parts = parse_url($url);
        $path = rtrim($parts['path'] ?? '', '/');
        if (preg_match(self::SKU_FROM_SLUG, $path, $m) !== 1) {
            return null;
        }

        $sku = str_pad($m[1], self::MAGENTO_SKU_WIDTH, '0', STR_PAD_LEFT);
        $query = '{products('
            .sprintf('filter:{sku:{eq:"%s"}},', $sku)
            .'pageSize:1,currentPage:1'
            .'){items{'.GraphQl::PRODUCT_FIELDS.'}}}';

        $base = ($parts['scheme'] ?? 'https').'://'.($parts['host'] ?? '');

        return [
            'url' => $base.'/graphql?'.http_build_query(['query' => $query]),
            'headers' => ['Accept' => 'application/json'],
        ];
    }

    public static function deriveBookType(
        mixed $isBook,
        mixed $isAudioBook,
        mixed $isEbook = null,
        bool $hasBookCategory = false,
    ): string {
        if (self::truthy($isAudioBook)) {
            return 'audio';
        }
        if (self::truthy($isEbook)) {
            return 'ebook';
        }
        if (self::truthy($isBook)) {
            return 'book';
        }

        return $hasBookCategory ? 'book' : 'non_book';
    }

    /** @param list<string>|null $categories */
    public static function categoriesIndicateBook(?array $categories): bool
    {
        foreach ($categories ?? [] as $category) {
            $folded = self::foldAscii($category);
            foreach (self::BOOK_CATEGORY_SUBSTRINGS as $needle) {
                if (str_contains($folded, $needle)) {
                    return true;
                }
            }
        }

        return false;
    }

    /**
     * @param  array<string, mixed>  $item
     * @return ParsedProduct|null
     */
    private static function graphqlItemToProduct(array $item): ?array
    {
        $urlKey = $item['url_key'] ?? null;
        if (! is_string($urlKey) || $urlKey === '') {
            return null;
        }
        $canonicalUrl = self::BASE_URL.'/'.$urlKey;

        $priceRange = self::map($item['price_range'] ?? null);
        $minimum = self::map($priceRange['minimum_price'] ?? null);
        $final = self::map($minimum['final_price'] ?? null);
        $regular = self::map($minimum['regular_price'] ?? null);
        $price = isset($final['value']) ? self::numberToString($final['value']) : null;
        $priceOriginal = null;
        if (isset($regular['value']) && ($regular['value'] !== ($final['value'] ?? null))) {
            $priceOriginal = self::numberToString($regular['value']);
        }

        $authorLabels = [];
        foreach (is_array($item['author'] ?? null) ? $item['author'] : [] as $author) {
            $label = is_array($author) ? ($author['author_label'] ?? null) : null;
            if (is_string($label) && $label !== '') {
                $authorLabels[] = $label;
            }
        }
        $authorStr = $authorLabels === [] ? null : implode(', ', $authorLabels);

        $narrators = array_values(array_filter(
            is_array($item['narrator'] ?? null) ? $item['narrator'] : [],
            static fn (mixed $n): bool => is_string($n) && $n !== ''
        ));
        $narratorStr = $narrators === [] ? null : implode(', ', $narrators);

        $categoryNames = [];
        $categoryIds = [];
        foreach (is_array($item['categories'] ?? null) ? $item['categories'] : [] as $category) {
            if (! is_array($category)) {
                continue;
            }
            $name = $category['name'] ?? null;
            if (is_string($name) && $name !== '' && ! in_array($name, $categoryNames, true)) {
                $categoryNames[] = $name;
            }
            $id = $category['id'] ?? null;
            if (is_int($id) && ! in_array($id, $categoryIds, true)) {
                $categoryIds[] = $id;
            }
        }

        $isEbook = array_intersect($categoryIds, self::EBOOK_CATEGORY_IDS) !== [];
        $bookType = self::deriveBookType(
            $item['is_book'] ?? null,
            $item['is_audio_book'] ?? null,
            $isEbook,
            self::categoriesIndicateBook($categoryNames),
        );

        $labels = self::attrsToLabels($item['product_page_attributes'] ?? null);

        $isbn = null;
        $ean = null;
        $publisher = null;
        $pages = null;
        $year = null;
        $coverType = null;
        $translator = null;
        $language = null;
        $dimensions = null;
        $originalTitle = null;
        $color = null;

        if ($labels !== []) {

            $langRaw = self::clean($labels[self::LABEL_LANGUAGE] ?? null);
            if ($langRaw !== null && $langRaw !== self::LANG_LITHUANIAN) {
                return null;
            }

            [$isbn, $ean] = self::resolveIsbnAndEan(
                self::clean($labels[self::LABEL_ISBN] ?? null),
                self::clean($labels[self::LABEL_EAN] ?? null),
            );

            $publisher = self::clean($labels[self::LABEL_PUBLISHER] ?? null);
            $pages = self::parseInt($labels[self::LABEL_PAGES] ?? null);
            $year = self::parseYear($labels[self::LABEL_YEAR] ?? null);
            $coverType = self::clean($labels[self::LABEL_COVER] ?? null);
            $translator = self::clean($labels[self::LABEL_TRANSLATOR] ?? null);
            $language = self::clean($labels[self::LABEL_LANGUAGE] ?? null);
            $dimensions = self::clean($labels[self::LABEL_DIMENSIONS] ?? null);
            $originalTitle = self::clean($labels[self::LABEL_ORIGINAL_TITLE] ?? null);
            $color = self::clean($labels[self::LABEL_COLOR] ?? null);
        }

        if (($isbn === null || $publisher === null || $pages === null || $year === null)
            && is_string($item['structured_data'] ?? null)) {
            $structured = json_decode($item['structured_data'], true);
            $main = is_array($structured) ? ($structured['mainEntity'] ?? []) : [];
            if (is_array($main)) {
                $isbn ??= self::coerceIsbn($main['isbn'] ?? null);
                if ($publisher === null) {
                    $pub = $main['publisher'] ?? null;
                    if (is_array($pub)) {
                        $publisher = self::clean($pub['name'] ?? null);
                    } elseif (is_string($pub)) {
                        $publisher = $pub === '' ? null : $pub;
                    }
                }
                $pages ??= self::parseInt($main['numberOfPages'] ?? null);
                $year ??= self::parseYear($main['datePublished'] ?? null);
            }
        }

        $properties = [];

        if ($pages !== null && $bookType !== 'audio') {
            $properties['pages'] = $pages;
        }
        foreach ([
            'narrator' => $narratorStr,
            'cover_type' => $coverType,
            'translator' => $translator,
            'language' => $language,
            'dimensions' => $dimensions,
            'original_title' => $originalTitle,
            'color' => $color,
            'ean' => $ean,
        ] as $key => $value) {
            if ($value !== null && $value !== '') {
                $properties[$key] = $value;
            }
        }

        return [
            'url' => $canonicalUrl,
            'title' => self::clean($item['name'] ?? null),
            'author' => $authorStr,
            'sku' => self::clean($item['sku'] ?? null),
            'isbn' => $isbn,
            'publisher' => $publisher,
            'year' => $year,
            'format' => self::formatFromBookType($bookType, $coverType),
            'description' => self::flattenAnotacija($item['anotacija'] ?? null),
            'image_url' => self::clean(self::map($item['image'] ?? null)['url'] ?? null),
            'price' => $price,
            'price_original' => $priceOriginal,
            'in_stock' => ($item['stock_status'] ?? null) === 'IN_STOCK',
            'type' => $bookType,
            'categories' => $categoryNames,
            'properties' => $properties === [] ? null : $properties,
        ];
    }

    /**
     * @param  array<string, mixed>  $item
     * @return ParsedProduct|null
     */
    private static function lupasearchItemToProduct(array $item): ?array
    {

        $rawIds = is_array($item['category_ids'] ?? null) ? $item['category_ids'] : [];
        foreach ($rawIds as $id) {
            $categoryId = self::integer($id);
            if ($categoryId !== null && in_array($categoryId, self::ENGLISH_CATEGORY_IDS, true)) {
                return null;
            }
        }

        $price = isset($item['price']) ? self::numberToString($item['price']) : null;
        $priceOriginal = null;
        $regularPrice = self::number($item['regular_price'] ?? null);
        $finalPrice = self::number($price);
        if ($regularPrice !== null && $finalPrice !== null && $regularPrice !== $finalPrice) {
            $priceOriginal = self::numberToString($item['regular_price']);
        }

        $authors = array_values(array_filter(
            is_array($item['autorius'] ?? null) ? $item['autorius'] : [],
            static fn (mixed $a): bool => is_string($a) && $a !== ''
        ));
        $authorStr = $authors === [] ? null : implode(', ', $authors);

        $publisher = self::clean($item['leidykla'] ?? null);

        $coverList = is_array($item['virselio_tipas'] ?? null) ? $item['virselio_tipas'] : [];
        $coverType = self::clean($coverList[0] ?? null);

        $categories = [];
        foreach ($rawIds as $id) {
            if (is_int($id)) {
                $categories[] = CategoryNames::name($id);
            }
        }

        $bookType = self::deriveBookType(
            $item['is_book'] ?? null,
            $item['is_audio_book'] ?? null,
            $item['is_ebook'] ?? null,
            self::categoriesIndicateBook($categories),
        );

        $properties = [];
        if ($coverType !== null && $coverType !== '') {
            $properties['cover_type'] = $coverType;
        }
        if (($item['is_new'] ?? null) !== null) {
            $properties['is_new'] = (bool) $item['is_new'];
        }
        if (($item['in_store_only'] ?? null) !== null) {
            $properties['in_store_only'] = (bool) $item['in_store_only'];
        }
        if (is_int($item['discount_rate'] ?? null) || is_float($item['discount_rate'] ?? null)) {
            $properties['discount_rate'] = (float) $item['discount_rate'];
        }

        return [
            'url' => self::clean($item['url'] ?? null) ?? '',
            'title' => self::clean($item['name'] ?? null),
            'author' => $authorStr,
            'sku' => self::clean($item['sku'] ?? null),

            'isbn' => null,
            'publisher' => $publisher,
            'year' => null,
            'format' => self::formatFromBookType($bookType, $coverType),
            'description' => self::flattenAnotacija($item['anotacija'] ?? null),
            'image_url' => self::clean($item['image'] ?? null),
            'price' => $price,
            'price_original' => $priceOriginal,
            'in_stock' => ($item['in_stock'] ?? null) === 1 || ($item['in_stock'] ?? null) === true,
            'type' => $bookType,
            'categories' => $categories,
            'properties' => $properties === [] ? null : $properties,
        ];
    }

    /** @return array{string|null, string|null} */
    private static function resolveIsbnAndEan(?string $rawIsbn, ?string $rawEan): array
    {
        $strict = static function (?string $value): ?string {
            if ($value === null) {
                return null;
            }
            $digits = trim(str_replace(['-', ' '], '', $value));

            return Isbn::isValid($digits) ? Isbn::toIsbn13($digits) : null;
        };

        $isbnStrict = $strict($rawIsbn);
        $eanStrict = $strict($rawEan);
        $isbnRecovered = self::coerceIsbn($rawIsbn);

        if ($isbnStrict !== null) {
            $isbn = $isbnStrict;
        } elseif ($eanStrict !== null && $isbnRecovered !== null
            && Str::startsWith($isbnRecovered, substr($eanStrict, 0, 9))) {
            $isbn = $eanStrict;
        } elseif ($isbnRecovered !== null) {
            $isbn = $isbnRecovered;
        } else {
            $isbn = $eanStrict ?? self::coerceIsbn($rawEan);
        }

        $ean = ($rawEan !== null && $rawEan !== $isbn) ? $rawEan : null;

        return [$isbn, $ean];
    }

    public static function coerceIsbn(mixed $value): ?string
    {
        if (! is_string($value)) {
            return null;
        }
        $digits = trim(str_replace(['-', ' '], '', $value));

        if (Isbn::isValid($digits)) {
            return Isbn::toIsbn13($digits);
        }

        if (strlen($digits) === 10 && ctype_digit(substr($digits, 0, 9))) {
            return Isbn::toIsbn13($digits);
        }

        return null;
    }

    /** @return array<string, string> */
    private static function attrsToLabels(mixed $node): array
    {
        if (! is_array($node) || $node === []) {
            return [];
        }
        $containers = array_is_list($node) ? $node : [$node];

        $labels = [];
        foreach ($containers as $container) {
            if (! is_array($container)) {
                continue;
            }
            foreach (['primary_attributes', 'secondary_attributes'] as $bucket) {
                foreach (is_array($container[$bucket] ?? null) ? $container[$bucket] : [] as $attr) {
                    if (! is_array($attr)) {
                        continue;
                    }
                    $label = $attr['label'] ?? null;
                    $value = $attr['value'] ?? null;
                    $stringValue = self::scalarString($value);
                    if (is_string($label) && $label !== '' && $stringValue !== null) {
                        $labels[$label] = $stringValue;
                    }
                }
            }
        }

        return $labels;
    }

    private static function formatFromBookType(string $bookType, ?string $coverType): ?string
    {
        return match ($bookType) {
            'audio' => 'audiobook',
            'ebook' => 'ebook',
            'book' => CoverType::toFormat($coverType) ?? 'book',
            default => null,
        };
    }

    private static function flattenAnotacija(mixed $raw): ?string
    {
        if (is_array($raw)) {
            $joined = implode(' ', array_filter($raw, is_string(...)));
        } elseif (is_string($raw)) {
            $joined = $raw;
        } else {
            return null;
        }

        return self::stripHtml($joined);
    }

    private static function stripHtml(?string $text): ?string
    {
        if ($text === null || $text === '') {
            return null;
        }
        $cleaned = preg_replace('/<[^>]+>/', ' ', $text) ?? $text;
        $cleaned = trim(preg_replace('/\s+/u', ' ', $cleaned) ?? $cleaned);
        $cleaned = html_entity_decode($cleaned, ENT_QUOTES | ENT_HTML5, 'UTF-8');

        return $cleaned === '' ? null : $cleaned;
    }

    private static function clean(mixed $value): ?string
    {
        if (! is_string($value)) {
            return null;
        }
        $trimmed = trim($value);

        return ($trimmed === '' || in_array($trimmed, self::EMPTY_MARKERS, true))
            ? null
            : $trimmed;
    }

    private static function parseYear(mixed $value): ?int
    {
        if (in_array($value, [null, '', false], true)) {
            return null;
        }
        $string = self::scalarString($value);
        if ($string === null || preg_match('/^(\d{4})/', $string, $m) !== 1) {
            return null;
        }
        $year = (int) $m[1];

        return ($year >= 1500 && $year <= 2100) ? $year : null;
    }

    private static function parseInt(mixed $value): ?int
    {
        if ($value === null || $value === '') {
            return null;
        }
        $string = self::scalarString($value);
        if ($string === null) {
            return null;
        }
        $trimmed = trim($string);

        return preg_match('/^-?\d+$/', $trimmed) === 1 ? (int) $trimmed : null;
    }

    private static function truthy(mixed $value): bool
    {
        if (is_string($value)) {

            return $value !== '';
        }

        return (bool) $value;
    }

    private static function numberToString(mixed $value): ?string
    {
        if ($value === null) {
            return null;
        }
        if (is_float($value)) {

            return $value === floor($value) && is_finite($value)
                ? sprintf('%.1f', $value)
                : (string) $value;
        }

        return is_int($value) || is_string($value) && is_numeric($value)
            ? (string) $value
            : null;
    }

    private static function foldAscii(string $value): string
    {
        $lower = mb_strtolower($value, 'UTF-8');
        $nfd = Normalizer::normalize($lower, Normalizer::FORM_D);

        return preg_replace('/\p{Mn}/u', '', $nfd === false ? $lower : $nfd) ?? $lower;
    }

    /** @return ParsedItem */
    private static function emptyProductPage(string $reasonKey): array
    {
        return [
            'title' => null, 'description' => null, 'price' => null,
            'price_original' => null, 'in_stock' => null, 'isbn' => null,
            'sku' => null, 'publisher' => null, 'image_url' => null,
            'categories' => [], 'year' => null, 'pages' => null,
            'author' => null, 'cover_type' => null, 'format' => null,
            'duration' => null, 'narrator' => null, 'translator' => null,
            'schema_types' => [], 'is_book_product' => false, 'book_score' => 0,
            'book_score_reasons' => [['key' => $reasonKey, 'points' => 0]],
            'type' => 'non_book', 'planned_availability_date' => null,
            'rating' => null, 'review_count' => null,
        ];
    }

    /** @return array<string, mixed> */
    private static function map(mixed $value): array
    {
        if (! is_array($value)) {
            return [];
        }

        $map = [];
        foreach ($value as $key => $item) {
            if (is_string($key)) {
                $map[$key] = $item;
            }
        }

        return $map;
    }

    /** @return list<array<string, mixed>> */
    private static function listOfMaps(mixed $value): array
    {
        if (! is_array($value)) {
            return [];
        }

        $maps = [];
        foreach ($value as $item) {
            if (is_array($item)) {
                $maps[] = self::map($item);
            }
        }

        return $maps;
    }

    private static function scalarString(mixed $value): ?string
    {
        if (is_string($value)) {
            return $value;
        }

        return is_int($value) || is_float($value) ? (string) $value : null;
    }

    private static function integer(mixed $value): ?int
    {
        if (is_int($value)) {
            return $value;
        }
        if (is_string($value) && preg_match('/^-?\d+$/', $value) === 1) {
            return (int) $value;
        }

        return null;
    }

    private static function number(mixed $value): ?float
    {
        if (is_int($value) || is_float($value)) {
            return (float) $value;
        }
        if (is_string($value) && is_numeric($value)) {
            return (float) $value;
        }

        return null;
    }
}
