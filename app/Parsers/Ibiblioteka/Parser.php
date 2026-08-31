<?php

declare(strict_types=1);

namespace App\Parsers\Ibiblioteka;

use App\Crawler\CrawlerTypes;
use App\Parsers\DiscoveryParser;
use App\Parsers\IbibliotekaSearchParser;
use App\Parsers\ProductParser;
use App\Parsers\ScanUrlRewriter;

/** @phpstan-import-type ParsedItem from CrawlerTypes */
final class Parser implements DiscoveryParser, IbibliotekaSearchParser, ProductParser, ScanUrlRewriter
{
    private const COVER_BASE = 'https://ibiblioteka.lt';

    private const DETAIL_PATH = '/metis-api/bibliographic-records/public/';

    private const ROLE_CODES = [
        '070' => 'author',
        '080' => 'author',
        '730' => 'translator',
        '550' => 'narrator',
        '440' => 'illustrator',
        '340' => 'editor',
        '220' => 'compiler',
    ];

    private const PAGES = '/(\d+)\s*(?:p\b|psl\.)/u';

    private const DURATION = '/\d+\s*(?:val|min|sek)\.?(?:[^)]*)/u';

    private const YEAR = '/\b(1[89]\d{2}|20\d{2})\b/';

    private const DIMENSIONS = '/(\d+)\s*cm/u';

    private const AUDIO_KEYWORDS = ['mp3', 'audio', 'val.,', 'min.,'];

    /** @return array{products: list<ParsedItem>, total: int|null} */
    public static function parseSearchResponse(string $json): array
    {
        $data = json_decode($json, true);
        if (! is_array($data)) {
            return ['products' => [], 'total' => null];
        }

        $results = self::map($data['results'] ?? null);
        $items = self::listOfMaps($results['content'] ?? null);

        $products = [];
        foreach ($items as $item) {
            $id = self::scalarString($item['id'] ?? null);
            if ($id === null || $id === '' || $id === '0') {
                continue;
            }

            [$year, $publisher] = self::parsePublicationView($item['publicationView'] ?? '');
            [$bookType, $bookFormat] = self::inferTypeAndFormat($item['publicationFormat'] ?? null, '');

            $products[] = [
                'url' => self::COVER_BASE.self::DETAIL_PATH.$id,
                'title' => self::nonEmptyString($item['titleView'] ?? null)
                    ?? self::nonEmptyString($item['titleFull'] ?? null),
                'sku' => self::nonEmptyString($item['code'] ?? null),
                'year' => $year,
                'publisher' => $publisher,
                'type' => $bookType,
                'format' => $bookFormat,

                'is_book_product' => true,
                'book_score' => 5,
            ];
        }

        return ['products' => $products, 'total' => null];
    }

    /** @return array{products: list<ParsedItem>, total: int|null} */
    public static function parseCategoryPage(string $json): array
    {
        return self::parseSearchResponse($json);
    }

    /** @return list<string> */
    public static function parseSitemapUrls(string $xml, ?callable $fetchChild = null): array
    {
        return [];
    }

    /** @return array{url: string, headers: array<string, string>} */
    public static function rewriteScanUrl(string $url): array
    {
        return ['url' => $url, 'headers' => ['Accept' => 'application/json']];
    }

