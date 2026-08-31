<?php

declare(strict_types=1);

namespace App\Parsers;

interface ScanUrlRewriter
{
    /** @return array{url: string, headers: array<string, string>}|null */
    public static function rewriteScanUrl(string $url): ?array;
}
