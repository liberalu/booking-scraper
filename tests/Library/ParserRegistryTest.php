<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Support\ParserRegistry;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;
use RuntimeException;

final class ParserRegistryTest extends TestCase
{
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

        foreach (['parseSitemapUrls', 'parseCategoryPage', 'parseProductPage'] as $method) {
            self::assertTrue(
                ParserRegistry::supports($shop, $method),
                "{$shop} is missing {$method}()"
            );
        }
    }

    public function test_the_registry_matches_the_configured_shops(): void
    {

        $configured = array_map(
            static fn (string $path): string => basename($path, '.toml'),
            glob(__DIR__.'/../../config/shops/*.toml') ?: []
        );
        sort($configured);

        $registered = ParserRegistry::shops();
        sort($registered);

        self::assertSame($configured, $registered);
    }

    public function test_an_unknown_shop_names_what_does_exist(): void
    {
        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessageMatches('/known shops:.*vaga/');

        ParserRegistry::for('not-a-shop');
    }

    public function test_pegasas_exposes_its_scan_url_rewrite(): void
    {

        self::assertTrue(ParserRegistry::supports('pegasas', 'rewriteScanUrl'));
        self::assertFalse(ParserRegistry::supports('vaga', 'rewriteScanUrl'));
    }
}
