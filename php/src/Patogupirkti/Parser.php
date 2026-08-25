<?php

declare(strict_types=1);

namespace BookScraper\Patogupirkti;

use BookScraper\CoverType;
use BookScraper\Isbn;
use BookScraper\Vaga\Parser as BookClassifier;

/**
 * Port of book_scraper/spiders/patogupirkti/parsers.py.
 *
 * Magento 1. Category cards carry an inline `product_tracking_data` JS
 * object with structured fields; product pages use schema.org microdata
 * plus a spec table. Book/non-book scoring is shared with vaga, as in the
 * Python module.
 */
final class Parser
{
    private const BASE_URL = 'https://www.patogupirkti.lt';
    private const SITEMAP_NS = 'http://www.sitemaps.org/schemas/sitemap/0.9';

    /** Card boundary. Splitting on the opening tag keeps fields from bleeding. */
    private const CARD_OPEN = '/<div\s+class="product">/i';

    private const CARD_LINK = '/href="(https?:\/\/www\.patogupirkti\.lt\/knyga\/[^"]+\.html)"/i';

    /** `var product_tracking_data_62181 = {...};` */
    private const TRACKING_DATA = '/var\s+product_tracking_data_(\d+)\s*=\s*(\{.*?\})\s*;/s';

    private const PRICE_VALUE = '/([\d ]+[.,]\d+)\s*(?:<[^>]+>)?\s*€/u';
    private const NEW_PRICE = '/<div\s+class="new-price"[^>]*>(.*?)<\/div>/si';
    private const OLD_PRICE = '/<strong[^>]*\bclass="[^"]*\bold-price\b[^"]*"[^>]*>(.*?)<\/strong>/si';

    private const STOCK = '/<div\s+class="(instock|outstock)\s+stock-status/i';

    /** "Šiuo metu neparduodama" — discontinued, no availability microdata. */
    private const NOT_FOR_SALE = '/neparduodama/i';

    private const SPEC_ROW = '/<td\s+class="title"[^>]*>\s*([^<]+?)\s*:?\s*<\/td>\s*'
        . '<td\s+class="value"[^>]*>(.*?)<\/td>/si';

    private const BREADCRUMB = '/itemprop=["\']itemListElement["\'][^>]*>.*?'
        . 'itemprop=["\']name["\'][^>]*>\s*([^<]+?)\s*</si';

    /** Breadcrumb root present on every product; carries no signal. */
    private const BREADCRUMB_ROOT = 'pirmas';

    // --------------------------------------------------------------- sitemap

    /**
     * Product URLs from a `<urlset>` or `<sitemapindex>`.
     *
     * An index recurses only into children whose loc contains
     * `sitemap_product`, skipping the category/page/author/serial/
     * manufacturer sub-sitemaps. `$fetchChild` is injectable so callers (and
     * tests) control the HTTP.
     *
     * @param  callable(string): string|null  $fetchChild
     * @return list<string>
     */
    public static function parseSitemapUrls(string $xml, ?callable $fetchChild = null): array
    {
        $doc = self::loadXml($xml);
        if ($doc === null) {
            return [];
        }

        if (str_ends_with($doc->documentElement->tagName, 'sitemapindex')) {
            $urls = [];
            $xpath = new \DOMXPath($doc);
            $xpath->registerNamespace('s', self::SITEMAP_NS);
            foreach ($xpath->query('//s:sitemap/s:loc') ?: [] as $node) {
                $loc = $node->textContent;
                if ($loc === '' || !str_contains($loc, 'sitemap_product')) {
                    continue;
                }
                if ($fetchChild === null) {
                    continue;
                }
                $urls = [...$urls, ...self::parseUrlset($fetchChild($loc))];
            }

            return $urls;
        }

        return self::parseUrlset($xml);
    }

