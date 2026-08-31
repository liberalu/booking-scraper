<?php

declare(strict_types=1);

namespace App\Discovery;

final class QueryString
{
    /** @return array<string, string> */
    public static function parse(string $url): array
    {
        $query = parse_url($url, PHP_URL_QUERY);
        if (! is_string($query) || $query === '') {
            return [];
        }

        $out = [];
        foreach (explode('&', $query) as $pair) {
            if ($pair === '') {
                continue;
            }
            [$key, $value] = array_pad(explode('=', $pair, 2), 2, '');
            $out[urldecode($key)] = urldecode($value);
        }

        return $out;
    }
}
