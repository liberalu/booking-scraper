<?php

declare(strict_types=1);

namespace BookScraper;

/**
 * Port of book_scraper/url_utils.py.
 *
 * Canonical form is what `uq_shop_book_shop_url` and
 * `uq_discovered_urls_shop_normalized` are enforced on, so this must agree
 * with the Python character for character — a divergence would split one
 * product across two rows.
 */
final class UrlUtils
{
    private const TRACKING_PREFIXES = ['utm_'];

    private const TRACKING_EXACT = [
        'fbclid', 'gclid', 'msclkid', 'mc_cid', 'mc_eid',
        '_ga', 'yclid', 'ref', 'ref_src', 'ref_url',
    ];

    /**
     * Lowercases scheme+host, drops the fragment, strips tracking params,
     * collapses duplicate slashes, trims a trailing slash (except root).
     * Path case is preserved: shops often treat paths as case-sensitive.
     */
    public static function normalize(string $url): string
    {
        [$scheme, $authority, $path, $query] = self::split(trim($url));

        // Python lowercases the whole netloc: userinfo, host and port.
        $scheme = strtolower($scheme);
        $authority = strtolower($authority);

        $path = self::collapseSlashes($path);
        if ($path === '') {
            $path = '/';
        }
        if (strlen($path) > 1 && str_ends_with($path, '/')) {
            $path = rtrim($path, '/');
        }

        return self::unsplit($scheme, $authority, $path, self::filterQuery($query));
    }

    /**
     * RFC 3986 Appendix B split, equivalent to Python's urlsplit().
     *
     * Deliberately NOT parse_url(): that function corrupts non-ASCII bytes
     * in the path, substituting '_' — `/asmeninis-tobulėjimas` comes back
     * as `/asmeninis-tobul\xc4_jimas`. Most of the catalogue has Lithuanian
     * diacritics in its slugs, so parse_url would produce a wrong
     * `normalized_url` for the majority of rows and defeat the very
     * uniqueness constraints this function backs. This regex is byte-safe.
     *
     * @return array{0: string, 1: string, 2: string, 3: string}
     */
    private static function split(string $url): array
    {
        $pattern = '%^(?:([^:/?\#]+):)?(?://([^/?\#]*))?([^?\#]*)(?:\?([^\#]*))?%';
        if (preg_match($pattern, $url, $m) !== 1) {
            return ['', '', $url, ''];
        }

        return [$m[1] ?? '', $m[2] ?? '', $m[3] ?? '', $m[4] ?? ''];
    }

    private static function collapseSlashes(string $path): string
    {
        if (!str_contains($path, '//')) {
            return $path;
        }

        return preg_replace('#/{2,}#', '/', $path) ?? $path;
    }

    /**
     * Mirrors parse_qsl(keep_blank_values=True) + urlencode: blank values
     * are kept (as `k=`), and ordering follows the original query.
     */
    private static function filterQuery(string $query): string
    {
        if ($query === '') {
            return '';
        }

        $pairs = [];
        foreach (explode('&', $query) as $chunk) {
            if ($chunk === '') {
                continue;
            }
            [$rawKey, $rawValue] = array_pad(explode('=', $chunk, 2), 2, '');
            $key = urldecode($rawKey);
            if ($key === '' || self::isTracking($key)) {
                continue;
            }
            $pairs[] = rawurlencode($key) . '=' . rawurlencode(urldecode($rawValue));
        }

        // urlencode() uses quote_plus: space becomes '+', not '%20'.
        return str_replace('%20', '+', implode('&', $pairs));
    }

    private static function isTracking(string $key): bool
    {
        $lower = strtolower($key);
        foreach (self::TRACKING_PREFIXES as $prefix) {
            if (str_starts_with($lower, $prefix)) {
                return true;
            }
        }

        return in_array($lower, self::TRACKING_EXACT, true);
    }

    private static function unsplit(string $scheme, string $netloc, string $path, string $query): string
    {
        $out = '';
        if ($netloc !== '' || str_starts_with($path, '//')) {
            if ($scheme !== '') {
                $out .= $scheme . ':';
            }
            $out .= '//' . $netloc;
        } elseif ($scheme !== '') {
            $out .= $scheme . ':';
        }
        $out .= $path;
        if ($query !== '') {
            $out .= '?' . $query;
        }

        return $out;
    }
}