    /** @return list<string> */
    private static function parseUrlset(string $xml): array
    {
        $doc = self::loadXml($xml);
        if ($doc === null) {
            return [];
        }
        $xpath = new \DOMXPath($doc);
        $xpath->registerNamespace('s', self::SITEMAP_NS);

        $urls = [];
        foreach ($xpath->query('//s:loc') ?: [] as $node) {
            if ($node->textContent !== '') {
                $urls[] = $node->textContent;
            }
        }

        return $urls;
    }

    // -------------------------------------------------------- category page

    /**
     * Products from a category listing.
     *
     * `total` is null: patogupirkti surfaces no reliable count, so the spider
     * walks `?p=N` until a page comes back empty.
     *
     * @return array{products: list<array<string, mixed>>, total: null}
     */
    public static function parseCategoryPage(string $html): array
    {
        $products = [];
        $seen = [];

        foreach (self::splitCards($html) as $card) {
            if (preg_match(self::TRACKING_DATA, $card, $tracking) !== 1) {
                // No tracking blob means template scaffolding (promo tiles).
                continue;
            }
            $data = json_decode($tracking[2], true);
            if (!is_array($data)) {
                continue;
            }

            if (preg_match(self::CARD_LINK, $card, $link) !== 1) {
                continue;
            }
            $url = $link[1];
            if (isset($seen[$url])) {
                continue;
            }
            $seen[$url] = true;

            $title = self::unescape((string) ($data['name'] ?? ''));
            if ($title === null) {
                continue;
            }

            $priceOriginal = isset($data['price']) && $data['price'] !== ''
                ? self::normalizePrice((string) $data['price'])
                : null;

            // The rendered card carries the displayed price: `.new-price` is
            // final, the `.old-price` strong is pre-discount. Full-priced
            // items have neither, so fall back to the tracking price.
            $price = preg_match(self::NEW_PRICE, $card, $new) === 1
                ? self::normalizePrice($new[1])
                : null;
            if (preg_match(self::OLD_PRICE, $card, $old) === 1) {
                $fromOld = self::normalizePrice($old[1]);
                if ($fromOld !== null) {
                    $priceOriginal = $fromOld;
                }
            }
            if ($price === null) {
                $price = $priceOriginal;
                // No discount, so an "original" would just duplicate it.
                $priceOriginal = null;
            }

            if (preg_match(self::STOCK, $card, $stock) === 1) {
                $inStock = strtolower($stock[1]) === 'instock';
            } elseif (preg_match(self::NOT_FOR_SALE, $card) === 1) {
                $inStock = false;
            } else {
                $inStock = true;
            }

            // `variant` joins publisher/year/format/pages ("Jotema, 2026,
            // 15x22, minkšti viršeliai, 352"). Splitting it is fragile —
            // publishers contain commas — so it is kept raw and the scan
            // phase fills clean fields from the product page.
            $properties = ['magento_id' => $tracking[1]];
            if (is_string($data['variant'] ?? null) && trim($data['variant']) !== '') {
                $properties['variant_raw'] = trim($data['variant']);
            }

            $category = $data['category'] ?? null;
            $categories = is_string($category) && trim($category) !== ''
                ? [trim($category)]
                : [];

            $products[] = [
                'url' => $url,
                'title' => $title,
                'author' => self::unescape((string) ($data['brand'] ?? '')),
                'price' => $price,
                'price_original' => $priceOriginal,
                'in_stock' => $inStock,
                'categories' => $categories,
                'properties' => $properties,
            ];
        }

        return ['products' => $products, 'total' => null];
    }

    // --------------------------------------------------------- product page

    /** @return array<string, mixed> */
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

        // h1 is clean; og:title carries a " - <author> | Patogupirkti.lt"
        // suffix that has to come off.
        if (preg_match('/<h1[^>]*>\s*([^<]+?)\s*<\/h1>/i', $html, $h1) === 1) {
            $data['title'] = self::unescape($h1[1]);
        } else {
            $ogTitle = self::metaContent($html, 'og:title');
            if ($ogTitle !== null) {
                $ogTitle = preg_replace('/\s*\|\s*Patogupirkti\.lt\s*$/u', '', $ogTitle) ?? $ogTitle;
                $ogTitle = preg_replace('/\s+-\s+[^-]+$/u', '', $ogTitle) ?? $ogTitle;
            }
            $data['title'] = $ogTitle;
        }

