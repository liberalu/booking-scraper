<?php

declare(strict_types=1);

namespace App\Parsers\Pegasas;

use App\Support\CoverType;
use App\Support\Isbn;

/**
 * Port of book_scraper/spiders/pegasas/parsers.py.
 *
 * pegasas is a Magento 2 PWA: product pages serve a React shell with no
 * parseable data, so everything comes from JSON — Magento GraphQL (rich,
 * slow) or LupaSearch (fast, thinner). Both are normalised to the same
 * product shape so the spider needs no per-source branching.
 */
final class Parser
{
    private const BASE_URL = 'https://www.pegasas.lt';

    /** Trailing numeric slug suffix is the unpadded Magento SKU. */
    private const SKU_FROM_SLUG = '/-(\d+)\/?$/';

    private const MAGENTO_SKU_WIDTH = 18;

    /** Magento attribute labels. Stable platform labels, not user text. */
    private const LABEL_PUBLISHER = 'Leidykla';
    private const LABEL_TRANSLATOR = 'Vertėjas';
    private const LABEL_YEAR = 'Leidimo metai';
    private const LABEL_COVER = 'Viršelio tipas';
    private const LABEL_PAGES = 'Puslapių skaičius';
    private const LABEL_ISBN = 'ISBN kodas';
    private const LABEL_EAN = 'EAN kodas';
    private const LABEL_LANGUAGE = 'Leidinio kalba';
    private const LABEL_DIMENSIONS = 'Matmenys';
    private const LABEL_ORIGINAL_TITLE = 'Pav. originalo kalba';
    private const LABEL_COLOR = 'Spalvingumas';

    /**
     * pegasas mixes ~38k Lithuanian items with ~600k drop-shipped English
     * imports under the same parent categories, so the language attribute
     * is the only reliable way to scope to LT.
     */
    private const LANG_LITHUANIAN = 'Lietuvių';

    /** 8128 = "Knygos anglų kalba". LupaSearch omits language, so id is the proxy. */
    private const ENGLISH_CATEGORY_IDS = [8128];

    /** 6122 = "Elektroninės knygos". Magento has is_book/is_audio_book but no is_ebook. */
    private const EBOOK_CATEGORY_IDS = [6122];

    /**
     * Category-name substrings that mean "book", used when Magento's
     * `is_book` is false but the categories clearly disagree (educational
     * textbooks, illustrated children's books, some new releases).
     *
     * Substring not prefix, so "Mokslo literatūra" matches on "literat"
     * exactly as "Grožinė literatūra" does. Checked against pegasas's full
     * 1,170-name catalogue: no cosmetics/toys/stationery collide.
     */
    private const BOOK_CATEGORY_SUBSTRINGS = ['knyg', 'groz', 'literat', 'vadovel', 'pratyb'];

    /** Values Magento uses for "empty". */
    private const EMPTY_MARKERS = ['-', '—'];

    // ---------------------------------------------------------------- sitemap

    /** pegasas.lt publishes no XML sitemap. */
    public static function parseSitemapUrls(string $xml): array
    {
        return [];
    }

    // --------------------------------------------------------- category page

    /**
     * Magento GraphQL products-in-category response.
     *
     * `total_count` drives the spider's upfront pagination, without which
     * concurrency never engages on discover.
     *
     * @return array{products: list<array<string, mixed>>, total: int|null}
     */
    public static function parseCategoryPage(string $body): array
    {
        $data = json_decode($body, true);
        if (!is_array($data)) {
            return ['products' => [], 'total' => null];
        }

        $node = $data['data']['products'] ?? [];
        $items = is_array($node['items'] ?? null) ? $node['items'] : [];
        $total = isset($node['total_count']) && is_numeric($node['total_count'])
            ? (int) $node['total_count']
            : null;

        $products = [];
        foreach ($items as $item) {
            if (!is_array($item) || ($item['url_key'] ?? null) === null || $item['url_key'] === '') {
                continue;
            }
            $product = self::graphqlItemToProduct($item);
            if ($product !== null) {
                $products[] = $product;
            }
        }

        return ['products' => $products, 'total' => $total];
    }

    // ------------------------------------------------------------ lupasearch

    /**
     * LupaSearch query API response. Same product shape as GraphQL, but
     * ISBN/year/pages are always null — LupaSearch doesn't expose them, and
     * enrichment happens via GraphQL or a scan fetch.
     *
     * @return array{products: list<array<string, mixed>>, total: int}
     */
    public static function parseLupasearchResponse(string $body): array
    {
        $data = json_decode($body, true);
        if (!is_array($data)) {
            return ['products' => [], 'total' => 0];
        }

        $products = [];
        foreach (is_array($data['items'] ?? null) ? $data['items'] : [] as $item) {
            if (!is_array($item)) {
                continue;
            }
            $product = self::lupasearchItemToProduct($item);
            if ($product !== null) {
                $products[] = $product;
            }
        }

        return ['products' => $products, 'total' => (int) ($data['total'] ?? 0)];
    }

