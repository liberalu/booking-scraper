<?php

declare(strict_types=1);

namespace BookScraper\Ibiblioteka;

/**
 * Port of book_scraper/spiders/ibiblioteka/parsers.py.
 *
 * The Lithuanian National Library (LIBIS) JSON API. Unlike every other
 * source here this is not a shop: it emits CANONICAL bibliographic records,
 * tagged `_emit_as: "book"` so the scan spider builds a BookItem instead of
 * a ShopBookItem. There are no prices.
 *
 * Person roles use UNIMARC relator codes.
 */
final class Parser
{
    private const COVER_BASE = 'https://ibiblioteka.lt';

    private const DETAIL_PATH = '/metis-api/bibliographic-records/public/';

    /** UNIMARC relator code => our role name. */
    private const ROLE_CODES = [
        '070' => 'author',
        '080' => 'author',
        '730' => 'translator',
        '550' => 'narrator',
        '440' => 'illustrator',
        '340' => 'editor',
        '220' => 'compiler',
    ];

    /** Page count in the physical description: "312 p." / "312 psl." */
    private const PAGES = '/(\d+)\s*(?:p\b|psl\.)/u';

    /** Audiobook duration: "9 val., 25 min., 1 sek." */
    private const DURATION = '/\d+\s*(?:val|min|sek)\.?(?:[^)]*)/u';

    private const YEAR = '/\b(1[89]\d{2}|20\d{2})\b/';

    private const DIMENSIONS = '/(\d+)\s*cm/u';

    /** Physical-description keywords that mean an audio file, not an e-book. */
    private const AUDIO_KEYWORDS = ['mp3', 'audio', 'val.,', 'min.,'];

    // --------------------------------------------------------------- search

    /**
     * A POST /detailed-search response.
     *
     * Carries everything extractable from the listing — title, year,
     * publisher (parsed out of publicationView), format, LIBIS code as SKU —
     * so records appear without waiting for the scan phase, which later adds
     * authors, ISBNs and covers from the detail endpoint.
     *
     * @return array{products: list<array<string, mixed>>, total: null}
     */
    public static function parseSearchResponse(string $json): array
    {
        $data = json_decode($json, true);
        if (!is_array($data)) {
            return ['products' => [], 'total' => null];
        }

        $items = $data['results']['content'] ?? [];
        if (!is_array($items)) {
            return ['products' => [], 'total' => null];
        }

        $products = [];
        foreach ($items as $item) {
            if (!is_array($item)) {
                continue;
            }
            $id = $item['id'] ?? null;
            if ($id === null || $id === '' || $id === 0) {
                continue;
            }

            [$year, $publisher] = self::parsePublicationView($item['publicationView'] ?? '');
            [$bookType, $bookFormat] = self::inferTypeAndFormat($item['publicationFormat'] ?? null, '');

            $products[] = [
                'url' => self::COVER_BASE . self::DETAIL_PATH . $id,
                'title' => ($item['titleView'] ?? null) ?: (($item['titleFull'] ?? null) ?: null),
                'sku' => ($item['code'] ?? null) ?: null,
                'year' => $year,
                'publisher' => $publisher,
                'type' => $bookType,
                'format' => $bookFormat,
                // The national library is authoritative — no scoring needed.
                'is_book_product' => true,
                'book_score' => 5,
            ];
        }

        return ['products' => $products, 'total' => null];
    }

    /** Alias matching the shop-parser contract used by the registry. */
    public static function parseCategoryPage(string $json): array
    {
        return self::parseSearchResponse($json);
    }

    /** LIBIS has no sitemap; discovery goes through the search API. */
    public static function parseSitemapUrls(string $xml): array
    {
        return [];
    }

    // --------------------------------------------------------------- detail

