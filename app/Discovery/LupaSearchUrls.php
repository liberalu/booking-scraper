<?php

declare(strict_types=1);

namespace App\Discovery;

/**
 * URL and body helpers for the LupaSearch JSON discovery strategy.
 *
 * LupaSearch is a POST endpoint, but the queue stores URLs only. Every request
 * input is encoded into a synthetic URL's query string and the JSON body is
 * rebuilt from it — so a resumed run reissues the exact request the original
 * one sent, and the queue schema stays a list of strings.
 */
final class LupaSearchUrls
{
    /**
     * The site's own UI sorts this way. Replicating it keeps the result
     * ordering stable, so a resumed run sees the same items at the same
     * offsets.
     */
    private const DEFAULT_SORT = [
        ['in_stock' => 'desc'],
        ['in_store_only' => 'desc'],
        ['profit' => 'desc'],
        ['sku' => 'desc'],
    ];

    /**
     * @param list<string> $categoryIds
     * @param array<string, list<string>> $extraFilters
     */
    public static function buildSeedUrl(
        string $endpoint,
        array $categoryIds,
        int $pageSize,
        array $extraFilters = [],
    ): string {
        $params = [
            'offset' => '0',
            'limit' => (string) $pageSize,
            'category_ids' => implode(',', $categoryIds),
        ];
        // Sorted so the URL is identical between runs.
        $keys = array_keys($extraFilters);
        sort($keys, SORT_STRING);
        foreach ($keys as $key) {
            $params["f.{$key}"] = implode(',', $extraFilters[$key]);
        }

        return $endpoint . '?' . http_build_query($params);
    }

    /** @return array{0: int, 1: int} offset, limit */
    public static function parseOffsets(string $url): array
    {
        $params = QueryString::parse($url);

        return [(int) ($params['offset'] ?? 0), (int) ($params['limit'] ?? 42)];
    }

    /** The same URL with `offset` replaced. */
    public static function advance(string $url, int $newOffset): string
    {
        $params = QueryString::parse($url);
        $params['offset'] = (string) $newOffset;

        // offset/limit/category_ids first, then anything else in its original
        // order — matching how Python rebuilds the query string.
        $ordered = [];
        foreach (['offset', 'limit', 'category_ids'] as $key) {
            if (array_key_exists($key, $params)) {
                $ordered[$key] = $params[$key];
            }
        }
        foreach ($params as $key => $value) {
            if (!array_key_exists($key, $ordered)) {
                $ordered[$key] = $value;
            }
        }

        return self::withQuery($url, http_build_query($ordered));
    }

    /**
     * The POST body and headers for a synthetic URL.
     *
     * The query string is the source of truth, so this is the only place the
     * body shape lives — and a queued URL is enough to rebuild it.
     *
     * @return array{method: string, body: string, headers: array<string, string>}
     */
    public static function postRequest(string $url): array
    {
        $params = QueryString::parse($url);
        $offset = (int) ($params['offset'] ?? 0);
        $limit = (int) ($params['limit'] ?? 42);

        $filters = [
            'category_ids' => array_values(array_filter(
                explode(',', (string) ($params['category_ids'] ?? '')),
                static fn (string $part): bool => $part !== ''
            )),
        ];
        foreach ($params as $key => $value) {
            if (!str_starts_with((string) $key, 'f.')) {
                continue;
            }
            $flat = array_values(array_filter(
                explode(',', (string) $value),
                static fn (string $part): bool => $part !== ''
            ));
            if ($flat !== []) {
                $filters[substr((string) $key, 2)] = $flat;
            }
        }

        $body = [
            'searchText' => '',
            'offset' => $offset,
            'limit' => $limit,
            'sort' => self::DEFAULT_SORT,
            'filters' => $filters,
        ];

        return [
            'method' => 'POST',
            'body' => json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR),
            'headers' => [
                'Content-Type' => 'application/json',
                'Accept' => 'application/json',
                'Origin' => 'https://www.pegasas.lt',
                'Referer' => 'https://www.pegasas.lt/',
            ],
        ];
    }

    private static function withQuery(string $url, string $query): string
    {
        $parts = parse_url($url);
        $out = ($parts['scheme'] ?? 'https') . '://' . ($parts['host'] ?? '');
        if (isset($parts['port'])) {
            $out .= ':' . $parts['port'];
        }
        $out .= $parts['path'] ?? '';
        if ($query !== '') {
            $out .= '?' . $query;
        }
        if (isset($parts['fragment'])) {
            $out .= '#' . $parts['fragment'];
        }

        return $out;
    }
}
