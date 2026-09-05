<?php

declare(strict_types=1);

namespace App\Parsers\Vaga;

use App\Books\BookClassifier;
use App\Crawler\CrawlerTypes;
use App\Parsers\DiscoveryParser;
use App\Parsers\ProductParser;
use App\Support\CoverType;
use DOMDocument;
use DOMXPath;
use Symfony\Component\DomCrawler\Crawler;

/** @phpstan-import-type ParsedItem from CrawlerTypes */
final class Parser implements DiscoveryParser, ProductParser
{
    private const string CARD_PRICE = '/class="price(?:\s+[a-z-]+)*"[^>]*>\s*([0-9,]+)€/u';

    private const string CARD_PRICE_OLD = '/class="price-old[^"]*"[^>]*>[^<]*?([0-9,]+)€/u';

    private const array ALLOWED_DESCRIPTION_TAGS = [
        'p', 'br', 'strong', 'em', 'b', 'i', 'u', 'ul', 'ol', 'li',
    ];

    /** @return list<string> */
    public static function parseSitemapUrls(string $xml, ?callable $fetchChild = null): array
    {

        if (trim($xml) === '') {
            return [];
        }

        $doc = new DOMDocument;

        $prev = libxml_use_internal_errors(true);
        $ok = $doc->loadXML($xml);
        libxml_use_internal_errors($prev);
        if ($ok === false) {
            return [];
        }

        $xpath = new DOMXPath($doc);
        $xpath->registerNamespace('s', 'http://www.sitemaps.org/schemas/sitemap/0.9');
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
        $segments = preg_split('/class="product-item-container product-\d+"/u', $html);
        if ($segments === false) {
            $segments = [];
        }
        foreach (array_slice($segments, 1) as $seg) {
            if (preg_match('/<p class="name"><a href="([^"]+)">([^<]+)/u', $seg, $name) !== 1) {
                continue;
            }

            $products[] = [
                'url' => trim(explode('?', $name[1])[0]),
                'title' => self::unescape(trim($name[2])),
                'author' => self::firstGroup('/<p class="Autorius">\s*([^<]+?)\s*<\/p>/u', $seg),

                'price' => self::firstPrice(self::CARD_PRICE, $seg),
                'price_original' => self::firstPrice(self::CARD_PRICE_OLD, $seg),
                'image_url' => self::firstGroup('/data-src="([^"]+)"/u', $seg, unescape: false),
            ];
        }

        $total = null;
        if (preg_match('/Rodoma nuo \d+ iki \d+ iš (\d+)/u', $html, $m) === 1) {
            $total = (int) $m[1];
        }

        return ['products' => $products, 'total' => $total];
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

        $data['author'] = self::firstGroup(
            '/class="brand">\s*<span>Autorius\s*<\/span>\s*<a[^>]*>([^<]+)<\/a>/u',
            $html
        );

        $schemaTypes = [];
        preg_match_all(
            '/<script type="application\/ld\+json">\s*(.*?)\s*<\/script>/us',
            $html,
            $blocks
        );
        foreach ($blocks[1] as $block) {
            $cleaned = preg_replace('/[\x00-\x1f]+/', ' ', trim($block)) ?? '';
            $ld = json_decode($cleaned, true);
            if (! is_array($ld)) {
                continue;
            }

            $ldTypes = self::stringList($ld['@type'] ?? null);
            $schemaTypes = [...$schemaTypes, ...$ldTypes];

            if (in_array('Product', $ldTypes, true) || in_array('Book', $ldTypes, true)) {
                $offers = self::map($ld['offers'] ?? null);
                $data['title'] = self::unescapeMixed($ld['name'] ?? null);
                $data['description'] = self::unescapeMixed($ld['description'] ?? null);
                $data['sku'] = $ld['sku'] ?? null;
                $data['price'] = $offers['price'] ?? null;
                $availability = $offers['availability'] ?? null;
                $data['in_stock'] = is_string($availability) && str_contains($availability, 'InStock');
                $data['isbn'] = self::map($ld['isRelatedTo'] ?? null)['isbn'] ?? null;
                $data['publisher'] = self::unescapeMixed(self::map($ld['brand'] ?? null)['name'] ?? null);
                $images = $ld['image'] ?? [];
                if (is_string($images) && $images !== '') {
                    $data['image_url'] = $images;
                } elseif (is_array($images)) {
                    $firstImage = array_values($images)[0] ?? null;
                    $data['image_url'] = is_string($firstImage) ? $firstImage : null;
                }
            }

            if (($ld['@type'] ?? null) === 'BreadcrumbList') {
                $categories = [];
                $items = $ld['itemListElement'] ?? null;
                if (is_array($items)) {
                    foreach ($items as $item) {
                        if (! is_array($item)) {
                            continue;
                        }

                        $name = $item['name'] ?? null;
                        if (is_string($name) && $name !== '') {
                            $categories[] = self::unescape($name);
                        }
                    }
                }
                $data['categories'] = $categories;
            }
        }

        $special = self::firstPrice('/class="price-new (?:special|coupon)"[^>]*>\s*([\d,]+)€/u', $html);
        if ($special !== null) {
            $data['price'] = $special;
        }

        $data['price_original'] = self::firstPrice('/class="price-knygyne">([0-9,]+)€/u', $html)
            ?? $data['price_original'];

        if (preg_match('/<div[^>]*id=["\']collapse-description["\'][^>]*>(.*?)<\/div>/uis', $html, $desc) === 1) {
            $rich = self::sanitizeDescriptionHtml($desc[1]);
            if ($rich !== '') {
                $data['description'] = self::unescape($rich);
            }
        }

        preg_match_all(
            '/<span class="propery-title">(.*?)<\/span>\s*<span class="propery-des">(.*?)<\/span>/u',
            $html,
            $props,
            PREG_SET_ORDER
        );
        $propMap = [];
        foreach ($props as $pair) {
            $propMap[trim($pair[1])] = self::unescape(trim($pair[2]));
        }

        $data['isbn'] ??= $propMap['ISBN'] ?? null;
        $data['year'] = self::toIntOrNull($propMap['Metai'] ?? null);
        $data['pages'] = self::toIntOrNull($propMap['Puslapiai'] ?? null);
        $data['cover_type'] = $propMap['Viršelis'] ?? null;
        $data['publisher'] ??= $propMap['Leidykla'] ?? null;
        $data['duration'] = $propMap['Trukmė'] ?? null;
        $data['narrator'] = $propMap['Įgarsino'] ?? null;
        $data['translator'] = $propMap['Vertėjas'] ?? null;

        $trukme = trim($propMap['Trukmė'] ?? '');
        if ($trukme !== '' && preg_match('/[1-9]/', $trukme) === 1) {
            $data['format'] = 'audiobook';
        } elseif (isset($propMap['Viršelis'])) {
            $data['format'] = CoverType::toFormat($propMap['Viršelis']);
        } elseif (isset($propMap['Puslapiai'])) {
            $data['format'] = 'book';
        }

        $crawler = new Crawler($html);
        $data['planned_availability_date'] = self::plannedAvailabilityDate($crawler);
        $data['rating'] = self::rating($crawler);
        $data['review_count'] = self::reviewCount($crawler);

        $schemaTypes = array_values(array_unique($schemaTypes));
        sort($schemaTypes);
        $data['schema_types'] = $schemaTypes;

        $classification = BookClassifier::classify($data);
        $data['is_book_product'] = $classification['is_book_product'];
        $data['book_score'] = $classification['score'];
        $data['book_score_reasons'] = $classification['reasons'];
        $data['type'] = BookClassifier::inferType($data);

        return $data;
    }

