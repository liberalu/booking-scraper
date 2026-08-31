<?php

declare(strict_types=1);

namespace App\Discovery;

use DateTimeImmutable;

final class IbibliotekaApiUrls
{
    private const ENDPOINT = 'https://ibiblioteka.lt/metis-api/bibliographic-records'
        .'/public/detailed-search/page';

    /** @return list<string> */
    public static function buildSeedUrls(int $yearFrom, int $yearTo, int $pageSize): array
    {
        $urls = [];
        $current = new DateTimeImmutable(sprintf('%04d-01-01', $yearFrom));
        $end = new DateTimeImmutable(sprintf('%04d-01-01', $yearTo));
        while ($current < $end) {
            $next = $current->modify('first day of next month');
            $urls[] = self::ENDPOINT.'?'.http_build_query([
                'psi' => '0',
                'ps' => (string) $pageSize,
                'df' => $current->format('Y-m-d'),
                'dt' => $next->format('Y-m-d'),
            ]);
            $current = $next;
        }

        return $urls;
    }

    /** @return array{int, int, string, string} */
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

    public static function advance(string $url, int $newPsi): string
    {
        $params = QueryString::parse($url);
        $params['psi'] = (string) $newPsi;

        $ordered = [];

        foreach (['psi', 'ps', 'df', 'dt', 'yf', 'yt'] as $key) {
            if (array_key_exists($key, $params)) {
                $ordered[$key] = $params[$key];
            }
        }

        return explode('?', $url, 2)[0].'?'.http_build_query($ordered);
    }

    /** @return array{method: 'POST', body: string, headers: array<string, string>} */
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

    /** @return array<string, mixed> */
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
                'dateRange' => new \stdClass,
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
