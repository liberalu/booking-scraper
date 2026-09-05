<?php

declare(strict_types=1);

namespace App\Support;

use InvalidArgumentException;

final class CrawlerUrlPolicy
{
    public const int MAX_URLS = 5000;

    /** @return list<string> */
    public static function parse(string $value, string $baseUrl): array
    {
        $urls = array_values(array_filter(
            array_map(trim(...), explode(',', $value)),
            static fn (string $url): bool => $url !== '',
        ));
        if (count($urls) > self::MAX_URLS) {
            throw new InvalidArgumentException('No more than '.self::MAX_URLS.' explicit URLs are allowed.');
        }

        foreach ($urls as $url) {
            self::assertAllowed($url, $baseUrl);
        }

        return $urls;
    }

    public static function assertAllowed(string $url, string $baseUrl): void
    {
        $parts = parse_url($url);
        $base = parse_url($baseUrl);
        if ($parts === false || $base === false) {
            throw new InvalidArgumentException('The crawl URL is invalid.');
        }

        $scheme = strtolower(is_string($parts['scheme'] ?? null) ? $parts['scheme'] : '');
        $host = strtolower(rtrim(is_string($parts['host'] ?? null) ? $parts['host'] : '', '.'));
        $baseHost = strtolower(rtrim(is_string($base['host'] ?? null) ? $base['host'] : '', '.'));

        if (! in_array($scheme, ['http', 'https'], true) || $host === '' || $host !== $baseHost) {
            throw new InvalidArgumentException("The crawl URL must use the configured shop host {$baseHost}.");
        }
        if (isset($parts['user']) || isset($parts['pass'])) {
            throw new InvalidArgumentException('Crawl URLs cannot contain credentials.');
        }
        if (filter_var($host, FILTER_VALIDATE_IP) !== false) {
            throw new InvalidArgumentException('IP-address crawl targets are not allowed.');
        }

        $port = $parts['port'] ?? null;
        $expectedPort = $base['port'] ?? null;
        if ($port !== $expectedPort) {
            throw new InvalidArgumentException('The crawl URL must use the configured shop port.');
        }
    }
}
