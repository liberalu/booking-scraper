<?php

declare(strict_types=1);

namespace App\Parsers;

use App\Crawler\CrawlerTypes;

/**
 * @phpstan-import-type DiscoveryResult from CrawlerTypes
 */
interface DiscoveryParser
{
    /**
     * @param  (callable(string): string)|null  $fetchChild
     * @return list<string>
     */
    public static function parseSitemapUrls(string $content, ?callable $fetchChild = null): array;

    /** @return DiscoveryResult */
    public static function parseCategoryPage(string $content): array;
}