        // Microdata.
        $author = self::itempropText($html, 'author');
        if ($author !== null) {
            $data['author'] = $author;
        }
        $description = self::itempropText($html, 'description')
            ?? self::metaContent($html, 'og:description');
        if ($description !== null) {
            $data['description'] = $description;
        }
        $data['year'] = self::intOrNull(self::itempropText($html, 'copyrightYear'));
        $data['pages'] = self::intOrNull(self::itempropText($html, 'numberOfPages'));

        $isbnRaw = self::itempropText($html, 'isbn');
        if ($isbnRaw !== null) {
            $normalized = Isbn::normalize($isbnRaw);
            if (Isbn::isValid($normalized)) {
                // patogupirkti uses the ISBN as its SKU.
                $data['isbn'] = $normalized;
                $data['sku'] = $normalized;
            }
        }

        $priceRaw = self::itempropText($html, 'price');
        if ($priceRaw !== null) {
            // Already a clean decimal in practice; normalised in case the
            // template changes.
            $data['price'] = self::normalizePrice($priceRaw . ' €') ?: (trim($priceRaw) ?: null);
        }

        $availability = self::itempropText($html, 'availability')
            ?? self::itempropAttribute($html, 'availability');
        if ($availability !== null) {
            $data['in_stock'] = strtolower(trim($availability)) === 'instock';
        } elseif (preg_match(self::NOT_FOR_SALE, $html) === 1) {
            // Discontinued items emit no availability microdata. Marking them
            // out of stock keeps them out of the missing-price checks.
            $data['in_stock'] = false;
        }

        $image = self::metaContent($html, 'og:image');
        if ($image !== null) {
            $data['image_url'] = $image;
        }

        // Spec table: publisher, cover type, translator, and a fallback for
        // fields the microdata misses on legacy pages.
        $spec = self::extractSpecTable($html);

        if ($data['author'] === null && ($spec['Autorius'] ?? '') !== '') {
            $data['author'] = $spec['Autorius'];
        }
        $publisher = ($spec['Leidėjas'] ?? '') ?: ($spec['Leidykla'] ?? '');
        if ($publisher !== '') {
            $data['publisher'] = $publisher;
        }
        $data['year'] ??= self::intOrNull($spec['Išleidimo metai'] ?? null);
        $data['pages'] ??= self::intOrNull($spec['Knygos puslapių skaičius'] ?? null);

        if ($data['isbn'] === null && ($spec['ISBN ar kodas'] ?? '') !== '') {
            $normalized = Isbn::normalize($spec['ISBN ar kodas']);
            if (Isbn::isValid($normalized)) {
                $data['isbn'] = $normalized;
                $data['sku'] = $normalized;
            }
        }
        if (isset($spec['Formatas'])) {
            $data['cover_type'] = $spec['Formatas'];
            $data['format'] = CoverType::toFormat($spec['Formatas']);
        }
        if (isset($spec['Vertėjas'])) {
            $data['translator'] = $spec['Vertėjas'];
        }

        // Spec extras worth keeping but without first-class columns.
        $properties = [];
        if (isset($spec['Pavadinimas originalo kalba'])) {
            $properties['original_title'] = $spec['Pavadinimas originalo kalba'];
        }
        if (isset($spec['Iš kokios kalbos versta'])) {
            $properties['source_language'] = $spec['Iš kokios kalbos versta'];
        }
        if ($properties !== []) {
            $data['properties'] = $properties;
        }

        // Genre joins the breadcrumb chain so the classifier can read it as a
        // book signal.
        $categories = self::extractCategories($html);
        $genre = $spec['Žanras'] ?? null;
        if ($genre !== null && !in_array($genre, $categories, true)) {
            $categories[] = $genre;
        }
        $data['categories'] = $categories;