    /**
     * Ask for JSON explicitly.
     *
     * The endpoint content-negotiates: with a browser `Accept` it serves the
     * SPA shell (30,995 bytes of xhtml), and with `application/json` the
     * record (19,593 bytes). Measured on record 2097094, 2026-08-25.
     *
     * Python shipped without this hook, so its download handler's
     * HTML-preferring `Accept` stood and every scan fetch returned 200 with a
     * shell the parser found no title in — a run that reported `completed`
     * having scraped nothing, and the reason ibiblioteka has no production
     * rows. Python now carries the same hook; the two agree.
     *
     * The URL is returned unchanged — only the header matters here.
     *
     * @return array{url: string, headers: array<string, string>}
     */
    public static function rewriteScanUrl(string $url): array
    {
        return ['url' => $url, 'headers' => ['Accept' => 'application/json']];
    }

    /**
     * A GET /bibliographic-records/public/{id} response.
     *
     * Returns a BookItem-shaped array tagged `_emit_as: "book"`.
     *
     * @return array<string, mixed>
     */
    public static function parseProductPage(string $json): array
    {
        $raw = json_decode($json, true);
        if (!is_array($raw)) {
            return self::emptyResult();
        }

        $physical = (string) ($raw['allPhysicalAttributes'] ?? '');
        $pubFormat = $raw['publicationFormat'] ?? null;
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

        $cover = $raw['coverUrl'] ?? null;
        if (is_string($cover) && str_starts_with($cover, '/')) {
            $cover = self::COVER_BASE . $cover;
        }

        $year = null;
        if (is_string($raw['publicationDate'] ?? null)
            && preg_match(self::YEAR, $raw['publicationDate'], $m) === 1) {
            $year = (int) $m[1];
        }

        $isbns = [];
        foreach (is_array($raw['isbn'] ?? null) ? $raw['isbn'] : [] as $rawIsbn) {
            if (!is_string($rawIsbn) || $rawIsbn === '') {
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
            ? ($languages[0]['code'] ?? null)
            : null;

        $translatedFrom = [];
        foreach (is_array($raw['translatedFromLanguages'] ?? null) ? $raw['translatedFromLanguages'] : [] as $lang) {
            if (is_array($lang) && ($lang['code'] ?? null) !== null) {
                $translatedFrom[] = $lang['code'];
            }
        }

        $audienceRaw = is_array($raw['audience'] ?? null) ? $raw['audience'] : [];
        $audience = isset($audienceRaw[0]) && is_array($audienceRaw[0])
            ? ($audienceRaw[0]['nameLt'] ?? null)
            : null;

        $rateAverage = $raw['rateAverage'] ?? null;
        $rateNumber = $raw['rateNumber'] ?? null;

        return [
            '_emit_as' => 'book',
            '_part_urls' => self::partUrls($raw),
            'is_book_product' => true,
            'book_score' => 5,
            'book_score_reasons' => [['reason' => 'ibiblioteka_national_library']],
            'data_source' => 'ibiblioteka',
            'libis_code' => $raw['code'] ?? null,
            'title' => ($raw['title'] ?? null) ?: null,
            'title_full' => ($raw['titleFull'] ?? null) ?: null,
            'year' => $year,
            'publisher' => ($raw['publisher'] ?? null) ?: null,
            'series' => ($raw['seriesView'] ?? null) ?: null,
            'release_place' => ($raw['releasePlace'] ?? null) ?: null,
            'type' => $bookType,
            'format' => $pubFormat,
            'pages' => $pages,
            'duration' => $duration,
            'dimensions' => self::parseDimensions($physical),
            'language' => $language,
            'translated_from' => $translatedFrom === [] ? null : $translatedFrom,
            'description' => ($raw['summary'] ?? null) ?: null,
            'cover_url' => $cover,
            'upcoming_release' => (bool) ($raw['upcomingRelease'] ?? false),
            'udc_codes' => ($raw['udcSubjectsCodes'] ?? null) ?: null,
            'subjects' => ($raw['rubricSubjectView'] ?? null) ?: null,
            'audience' => $audience,
            'libis_rating' => $rateAverage ? (float) $rateAverage : null,
            'libis_review_count' => $rateNumber ? (int) $rateNumber : null,
            'isbns' => $isbns,
            'authors' => self::extractAuthors($raw),
        ];
    }

    /**
     * Detail URLs for each volume of a multipart work.
     *
     * A multipart record ("Ana Karenina T.1 + T.2") carries only the set-level
     * ISBN; per-volume ISBNs appear solely on the part records. Without
     * following them the canonical table has no volume-level ISBN, so a shop
     * listing for a single volume can never match. The scan spider queues
     * these as separate items.
     *
     * @param  array<string, mixed>  $raw
     * @return list<string>
     */
    private static function partUrls(array $raw): array
    {
        $parts = is_array($raw['parts'] ?? null) ? $raw['parts'] : [];
        if (!($raw['multipart'] ?? false) || $parts === []) {
            return [];
        }

        $urls = [];
        foreach ($parts as $part) {
            $code = is_array($part) ? ($part['code'] ?? null) : null;
            if ($code !== null && $code !== '') {
                $urls[] = self::COVER_BASE . self::DETAIL_PATH . $code;
            }
        }

        return $urls;
    }

    /**
     * Contributors with role and per-role position.
     *
     * Two sources: `authorViews` (primary authors) and `persons[]`, which
     * carries multi-role contributors via UNIMARC type codes. Deduped on
     * (role, code) so a person listed in both appears once per role.
     *
     * @param  array<string, mixed>  $raw
     * @return list<array<string, mixed>>
     */
    private static function extractAuthors(array $raw): array
    {
        $out = [];
        $seen = [];
        $rolePosition = [];

        foreach (is_array($raw['authorViews'] ?? null) ? $raw['authorViews'] : [] as $view) {
            if (!is_array($view)) {
                continue;
            }
            // LIBIS renamed the name field to `titleLt`; `value`/`name` are kept
            // as fallbacks because the fixtures predate that rename.
            $name = ($view['titleLt'] ?? null) ?: ($view['value'] ?? null);
            if ($name === null || $name === '') {
                continue;
            }
            $code = $view['code'] ?? null;
            $key = 'author|' . ($code ?: $name);
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $position = $rolePosition['author'] ?? 0;
            $out[] = ['name' => $name, 'libis_code' => $code, 'role' => 'author', 'position' => $position];
            $rolePosition['author'] = $position + 1;
        }

        foreach (is_array($raw['persons'] ?? null) ? $raw['persons'] : [] as $person) {
            if (!is_array($person)) {
                continue;
            }
            $name = ($person['titleLt'] ?? null) ?: ($person['name'] ?? null);
            if ($name === null || $name === '') {
                continue;
            }
            $code = $person['code'] ?? null;

            foreach (is_array($person['types'] ?? null) ? $person['types'] : [] as $type) {
                $role = self::ROLE_CODES[is_array($type) ? ($type['code'] ?? '') : ''] ?? null;
                if ($role === null) {
                    continue;
                }
                $key = $role . '|' . ($code ?: $name);
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

    // -------------------------------------------------------------- helpers

    /**
     * "Place : Publisher, Year" -> (year, publisher).
     *
     * @return array{0: int|null, 1: string|null}
     */
    private static function parsePublicationView(mixed $view): array
    {
        if (!is_string($view) || $view === '') {
            return [null, null];
        }

        $year = preg_match(self::YEAR, $view, $m) === 1 ? (int) $m[1] : null;

        $publisher = null;
        if (str_contains($view, ':')) {
            $afterColon = trim(explode(':', $view, 2)[1]);
            // Drop the year, then the punctuation it left behind.
            $clean = rtrim(preg_replace(self::YEAR, '', $afterColon) ?? $afterColon, " ,.()");
            $publisher = trim($clean) ?: null;
        }

        return [$year, $publisher];
    }

    /**
     * LIBIS publicationFormat + physical description -> (type, format).
     *
     * ELECTRONIC covers both audio and e-books, distinguished only by the
     * physical description mentioning an audio file or a duration.
     *
     * @return array{0: string, 1: string|null}
     */
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

        // PRINTED, or anything unrecognised: read the binding out of the
        // physical description when it says so.
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

    /** @return array<string, mixed> */
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
}
