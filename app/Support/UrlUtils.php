<?php

declare(strict_types=1);

namespace App\Support;

final class UrlUtils
{
    private const TRACKING_PREFIXES = ['utm_'];

    private const TRACKING_EXACT = [
        'fbclid', 'gclid', 'msclkid', 'mc_cid', 'mc_eid',
        '_ga', 'yclid', 'ref', 'ref_src', 'ref_url',
    ];

    public static function normalize(string $url): string
    {
        [$scheme, $authority, $path, $query] = self::split(trim($url));

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

    /** @return array{string, string, string, string} */
    private static function split(string $url): array
    {
        $pattern = '%^(?:([^:/?\#]+):)?(?://([^/?\#]*))?([^?\#]*)(?:\?([^\#]*))?%';
        if (preg_match($pattern, $url, $m) !== 1) {
            return ['', '', $url, ''];
        }

        return [$m[1], $m[2], $m[3], $m[4] ?? ''];
    }

    private static function collapseSlashes(string $path): string
    {
        if (! str_contains($path, '//')) {
            return $path;
        }

        return preg_replace('#/{2,}#', '/', $path) ?? $path;
    }

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
            $pairs[] = rawurlencode($key).'='.rawurlencode(urldecode($rawValue));
        }

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
                $out .= $scheme.':';
            }
            $out .= '//'.$netloc;
        } elseif ($scheme !== '') {
            $out .= $scheme.':';
        }
        $out .= $path;
        if ($query !== '') {
            $out .= '?'.$query;
        }

        return $out;
    }
}
