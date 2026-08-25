<?php

declare(strict_types=1);

namespace BookScraper\Discovery;

use DateTimeImmutable;

/**
 * URL and body helpers for the ibiblioteka.lt national-library JSON API.
 *
 * A POST endpoint, encoded into synthetic URLs the same way LupaSearch is, so
 * the queue can store and resume them as plain strings.
 *
 * Two details are load-bearing:
 *
 *  * The bare `…/detailed-search` path answers 405 to POST since 2026-06;
 *    paginated results live at `…/detailed-search/page`.
 *  * `selectedFilters` must carry its full key set or the endpoint returns
 *    400 — an empty list per key is required, not omission.
 *
 * Bands are monthly, not annual: the API caps a search at pageStartIndex
 * ~9,900, and high-volume years exceed that, so annual bands would silently
 * drop books off the end.
 */
final class IbibliotekaApiUrls
{
    private const ENDPOINT = 'https://ibiblioteka.lt/metis-api/bibliographic-records'
        . '/public/detailed-search/page';

    /** One seed per calendar month in [yearFrom, yearTo), each at psi=0.
     *
     * @return list<string>
     */
    public static function buildSeedUrls(int $yearFrom, int $yearTo, int $pageSize): array
    {
        $urls = [];
        $current = new DateTimeImmutable(sprintf('%04d-01-01', $yearFrom));
        $end = new DateTimeImmutable(sprintf('%04d-01-01', $yearTo));
        while ($current < $end) {
            $next = $current->modify('first day of next month');
            $urls[] = self::ENDPOINT . '?' . http_build_query([
                'psi' => '0',
                'ps' => (string) $pageSize,
                'df' => $current->format('Y-m-d'),
                'dt' => $next->format('Y-m-d'),
            ]);
            $current = $next;
        }

        return $urls;
    }

    /**
     * Accepts the current df/dt form and the legacy yf/yt one, so URLs queued
     * before the switch to monthly bands still resolve.
     *
     * @return array{0: int, 1: int, 2: string, 3: string} psi, ps, from, to
     */
    public static function parseParams(string $url): array
    {
        $params = QueryString::parse($url);
        $psi = (int) ($params['psi'] ?? 0);
        $ps = (int) ($params['ps'] ?? 100);

        if (isset($params['df'], $params['dt'])) {
            return [$psi, $ps, $params['df'], $params['dt']];
        }
        $yearFrom = (int) ($params['yf'] ?? 2020);
        $yearTo = (int) ($params['yt'] ?? 2021);

        return [$psi, $ps, sprintf('%04d-01-01', $yearFrom), sprintf('%04d-01-01', $yearTo)];
    }

    /** The same URL with `psi` replaced. */
    public static function advance(string $url, int $newPsi): string
    {
        $params = QueryString::parse($url);
        $params['psi'] = (string) $newPsi;

        $ordered = [];
        // Whichever date-range form the original carried is preserved.
        foreach (['psi', 'ps', 'df', 'dt', 'yf', 'yt'] as $key) {
            if (array_key_exists($key, $params)) {
                $ordered[$key] = $params[$key];
            }
        }

        return explode('?', $url, 2)[0] . '?' . http_build_query($ordered);
    }

    /**
     * @return array{method: string, body: string, headers: array<string, string>}
     */
    public static function postRequest(string $url): array
    {
        [$psi, $ps, $from, $to] = self::parseParams($url);

        $body = self::fixedBody();
        $body['pageStartIndex'] = $psi;
        $body['pageSize'] = $ps;
        $body['publicationDateRange'] = [
            'from' => "{$from}T00:00:00.000Z",
            'to' => "{$to}T00:00:00.000Z",
        ];
        // No language filter: ibiblioteka catalogues every language published
        // in Lithuania, and the shops sell those books too.
        $body['languages'] = [];

        return [
            'method' => 'POST',
            'body' => json_encode(
                $body,
                JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR
            ),
            'headers' => [
                'Content-Type' => 'application/json',
                'Accept' => 'application/json, text/plain, */*',
                'Accept-Language' => 'en-GB,en;q=0.5',
            ],
        ];
    }

    /**
     * Static fields every search sends. `dateRange` is an object, not a list —
     * json_encode would emit `[]` for an empty PHP array and the endpoint
     * rejects that.
     *
     * @return array<string, mixed>
     */
    private static function fixedBody(): array
    {
        return [
            'hierarchicalListMode' => false,
            'selectedFilters' => [
                'audiences' => [],
                'authors' => [],
                'languages' => [],
                'typeFilter' => [],
                'subjects' => [],
                'sources' => [],
                'libraries' => [],
                'releaseStatus' => [],
                'rateAverages' => [],
                'accessibleOnline' => [],
                'accessiblePublications' => [],
                'accessibilityFeatures' => [],
                'mediaProperties' => [],
                'recordStatuses' => [],
                'dateRange' => new \stdClass(),
            ],
            'searchFields' => [],
            'librariesData' => [
                [
                    'bookReceivedDateTypeEnumLastTwoWeeks' => false,
                    'bookReceivedDateTypeEnumLastMonth' => false,
                    'bookReceivedDateTypeEnumLastThreeMonths' => false,
                    'bookReceivedDateTypeEnumLastSixMonths' => false,
                    'bookReceivedDateTypeEnumLastYear' => false,
                    'bookReceivedDateTypes' => [],
                ],
            ],
            'publicationTypes' => ['BOOK'],
            'publicationAttributes' => [],
            'serialPublicationTypes' => [],
            'publicationFormats' => [],
            'rubricSubjects' => [],
            'audiences' => [],
            'udcSubjects' => [],
            'articleSubjects' => [],
            'publicationCountries' => [],
            'translateFromLanguages' => [],
            'page' => 0,
            'sortBy' => 'MATCH',
            'recentlySearchedByFilters' => false,
            'accessiblePublications' => [],
            'accessibilityType' => [],
            'informationAccessibilityMethod' => [],
            'accessibilityFeatures' => [],
            'accessibilityHazards' => [],
            'contentManagement' => [],
        ];
    }
}