        $classification = BookClassifier::classifyBookProduct($data);
        $data['is_book_product'] = $classification['is_book_product'];
        $data['book_score'] = $classification['score'];
        $data['book_score_reasons'] = $classification['reasons'];
        $data['type'] = BookClassifier::inferShopBookType($data);

        return $data;
    }

    // -------------------------------------------------------------- helpers

    /** @return list<string> per-card HTML slices */
    private static function splitCards(string $html): array
    {
        $parts = preg_split(self::CARD_OPEN, $html) ?: [];

        // The first slice is everything before the first card.
        return count($parts) > 1 ? array_slice($parts, 1) : [];
    }

    /**
     * itemprop text. The attribute may hold several space-separated tokens
     * (`itemprop="isbn sku"`), so the token is matched on word boundaries.
     */
    private static function itempropText(string $html, string $prop): ?string
    {
        $pattern = sprintf(
            '/itemprop=["\'][^"\']*\b%s\b[^"\']*["\'][^>]*>\s*([^<]*)/i',
            preg_quote($prop, '/')
        );

        return preg_match($pattern, $html, $m) === 1 ? self::unescape($m[1]) : null;
    }

    /** Same, but from a content="" / href="" attribute. */
    private static function itempropAttribute(string $html, string $prop): ?string
    {
        $pattern = sprintf(
            '/itemprop=["\'][^"\']*\b%s\b[^"\']*["\'][^>]*(?:content|href)=["\']([^"\']*)["\']/i',
            preg_quote($prop, '/')
        );

        return preg_match($pattern, $html, $m) === 1 ? self::unescape($m[1]) : null;
    }

    /** @return array<string, string> */
    private static function extractSpecTable(string $html): array
    {
        preg_match_all(self::SPEC_ROW, $html, $rows, PREG_SET_ORDER);

        $out = [];
        foreach ($rows as $row) {
            $label = rtrim(trim(self::unescape($row[1]) ?? ''), ':');
            $label = trim($label);
            $value = self::unescape(preg_replace('/<[^>]+>/', ' ', $row[2]) ?? $row[2]);
            if ($label !== '' && $value !== null && $value !== '') {
                $out[$label] = $value;
            }
        }

        return $out;
    }

    /** @return list<string> */
    private static function extractCategories(string $html): array
    {
        preg_match_all(self::BREADCRUMB, $html, $matches);

        $names = [];
        foreach ($matches[1] as $raw) {
            $name = self::unescape($raw);
            if ($name !== null) {
                $names[] = $name;
            }
        }

        // The last crumb is the product title itself.
        if (count($names) > 1) {
            array_pop($names);
        }

        return array_values(array_filter(
            $names,
            static fn (string $n): bool => mb_strtolower($n, 'UTF-8') !== self::BREADCRUMB_ROOT
        ));
    }

    private static function metaContent(string $html, string $property): ?string
    {
        $pattern = sprintf(
            '/<meta[^>]+property=["\']%s["\'][^>]+content=["\']([^"\']*)["\']/i',
            preg_quote($property, '/')
        );

        return preg_match($pattern, $html, $m) === 1 ? self::unescape($m[1]) : null;
    }

    private static function normalizePrice(?string $raw): ?string
    {
        if ($raw === null) {
            return null;
        }
        if (preg_match(self::PRICE_VALUE, $raw, $m) !== 1) {
            return null;
        }
        $value = str_replace([' ', ','], ['', '.'], $m[1]);

        return $value === '' ? null : $value;
    }

    /** Collapses whitespace and decodes entities; empty becomes null. */
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

    private static function loadXml(string $xml): ?\DOMDocument
    {
        // loadXML() raises ValueError on an empty string instead of
        // returning false, so this guard has to come first.
        if (trim($xml) === '') {
            return null;
        }

        $doc = new \DOMDocument();
        $previous = libxml_use_internal_errors(true);
        $ok = $doc->loadXML($xml);
        libxml_use_internal_errors($previous);

        return ($ok && $doc->documentElement !== null) ? $doc : null;
    }
}
