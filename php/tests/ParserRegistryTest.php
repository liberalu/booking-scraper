<?php

declare(strict_types=1);

namespace BookScraper\Tests;

use BookScraper\ParserRegistry;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;
use RuntimeException;

/**
 * Every shop the Python side has a parser module for must resolve here, or
 * the generic spiders silently cannot crawl it.
 */
final class ParserRegistryTest extends TestCase
{
    /** @return list<array{0: string}> */
    public static function shops(): array
    {
        return array_map(
            static fn (string $shop): array => [$shop],
            ['vaga', 'pegasas', 'patogupirkti', 'humanitas', 'almalittera', 'ibiblioteka']
        );
    }

    #[DataProvider('shops')]
    public function test_every_shop_resolves(string $shop): void
    {
        self::assertTrue(ParserRegistry::has($shop));
        self::assertTrue(class_exists(ParserRegistry::for($shop)));
    }

    #[DataProvider('shops')]
    public function test_every_parser_exposes_the_core_contract(string $shop): void
    {
        // The generic spiders call these three by name on every shop.
        foreach (['parseSitemapUrls', 'parseCategoryPage', 'parseProductPage'] as $method) {
            self::assertTrue(
                ParserRegistry::supports($shop, $method),
                "{$shop} is missing {$method}()"
            );
        }
    }

    public function test_the_registry_matches_the_python_parser_modules(): void
    {
        // Drift here means a shop exists on one side only.
        $pythonShops = array_values(array_filter(
            array_map('basename', glob(__DIR__ . '/../../book_scraper/spiders/*', GLOB_ONLYDIR) ?: []),
            static fn (string $dir): bool => is_file(
                __DIR__ . "/../../book_scraper/spiders/{$dir}/parsers.py"
            )
        ));
        sort($pythonShops);

        $phpShops = ParserRegistry::shops();
        sort($phpShops);

        self::assertSame($pythonShops, $phpShops);
    }

    public function test_an_unknown_shop_names_what_does_exist(): void
    {
        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessageMatches('/known shops:.*vaga/');

        ParserRegistry::for('not-a-shop');
    }

    public function test_pegasas_exposes_its_scan_url_rewrite(): void
    {
        // Only pegasas needs it: its product pages are a React shell, so the
        // scan URL is swapped for a single-SKU GraphQL query.
        self::assertTrue(ParserRegistry::supports('pegasas', 'rewriteScanUrl'));
        self::assertFalse(ParserRegistry::supports('vaga', 'rewriteScanUrl'));
    }
}