    /** @return ParsedItem */
    public static function parseProductPage(string $json): array
    {
        $raw = json_decode($json, true);
        if (! is_array($raw)) {
            return self::emptyResult();
        }

        $raw = self::map($raw);
        $physical = self::scalarString($raw['allPhysicalAttributes'] ?? null) ?? '';
        $pubFormat = self::nonEmptyString($raw['publicationFormat'] ?? null);
        [$bookType] = self::inferTypeAndFormat($pubFormat, $physical);

        $pages = null;
        $duration = null;
        if ($physical !== '') {
            if ($bookType === 'audio') {
                $duration = preg_match(self::DURATION, $physical, $m) === 1
                    ? rtrim(trim($m[0]), ',;')
                    : null;
            } else {
                $pages = preg_match(self::PAGES, $physical, $m) === 1 ? (int) $m[1] : null;
            }
        }

        $cover = self::nonEmptyString($raw['coverUrl'] ?? null);
        if ($cover !== null && str_starts_with($cover, '/')) {
            $cover = self::COVER_BASE.$cover;
        }

        $year = null;
        if (is_string($raw['publicationDate'] ?? null)
            && preg_match(self::YEAR, $raw['publicationDate'], $m) === 1) {
            $year = (int) $m[1];
        }

        $isbns = [];
        foreach (is_array($raw['isbn'] ?? null) ? $raw['isbn'] : [] as $rawIsbn) {
            if (! is_string($rawIsbn) || $rawIsbn === '') {
                continue;
            }
            $cleaned = str_replace(['-', ' '], '', $rawIsbn);
            $isbns[] = [
                'isbn' => $rawIsbn,
                'type' => match (strlen($cleaned)) {
                    13 => 'isbn13',
                    10 => 'isbn10',
                    default => 'unknown',
                },
            ];
        }

        $languages = is_array($raw['languages'] ?? null) ? $raw['languages'] : [];
        $language = isset($languages[0]) && is_array($languages[0])
            ? self::nonEmptyString($languages[0]['code'] ?? null)
            : null;

        $translatedFrom = [];
        foreach (is_array($raw['translatedFromLanguages'] ?? null) ? $raw['translatedFromLanguages'] : [] as $lang) {
            if (is_array($lang)) {
                $code = self::nonEmptyString($lang['code'] ?? null);
                if ($code !== null) {
                    $translatedFrom[] = $code;
                }
            }
        }

        $audienceRaw = is_array($raw['audience'] ?? null) ? $raw['audience'] : [];
        $audience = isset($audienceRaw[0]) && is_array($audienceRaw[0])
            ? self::nonEmptyString($audienceRaw[0]['nameLt'] ?? null)
            : null;

        $rateAverage = self::number($raw['rateAverage'] ?? null);
        $rateNumber = self::integer($raw['rateNumber'] ?? null);
        $rateAverage = $rateAverage === 0.0 ? null : $rateAverage;
        $rateNumber = $rateNumber === 0 ? null : $rateNumber;

        return [
            '_emit_as' => 'book',
            '_part_urls' => self::partUrls($raw),
            'is_book_product' => true,
            'book_score' => 5,
            'book_score_reasons' => [['reason' => 'ibiblioteka_national_library']],
            'data_source' => 'ibiblioteka',
            'libis_code' => self::nonEmptyString($raw['code'] ?? null),
            'title' => self::nonEmptyString($raw['title'] ?? null),
            'title_full' => self::nonEmptyString($raw['titleFull'] ?? null),
            'year' => $year,
            'publisher' => self::nonEmptyString($raw['publisher'] ?? null),
            'series' => self::nonEmptyString($raw['seriesView'] ?? null),
            'release_place' => self::nonEmptyString($raw['releasePlace'] ?? null),
            'type' => $bookType,
            'format' => $pubFormat,
            'pages' => $pages,
            'duration' => $duration,
            'dimensions' => self::parseDimensions($physical),
            'language' => $language,
            'translated_from' => $translatedFrom === [] ? null : $translatedFrom,
            'description' => self::nonEmptyString($raw['summary'] ?? null),
            'cover_url' => $cover,
            'upcoming_release' => self::boolean($raw['upcomingRelease'] ?? null),
            'udc_codes' => self::nonEmptyValue($raw['udcSubjectsCodes'] ?? null),
            'subjects' => self::nonEmptyValue($raw['rubricSubjectView'] ?? null),
            'audience' => $audience,
            'libis_rating' => $rateAverage,
            'libis_review_count' => $rateNumber,
            'isbns' => $isbns,
            'authors' => self::extractAuthors($raw),
        ];
    }

    /**
     * @param  array<string, mixed>  $raw
     * @return list<string>
     */
    private static function partUrls(array $raw): array
    {
        $parts = is_array($raw['parts'] ?? null) ? $raw['parts'] : [];
        if (! self::boolean($raw['multipart'] ?? null) || $parts === []) {
            return [];
        }

        $urls = [];
        foreach ($parts as $part) {
            $code = is_array($part) ? self::scalarString($part['code'] ?? null) : null;
            if ($code !== null && $code !== '') {
                $urls[] = self::COVER_BASE.self::DETAIL_PATH.$code;
            }
        }

        return $urls;
    }

