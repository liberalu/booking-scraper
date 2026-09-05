<?php

declare(strict_types=1);

namespace App\Parsers\Patogupirkti;

use App\Books\BookClassifier;
use App\Crawler\CrawlerTypes;
use App\Parsers\DiscoveryParser;
use App\Parsers\ProductParser;
use App\Support\CoverType;
use App\Support\Isbn;
use DOMDocument;
use DOMElement;
use DOMXPath;

/** @phpstan-import-type ParsedItem from CrawlerTypes */
final class Parser implements DiscoveryParser, ProductParser
{
    private const string SITEMAP_NS = 'http://www.sitemaps.org/schemas/sitemap/0.9';

    private const string CARD_OPEN = '/<div\s+class="product">/i';

    private const string CARD_LINK = '/href="(https?:\/\/www\.patogupirkti\.lt\/knyga\/[^"]+\.html)"/i';

    private const string TRACKING_DATA = '/var\s+product_tracking_data_(\d+)\s*=\s*(\{.*?\})\s*;/s';

    private const string PRICE_VALUE = '/([\d ]+[.,]\d+)\s*(?:<[^>]+>)?\s*€/u';

    private const string NEW_PRICE = '/<div\s+class="new-price"[^>]*>(.*?)<\/div>/si';

    private const string OLD_PRICE = '/<strong[^>]*\bclass="[^"]*\bold-price\b[^"]*"[^>]*>(.*?)<\/strong>/si';

    private const string STOCK = '/<div\s+class="(instock|outstock)\s+stock-status/i';

    private const string NOT_FOR_SALE = '/neparduodama/i';

    private const string SPEC_ROW = '/<td\s+class="title"[^>]*>\s*([^<]+?)\s*:?\s*<\/td>\s*'
        .'<td\s+class="value"[^>]*>(.*?)<\/td>/si';

    private const string BREADCRUMB = '/itemprop=["\']itemListElement["\'][^>]*>.*?'
        .'itemprop=["\']name["\'][^>]*>\s*([^<]+?)\s*</si';

    private const string BREADCRUMB_ROOT = 'pirmas';

    /**
     * @param  (callable(string): string)|null  $fetchChild
     * @return list<string>
     */
    public static function parseSitemapUrls(string $xml, ?callable $fetchChild = null): array
    {
        $doc = self::loadXml($xml);
        if (! $doc instanceof DOMDocument) {
            return [];
        }

        $root = $doc->documentElement;
        if (! $root instanceof DOMElement) {
            return [];
        }

        if (str_ends_with($root->tagName, 'sitemapindex')) {
            $urls = [];
            $xpath = new DOMXPath($doc);
            $xpath->registerNamespace('s', self::SITEMAP_NS);
            $nodes = $xpath->query('//s:sitemap/s:loc');
            if ($nodes === false) {
                return [];
            }

            foreach ($nodes as $node) {
                $loc = trim($node->nodeValue ?? '');
                if ($loc === '' || ! str_contains($loc, 'sitemap_product')) {
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
        if (! $doc instanceof DOMDocument) {
            return [];
        }
        $xpath = new DOMXPath($doc);
        $xpath->registerNamespace('s', self::SITEMAP_NS);

        $urls = [];
        $nodes = $xpath->query('//s:loc');
        if ($nodes === false) {
            return [];
        }

        foreach ($nodes as $node) {
            $url = trim($node->nodeValue ?? '');
            if ($url !== '') {
                $urls[] = $url;
            }
        }

        return $urls;
    }

    /** @return array{products: list<ParsedItem>, total: int|null} */
    public static function parseCategoryPage(string $html): array
    {
        $products = [];
        $seen = [];

        foreach (self::splitCards($html) as $card) {
            if (preg_match(self::TRACKING_DATA, $card, $tracking) !== 1) {

                continue;
            }
            $data = json_decode($tracking[2], true);
            if (! is_array($data)) {
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

            $title = self::unescape(self::scalarString($data['name'] ?? null));
            if ($title === null) {
                continue;
            }

            $priceOriginal = self::normalizePrice(self::scalarString($data['price'] ?? null));

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

                $priceOriginal = null;
            }

            if (preg_match(self::STOCK, $card, $stock) === 1) {
                $inStock = strtolower($stock[1]) === 'instock';
            } elseif (preg_match(self::NOT_FOR_SALE, $card) === 1) {
                $inStock = false;
            } else {
                $inStock = true;
            }

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
                'author' => self::unescape(self::scalarString($data['brand'] ?? null)),
                'price' => $price,
                'price_original' => $priceOriginal,
                'in_stock' => $inStock,
                'categories' => $categories,
                'properties' => $properties,
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

                $data['isbn'] = $normalized;
                $data['sku'] = $normalized;
            }
        }

        $priceRaw = self::itempropText($html, 'price');
        if ($priceRaw !== null) {

            $data['price'] = self::normalizePrice($priceRaw.' €');
            if ($data['price'] === null) {
                $trimmedPrice = trim($priceRaw);
                $data['price'] = $trimmedPrice === '' ? null : $trimmedPrice;
            }
        }

        $availability = self::itempropText($html, 'availability')
            ?? self::itempropAttribute($html, 'availability');
        if ($availability !== null) {
            $data['in_stock'] = strtolower(trim($availability)) === 'instock';
        } elseif (preg_match(self::NOT_FOR_SALE, $html) === 1) {

            $data['in_stock'] = false;
        }

        $image = self::metaContent($html, 'og:image');
        if ($image !== null) {
            $data['image_url'] = $image;
        }

        $spec = self::extractSpecTable($html);

        if ($data['author'] === null && ($spec['Autorius'] ?? '') !== '') {
            $data['author'] = $spec['Autorius'];
        }
        $publisher = $spec['Leidėjas'] ?? '';
        if ($publisher === '') {
            $publisher = $spec['Leidykla'] ?? '';
        }
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

        $categories = self::extractCategories($html);
        $genre = $spec['Žanras'] ?? null;
        if ($genre !== null && ! in_array($genre, $categories, true)) {
            $categories[] = $genre;
        }
        $data['categories'] = $categories;

        $classification = BookClassifier::classify($data);
        $data['is_book_product'] = $classification['is_book_product'];
        $data['book_score'] = $classification['score'];
        $data['book_score_reasons'] = $classification['reasons'];
        $data['type'] = BookClassifier::inferType($data);

        return $data;
    }

    /** @return list<string> */
    private static function splitCards(string $html): array
    {
        $parts = preg_split(self::CARD_OPEN, $html);
        if ($parts === false) {
            return [];
        }

        return count($parts) > 1 ? array_slice($parts, 1) : [];
    }

    private static function itempropText(string $html, string $prop): ?string
    {
        $pattern = sprintf(
            '/itemprop=["\'][^"\']*\b%s\b[^"\']*["\'][^>]*>\s*([^<]*)/i',
            preg_quote($prop, '/')
        );

        return preg_match($pattern, $html, $m) === 1 ? self::unescape($m[1]) : null;
    }

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

    private static function scalarString(mixed $value): ?string
    {
        if (is_string($value)) {
            return $value;
        }

        return is_int($value) || is_float($value) ? (string) $value : null;
    }

    private static function loadXml(string $xml): ?DOMDocument
    {

        if (trim($xml) === '') {
            return null;
        }

        $doc = new DOMDocument;
        $previous = libxml_use_internal_errors(true);
        $ok = $doc->loadXML($xml);
        libxml_use_internal_errors($previous);

        return ($ok && $doc->documentElement instanceof DOMElement) ? $doc : null;
    }
}