    public static function sanitizeDescriptionHtml(string $markup): string
    {
        $markup = preg_replace('/<(script|style)\b[^>]*>.*?<\/\1>/uis', '', $markup) ?? $markup;
        $markup = preg_replace('/<!--.*?-->/us', '', $markup) ?? $markup;
        $markup = preg_replace_callback(
            '/<(\/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>/u',
            static function (array $m): string {
                $tag = strtolower($m[2]);

                return in_array($tag, self::ALLOWED_DESCRIPTION_TAGS, true) ? "<{$m[1]}{$tag}>" : '';
            },
            $markup
        ) ?? $markup;

        return trim($markup);
    }

    private static function plannedAvailabilityDate(Crawler $crawler): ?string
    {
        $text = self::firstNodeText($crawler, '.form-group.isankstine .information-content span');
        if ($text === null) {

            foreach ($crawler->filter('span') as $span) {
                if (str_contains($span->textContent, 'Planuojame turėti')) {
                    $text = trim($span->textContent);
                    break;
                }
            }
        }
        if ($text === null) {
            return null;
        }

        return preg_match('/(\d{4}-\d{2}-\d{2})/', $text, $m) === 1 ? $m[1] : null;
    }

    private static function rating(Crawler $crawler): ?float
    {

        $box = $crawler->filter('.rating-box')->first();
        if ($box->count() === 0) {
            return null;
        }
        $stacks = $box->filter('.fa.fa-stack');
        if ($stacks->count() === 0) {
            return null;
        }
        $filled = $stacks->reduce(
            static fn (Crawler $s): bool => $s->filter('i.fa-star:not(.fa-star-o)')->count() > 0
        )->count();

        return $filled > 0 ? (float) $filled : null;
    }

    private static function reviewCount(Crawler $crawler): ?int
    {
        $text = self::firstNodeText($crawler, 'a.reviews_button');
        if ($text === null) {
            return null;
        }

        return preg_match('/^(\d+)/', $text, $m) === 1 ? (int) $m[1] : null;
    }

    private static function firstNodeText(Crawler $crawler, string $selector): ?string
    {
        $node = $crawler->filter($selector);

        return $node->count() > 0 ? trim($node->first()->text()) : null;
    }

    private static function unescape(string $value): string
    {
        return html_entity_decode($value, ENT_QUOTES | ENT_HTML5, 'UTF-8');
    }

    private static function unescapeMixed(mixed $value): mixed
    {
        return is_string($value) ? self::unescape($value) : $value;
    }

    private static function firstGroup(string $pattern, string $subject, bool $unescape = true): ?string
    {
        if (preg_match($pattern, $subject, $m) !== 1) {
            return null;
        }
        $value = trim($m[1]);

        return $unescape ? self::unescape($value) : $value;
    }

    private static function firstPrice(string $pattern, string $subject): ?string
    {
        return preg_match($pattern, $subject, $m) === 1 ? str_replace(',', '.', $m[1]) : null;
    }

    private static function toIntOrNull(?string $value): ?int
    {
        if ($value === null || preg_match('/^-?\d+$/', trim($value)) !== 1) {
            return null;
        }

        return (int) trim($value);
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
