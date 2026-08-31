<?php

declare(strict_types=1);

namespace App\Parsers;

use App\Crawler\CrawlerTypes;

/** @phpstan-import-type DiscoveryResult from CrawlerTypes */
interface IbibliotekaSearchParser
{
    /** @return DiscoveryResult */
    public static function parseSearchResponse(string $content): array;
}
