<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Parsers\Vaga\Parser;
use PHPUnit\Framework\TestCase;

final class VagaParserDifferentialTest extends TestCase
{
    private const string FIXTURES = __DIR__.'/../fixtures';

    private const string GOLDEN = __DIR__.'/../golden';

    public function test_product_page_matches_python(): void
    {
        $this->assertMatchesGolden(
            'product',
            Parser::parseProductPage(self::fixture('vaga_product_page.html'))
        );
    }

    public function test_category_page_matches_python(): void
    {
        $this->assertMatchesGolden(
            'category',
            Parser::parseCategoryPage(self::fixture('vaga_category_page.html'))
        );
    }

    public function test_sitemap_matches_python(): void
    {
        $this->assertMatchesGolden(
            'sitemap',
            Parser::parseSitemapUrls(self::fixture('vaga_sitemap.xml'))
        );
    }

    private function assertMatchesGolden(string $name, mixed $actual): void
    {
        $golden = json_decode(
            (string) file_get_contents(self::GOLDEN."/{$name}.json"),
            true,
            flags: JSON_THROW_ON_ERROR
        );

        self::assertSame(self::sorted($golden), self::sorted($actual));
    }

    private static function sorted(mixed $value): mixed
    {
        if (! is_array($value)) {
            return $value;
        }
        $value = array_map([self::class, 'sorted'], $value);
        if (! array_is_list($value)) {
            ksort($value);
        }

        return $value;
    }

    private static function fixture(string $name): string
    {
        return (string) file_get_contents(self::FIXTURES.'/'.$name);
    }
}