    // ---------------------------------------------------------- product page

    /**
     * Per-SKU GraphQL response, reached after rewriteScanUrl() swapped the
     * product URL. Non-JSON means the PWA shell was served directly.
     *
     * @return array<string, mixed>
     */
    public static function parseProductPage(string $body): array
    {
        $data = json_decode($body, true);
        if (!is_array($data)) {
            return self::emptyProductPage('pwa_shell_no_data');
        }

        $items = $data['data']['products']['items'] ?? [];
        if (!is_array($items) || $items === []) {
            return self::emptyProductPage('graphql_no_match');
        }

        $product = self::graphqlItemToProduct($items[0]);
        if ($product === null) {
            // Language gate fired. Recorded as non-product so the row closes
            // cleanly instead of raising a noisy validation error.
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
            'categories' => $product['categories'] ?? [],
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
            'type' => $product['type'] ?: 'non_book',
            'planned_availability_date' => null,
            'rating' => null,
            'review_count' => null,
        ];
    }

    /**
     * Rewrite a product URL into a single-SKU GraphQL request.
     *
     * The PWA serves a React shell for product pages, but GraphQL returns
     * full metadata in 200–500ms when filtered to one SKU. Returns null when
     * the slug carries no SKU; the spider then leaves the request alone and
     * the response lands in the shell fallback.
     *
     * @return array{url: string, headers: array<string, string>}|null
     */
    public static function rewriteScanUrl(string $url): ?array
    {
        $parts = parse_url($url);
        $path = rtrim($parts['path'] ?? '', '/');
        if (preg_match(self::SKU_FROM_SLUG, $path, $m) !== 1) {
            return null;
        }

        $sku = str_pad($m[1], self::MAGENTO_SKU_WIDTH, '0', STR_PAD_LEFT);
        $query = '{products('
            . sprintf('filter:{sku:{eq:"%s"}},', $sku)
            . 'pageSize:1,currentPage:1'
            . '){items{' . GraphQl::PRODUCT_FIELDS . '}}}';

        $base = ($parts['scheme'] ?? 'https') . '://' . ($parts['host'] ?? '');

        return [
            'url' => $base . '/graphql?' . http_build_query(['query' => $query]),
            'headers' => ['Accept' => 'application/json'],
        ];
    }

    // ------------------------------------------------------ type derivation