    /**
     * @param  array<string, mixed>  $raw
     * @return list<array{name: string, libis_code: string|null, role: string, position: int}>
     */
    private static function extractAuthors(array $raw): array
    {
        $out = [];
        $seen = [];
        $rolePosition = [];

        foreach (is_array($raw['authorViews'] ?? null) ? $raw['authorViews'] : [] as $view) {
            if (! is_array($view)) {
                continue;
            }

            $name = self::nonEmptyString($view['titleLt'] ?? null)
                ?? self::nonEmptyString($view['value'] ?? null);
            if ($name === null) {
                continue;
            }
            $code = self::nonEmptyString($view['code'] ?? null);
            $key = 'author|'.($code ?? $name);
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $position = $rolePosition['author'] ?? 0;
            $out[] = ['name' => $name, 'libis_code' => $code, 'role' => 'author', 'position' => $position];
            $rolePosition['author'] = $position + 1;
        }

        foreach (is_array($raw['persons'] ?? null) ? $raw['persons'] : [] as $person) {
            if (! is_array($person)) {
                continue;
            }
            $name = self::nonEmptyString($person['titleLt'] ?? null)
                ?? self::nonEmptyString($person['name'] ?? null);
            if ($name === null) {
                continue;
            }
            $code = self::nonEmptyString($person['code'] ?? null);

            foreach (is_array($person['types'] ?? null) ? $person['types'] : [] as $type) {
                $roleCode = is_array($type) ? self::nonEmptyString($type['code'] ?? null) : null;
                $role = $roleCode === null ? null : (self::ROLE_CODES[$roleCode] ?? null);
                if ($role === null) {
                    continue;
                }
                $key = $role.'|'.($code ?? $name);
                if (isset($seen[$key])) {
                    continue;
                }
                $seen[$key] = true;
                $position = $rolePosition[$role] ?? 0;
                $out[] = ['name' => $name, 'libis_code' => $code, 'role' => $role, 'position' => $position];
                $rolePosition[$role] = $position + 1;
            }
        }

        return $out;
    }

    /** @return array{int|null, string|null} */
    private static function parsePublicationView(mixed $view): array
    {
        if (! is_string($view) || $view === '') {
            return [null, null];
        }

        $year = preg_match(self::YEAR, $view, $m) === 1 ? (int) $m[1] : null;

        $publisher = null;
        if (str_contains($view, ':')) {
            $afterColon = trim(explode(':', $view, 2)[1]);

            $clean = rtrim(preg_replace(self::YEAR, '', $afterColon) ?? $afterColon, ' ,.()');
            $publisher = trim($clean);
            if ($publisher === '') {
                $publisher = null;
            }
        }

        return [$year, $publisher];
    }

    /** @return array{string, string|null} */
    private static function inferTypeAndFormat(mixed $pubFormat, string $physical): array
    {
        $lower = mb_strtolower($physical, 'UTF-8');

        if ($pubFormat === 'ELECTRONIC') {
            foreach (self::AUDIO_KEYWORDS as $keyword) {
                if (str_contains($lower, $keyword)) {
                    return ['audio', 'audio'];
                }
            }

            return ['ebook', 'ebook'];
        }

        if (str_contains($lower, 'kietais viršeliais') || str_contains($lower, 'kieti viršeliai')) {
            return ['book', 'Kieti viršeliai'];
        }
        if (str_contains($lower, 'minkštais viršeliais') || str_contains($lower, 'minkšti viršeliai')) {
            return ['book', 'Minkšti viršeliai'];
        }

        return ['book', null];
    }

    private static function parseDimensions(?string $physical): ?string
    {
        if ($physical === null || $physical === '') {
            return null;
        }

        return preg_match(self::DIMENSIONS, $physical, $m) === 1 ? "{$m[1]} cm" : null;
    }

    /** @return ParsedItem */
    private static function emptyResult(): array
    {
        return [
            'title' => null, 'author' => null, 'isbn' => null, 'sku' => null,
            'publisher' => null, 'year' => null, 'format' => null,
            'price' => null, 'price_original' => null, 'in_stock' => null,
            'image_url' => null, 'categories' => [], 'description' => null,
            'pages' => null, 'cover_type' => null, 'duration' => null,
            'narrator' => null, 'translator' => null, 'schema_types' => [],
            'is_book_product' => false, 'book_score' => 0,
            'book_score_reasons' => [], 'type' => 'book',
            'planned_availability_date' => null, 'rating' => null,
            'review_count' => null,
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

    private static function nonEmptyString(mixed $value): ?string
    {
        $string = self::scalarString($value);

        return $string === null || $string === '' ? null : $string;
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

    private static function boolean(mixed $value): bool
    {
        return $value === true || $value === 1 || $value === '1';
    }

    private static function nonEmptyValue(mixed $value): mixed
    {
        return $value === null || $value === '' || $value === [] ? null : $value;
    }
}
