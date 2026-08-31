<?php

declare(strict_types=1);

namespace App\Parsers;

use App\Crawler\CrawlerTypes;

/** @phpstan-import-type ParsedItem from CrawlerTypes */
interface ProductParser
{
    /** @return ParsedItem */
    public static function parseProductPage(string $content): array;
}
