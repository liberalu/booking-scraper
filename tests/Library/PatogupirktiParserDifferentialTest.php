<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Parsers\Patogupirkti\Parser;
use PHPUnit\Framework\TestCase;

final class PatogupirktiParserDifferentialTest extends TestCase
{
    private const FIXTURES = __DIR__.'/../fixtures/patogupirkti';

    private const GOLDEN = __DIR__.'/../golden';

    public function test_category_page_matches_python(): void
    {
        $this->assertMatchesGolden(
            'patogu_category',
            Parser::parseCategoryPage(self::fixture('category_page.html'))
        );
    }

    public function test_product_page_matches_python(): void
    {
        $this->assertMatchesGolden(
            'patogu_product',
            Parser::parseProductPage(self::fixture('product_page.html'))
        );
    }

    public function test_alternate_product_template_matches_python(): void
    {
        $this->assertMatchesGolden(
            'patogu_product_alt',
            Parser::parseProductPage(self::fixture('product_page_alt.html'))
        );
    }

    public function test_urlset_sitemap_matches_python(): void
    {
        $this->assertMatchesGolden(
            'patogu_sitemap',
            Parser::parseSitemapUrls(self::fixture('sitemap_product.xml'))
        );
    }

    public function test_a_sitemap_index_recurses_only_into_product_children(): void
    {

        $fetched = [];
        $urls = Parser::parseSitemapUrls(
            self::fixture('sitemap_index.xml'),
            function (string $url) use (&$fetched): string {
                $fetched[] = $url;

                return self::fixture('sitemap_product.xml');
            }
        );

        self::assertNotEmpty($fetched, 'the index should have been followed');
        foreach ($fetched as $url) {
            self::assertStringContainsString('sitemap_product', $url);
        }
        self::assertNotEmpty($urls);
    }

    public function test_a_sitemap_index_without_a_fetcher_yields_nothing(): void
    {

        self::assertSame([], Parser::parseSitemapUrls(self::fixture('sitemap_index.xml')));
    }

    public function test_malformed_xml_yields_no_urls(): void
    {
        self::assertSame([], Parser::parseSitemapUrls('<not-xml'));
        self::assertSame([], Parser::parseSitemapUrls(''));
    }

    public function test_discounted_cards_carry_both_prices(): void
    {
        $products = Parser::parseCategoryPage(self::fixture('category_page.html'))['products'];

        $discounted = array_values(array_filter(
            $products,
            static fn (array $p): bool => $p['price_original'] !== null
        ));
        self::assertNotEmpty($discounted, 'fixture should contain a discounted card');

        foreach ($discounted as $product) {

            self::assertLessThan(
                (float) $product['price_original'],
                (float) $product['price'],
                "discount inverted for {$product['url']}"
            );
        }
    }

    public function test_every_card_keeps_its_magento_id(): void
    {

        foreach (Parser::parseCategoryPage(self::fixture('category_page.html'))['products'] as $product) {
            self::assertArrayHasKey('magento_id', $product['properties']);
            self::assertMatchesRegularExpression('/^\d+$/', $product['properties']['magento_id']);
        }
    }

    public function test_total_is_null_so_pagination_chains(): void
    {
        self::assertNull(Parser::parseCategoryPage(self::fixture('category_page.html'))['total']);
    }

    public function test_the_breadcrumb_root_and_product_leaf_are_dropped(): void
    {

        $categories = Parser::parseProductPage(self::fixture('product_page.html'))['categories'];

        foreach ($categories as $category) {
            self::assertNotSame('pirmas', mb_strtolower($category, 'UTF-8'));
        }
        self::assertNotContains('Pelynų medus. Mano istorija', $categories);
    }

    public function test_the_isbn_doubles_as_the_sku(): void
    {
        $result = Parser::parseProductPage(self::fixture('product_page.html'));

        self::assertNotNull($result['isbn']);
        self::assertSame($result['isbn'], $result['sku']);
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