    /**
     * Map Magento/LupaSearch boolean-ish flags to our `type`.
     *
     * `$hasBookCategory` is a fallback: Magento's `is_book` is false on a
     * subset of real books (textbooks, illustrated children's titles, some
     * new releases), and positive category evidence overrides it.
     *
     * @return 'book'|'audio'|'ebook'|'non_book'
     */
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
            if (!is_string($category)) {
                continue;
            }
            $folded = self::foldAscii($category);
            foreach (self::BOOK_CATEGORY_SUBSTRINGS as $needle) {
                if (str_contains($folded, $needle)) {
                    return true;
                }
            }
        }

        return false;
    }

    // -------------------------------------------------------------- mapping

    /**
     * @param  array<string, mixed>  $item
     * @return array<string, mixed>|null  null when the language gate drops it
     */
    private static function graphqlItemToProduct(array $item): ?array
    {
        $canonicalUrl = self::BASE_URL . '/' . $item['url_key'];

        // Price
        $minimum = $item['price_range']['minimum_price'] ?? [];
        $final = $minimum['final_price'] ?? [];
        $regular = $minimum['regular_price'] ?? [];
        $price = isset($final['value']) ? self::numberToString($final['value']) : null;
        $priceOriginal = null;
        if (isset($regular['value']) && ($regular['value'] !== ($final['value'] ?? null))) {
            $priceOriginal = self::numberToString($regular['value']);
        }

        // Author / narrator
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

        // Categories — names deduped, deepest last preserved.
        $categoryNames = [];
        $categoryIds = [];
        foreach (is_array($item['categories'] ?? null) ? $item['categories'] : [] as $category) {
            if (!is_array($category)) {
                continue;
            }
            $name = $category['name'] ?? null;
            if (is_string($name) && $name !== '' && !in_array($name, $categoryNames, true)) {
                $categoryNames[] = $name;
            }
            $id = $category['id'] ?? null;
            if (is_int($id) && !in_array($id, $categoryIds, true)) {
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
            // Language gate. Only filters when the attribute is POPULATED and
            // clearly non-LT; untagged items (~1% of catalogue) fall through
            // rather than being lost to a Magento omission.
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

        // JSON-LD fallback. Run through coerceIsbn as well: Magento puts
        // EAN-13 in the Schema.org `isbn` slot, so sticker-kit GTINs would
        // otherwise slip past the label-level filter and fail validation.
        if (($isbn === null || $publisher === null || $pages === null || $year === null)
            && is_string($item['structured_data'] ?? null)) {
            $structured = json_decode($item['structured_data'], true);
            $main = is_array($structured) ? ($structured['mainEntity'] ?? []) : [];
            if (is_array($main)) {
                $isbn ??= self::coerceIsbn($main['isbn'] ?? null);
                if ($publisher === null) {
                    $pub = $main['publisher'] ?? null;
                    if (is_array($pub)) {
                        $publisher = ($pub['name'] ?? null) ?: null;
                    } elseif (is_string($pub)) {
                        $publisher = $pub ?: null;
                    }
                }
                $pages ??= self::parseInt($main['numberOfPages'] ?? null);
                $year ??= self::parseYear($main['datePublished'] ?? null);
            }
        }

        $properties = [];
        // Audiobooks must not carry pages: Magento sometimes reports the
        // print edition's count, through both the attributes and the JSON-LD
        // fallback. Duration is the right metric for audio.
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
            'title' => $item['name'] ?? null,
            'author' => $authorStr,
            'sku' => $item['sku'] ?? null,
            'isbn' => $isbn,
            'publisher' => $publisher,
            'year' => $year,
            'format' => self::formatFromBookType($bookType, $coverType),
            'description' => self::flattenAnotacija($item['anotacija'] ?? null),
            'image_url' => $item['image']['url'] ?? null,
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
     * @return array<string, mixed>|null
     */
    private static function lupasearchItemToProduct(array $item): ?array
    {
        // Language gate by category id: LupaSearch omits the attribute.
        $rawIds = is_array($item['category_ids'] ?? null) ? $item['category_ids'] : [];
        foreach ($rawIds as $id) {
            if (ctype_digit((string) $id) && in_array((int) $id, self::ENGLISH_CATEGORY_IDS, true)) {
                return null;
            }
        }

        // price is a stringified decimal, regular_price a float. Only emit an
        // original when it actually differs.
        $price = isset($item['price']) ? self::numberToString($item['price']) : null;
        $priceOriginal = null;
        if (isset($item['regular_price']) && $price !== null
            && (float) $item['regular_price'] !== (float) $price) {
            $priceOriginal = self::numberToString($item['regular_price']);
        }

        $authors = array_values(array_filter(
            is_array($item['autorius'] ?? null) ? $item['autorius'] : [],
            static fn (mixed $a): bool => is_string($a) && $a !== ''
        ));
        $authorStr = $authors === [] ? null : implode(', ', $authors);

        $publisher = self::clean($item['leidykla'] ?? null);

        $coverList = is_array($item['virselio_tipas'] ?? null) ? $item['virselio_tipas'] : [];
        $coverType = $coverList === [] ? null : ($coverList[0] ?? null);

        // Only numeric ids come back, so resolve names through the generated
        // map — otherwise the validator's non-book keyword checks see nothing.
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
            'url' => $item['url'] ?? '',
            'title' => $item['name'] ?? null,
            'author' => $authorStr,
            'sku' => $item['sku'] ?? null,
            // Absent from the LupaSearch payload; filled by GraphQL or scan.
            'isbn' => null,
            'publisher' => $publisher,
            'year' => null,
            'format' => self::formatFromBookType($bookType, $coverType),
            'description' => self::flattenAnotacija($item['anotacija'] ?? null),
            'image_url' => $item['image'] ?? null,
            'price' => $price,
            'price_original' => $priceOriginal,
            'in_stock' => ($item['in_stock'] ?? null) === 1 || ($item['in_stock'] ?? null) === true,
            'type' => $bookType,
            'categories' => $categories,
            'properties' => $properties === [] ? null : $properties,
        ];
    }

    // -------------------------------------------------------- ISBN vs EAN

    /**
     * pegasas's `EAN kodas` also carries non-book GTINs (sticker kits,
     * puzzles, `40100706…`), and its `ISBN kodas` sometimes holds a typo'd
     * ISBN-10. Two real cases drive the rule:
     *
     *  1. "Rikiki skalbia" — ISBN field has a bad-check-digit ISBN-10, EAN
     *     has the real ISBN-13. Both share publisher prefix 978-9986-02, so
     *     the EAN is the correction and wins.
     *  2. "Dina gėdytojos duktė" — ISBN field has a typo'd ISBN-10, EAN has
     *     an unrelated valid ISBN-13 (a different book). Prefixes diverge
     *     after 4 digits, so the EAN is ignored and the ISBN-10 core is
     *     recovered.
     *
     * Hence: prefer EAN over a recovered ISBN only when the leading 9 digits
     * (Bookland + group + publisher) agree — same publisher, same book.
     *
     * @return array{0: string|null, 1: string|null}  [isbn, ean]
     */
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
            && substr($isbnRecovered, 0, 9) === substr($eanStrict, 0, 9)) {
            $isbn = $eanStrict;
        } elseif ($isbnRecovered !== null) {
            $isbn = $isbnRecovered;
        } else {
            $isbn = $eanStrict ?? self::coerceIsbn($rawEan);
        }

        // Keep the EAN only when it is a real GTIN distinct from the ISBN.
        $ean = ($rawEan !== null && $rawEan !== $isbn) ? $rawEan : null;

        return [$isbn, $ean];
    }

    /**
     * Normalise a raw field to ISBN-13, or null.
     *
     * Accepts a valid ISBN-13, a valid ISBN-10, or an ISBN-10 with a wrong
     * check digit — recovered by taking the 9-digit core (pegasas stores
     * 9955082484, whose correct ISBN-13 is 9789955082484). Anything outside
     * the 978/979 Bookland space is rejected.
     */
    public static function coerceIsbn(mixed $value): ?string
    {
        if (!is_string($value)) {
            return null;
        }
        $digits = trim(str_replace(['-', ' '], '', $value));

        if (Isbn::isValid($digits)) {
            return Isbn::toIsbn13($digits);
        }
        // toIsbn13 validates format only, so it accepts an ISBN-10 whose
        // check digit is wrong.
        if (strlen($digits) === 10 && ctype_digit(substr($digits, 0, 9))) {
            return Isbn::toIsbn13($digits);
        }

        return null;
    }

    // -------------------------------------------------------------- helpers

    /**
     * Flatten product_page_attributes into label => value.
     *
     * Magento returns a list of containers, each holding
     * primary_attributes and secondary_attributes.
     *
     * @return array<string, string>
     */
    private static function attrsToLabels(mixed $node): array
    {
        if ($node === null || $node === []) {
            return [];
        }
        $containers = array_is_list((array) $node) ? (array) $node : [$node];

        $labels = [];
        foreach ($containers as $container) {
            if (!is_array($container)) {
                continue;
            }
            foreach (['primary_attributes', 'secondary_attributes'] as $bucket) {
                foreach (is_array($container[$bucket] ?? null) ? $container[$bucket] : [] as $attr) {
                    if (!is_array($attr)) {
                        continue;
                    }
                    $label = $attr['label'] ?? null;
                    $value = $attr['value'] ?? null;
                    if (is_string($label) && $label !== '' && $value !== null) {
                        $labels[$label] = (string) $value;
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

    /** LupaSearch returns `anotacija` as a list; GraphQL as a string. */
    private static function flattenAnotacija(mixed $raw): ?string
    {
        if (is_array($raw)) {
            $joined = implode(' ', array_filter($raw, 'is_string'));
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

    /** Empty, whitespace-only and dash values all mean "missing". */
    private static function clean(mixed $value): ?string
    {
        if (!is_string($value)) {
            return null;
        }
        $trimmed = trim($value);

        return ($trimmed === '' || in_array($trimmed, self::EMPTY_MARKERS, true))
            ? null
            : $trimmed;
    }

    private static function parseYear(mixed $value): ?int
    {
        if ($value === null || $value === '' || $value === false) {
            return null;
        }
        if (preg_match('/^(\d{4})/', (string) $value, $m) !== 1) {
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
        $trimmed = trim((string) $value);

        return preg_match('/^-?\d+$/', $trimmed) === 1 ? (int) $trimmed : null;
    }

    /** Mirrors Python's truthiness for the Magento flag fields. */
    private static function truthy(mixed $value): bool
    {
        if (is_string($value)) {
            // Python's bool("0") is True; only the empty string is falsey.
            return $value !== '';
        }

        return (bool) $value;
    }

    /** Matches Python's str() on ints and floats. */
    private static function numberToString(mixed $value): ?string
    {
        if ($value === null) {
            return null;
        }
        if (is_float($value)) {
            // Python renders a whole float as "12.0", PHP as "12".
            return $value === floor($value) && is_finite($value)
                ? sprintf('%.1f', $value)
                : (string) $value;
        }

        return (string) $value;
    }

    private static function foldAscii(string $value): string
    {
        $lower = mb_strtolower($value, 'UTF-8');
        $nfd = \Normalizer::normalize($lower, \Normalizer::FORM_D);

        return preg_replace('/\p{Mn}/u', '', $nfd === false ? $lower : $nfd) ?? $lower;
    }

    /** @return array<string, mixed> */
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
}
