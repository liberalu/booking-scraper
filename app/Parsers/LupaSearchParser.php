<?php

declare(strict_types=1);

namespace App\Parsers;

use App\Crawler\CrawlerTypes;

/** @phpstan-import-type DiscoveryResult from CrawlerTypes */
interface LupaSearchParser
{
    /** @return DiscoveryResult */
    public static function parseLupasearchResponse(string $content): array;
}
