<?php

declare(strict_types=1);

namespace BookScraper\Tests;

use BookScraper\Patogupirkti\Parser;
use PHPUnit\Framework\TestCase;

/**
 * patogupirkti is Magento 1: category cards carry an inline
 * `product_tracking_data` blob, product pages use schema.org microdata plus
 * a spec table. Two product templates exist — the legacy one leans on the
 * spec table where the newer carries microdata — so both are compared.
 */
final class PatogupirktiParserDifferentialTest extends TestCase
{
    private const FIXTURES = __DIR__ . '/../../tests/fixtures/patogupirkti';
    private const GOLDEN = __DIR__ . '/golden';

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

    // ---------------------------------------------------------- sitemap index

    public function test_a_sitemap_index_recurses_only_into_product_children(): void
    {
        // The index also lists category/page/author/serial/manufacturer
        // children; following those would flood discovery with non-products.
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
        // The caller owns the HTTP; without a fetcher there is nothing to read.
        self::assertSame([], Parser::parseSitemapUrls(self::fixture('sitemap_index.xml')));
    }

    public function test_malformed_xml_yields_no_urls(): void
    {
        self::assertSame([], Parser::parseSitemapUrls('<not-xml'));
        self::assertSame([], Parser::parseSitemapUrls(''));
    }

    // ----------------------------------------------------------- card details

    public function test_discounted_cards_carry_both_prices(): void
    {
        $products = Parser::parseCategoryPage(self::fixture('category_page.html'))['products'];

        $discounted = array_values(array_filter(
            $products,
            static fn (array $p): bool => $p['price_original'] !== null
        ));
        self::assertNotEmpty($discounted, 'fixture should contain a discounted card');

        foreach ($discounted as $product) {
            // The displayed price must be the lower of the two, or the
            // discount labelling is inverted.
            self::assertLessThan(
                (float) $product['price_original'],
                (float) $product['price'],
                "discount inverted for {$product['url']}"
            );
        }
    }

    public function test_every_card_keeps_its_magento_id(): void
    {
        // The id is the join key back to the tracking blob, and the only
        // stable identifier a card exposes.
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
        // "Pirmas" appears on every product and the last crumb is the product
        // itself; keeping either would pollute the classifier's category
        // signal.
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

    // -------------------------------------------------------------- helpers

    private function assertMatchesGolden(string $name, mixed $actual): void
    {
        $golden = json_decode(
            (string) file_get_contents(self::GOLDEN . "/{$name}.json"),
            true,
            flags: JSON_THROW_ON_ERROR
        );

        self::assertSame(self::sorted($golden), self::sorted($actual));
    }

    private static function sorted(mixed $value): mixed
    {
        if (!is_array($value)) {
            return $value;
        }
        $value = array_map([self::class, 'sorted'], $value);
        if (!array_is_list($value)) {
            ksort($value);
        }

        return $value;
    }

    private static function fixture(string $name): string
    {
        return (string) file_get_contents(self::FIXTURES . '/' . $name);
    }
}
