<?php

declare(strict_types=1);

namespace BookScraper\Discovery;

/**
 * Query-string parsing that keeps the keys it was given.
 *
 * PHP's `parse_str` rewrites `.` and space in parameter names to `_`, so a
 * filter param like `f.publisher` comes back as `f_publisher` and the filter
 * silently disappears from the rebuilt request body. This splits by hand
 * instead.
 */
final class QueryString
{
    /** @return array<string, string> last value wins, as in parse_qs's [0] */
    public static function parse(string $url): array
    {
        $query = parse_url($url, PHP_URL_QUERY);
        if (!is_string($query) || $query === '') {
            return [];
        }

        $out = [];
        foreach (explode('&', $query) as $pair) {
            if ($pair === '') {
                continue;
            }
            [$key, $value] = array_pad(explode('=', $pair, 2), 2, '');
            $out[urldecode($key)] = urldecode((string) $value);
        }

        return $out;
    }
}
