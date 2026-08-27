<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Parsers\Humanitas\Parser;
use PHPUnit\Framework\TestCase;

/**
 * humanitas sits behind a Cloudflare Managed Challenge, so every fetch goes
 * through FlareSolverr — but the parsing is ordinary HTML and compares
 * directly against the Python golden.
 */
final class HumanitasParserDifferentialTest extends TestCase
{
    private const FIXTURES = __DIR__ . '/../../fixtures/humanitas';
    private const GOLDEN = __DIR__ . '/golden';

    public function test_index_page_urls_match_python(): void
    {
        $this->assertMatchesGolden(
            'humanitas_index',
            Parser::parseSitemapUrls(self::fixture('index_page.html'))
        );
    }

    public function test_category_cards_match_python(): void
    {
        $this->assertMatchesGolden(
            'humanitas_category',
            Parser::parseCategoryPage(self::fixture('index_page.html'))
        );
    }

    public function test_product_page_matches_python(): void
    {
        $this->assertMatchesGolden(
            'humanitas_product',
            Parser::parseProductPage(self::fixture('product_with_book_info.html'))
        );
    }

    public function test_a_page_without_the_book_info_block_matches_python(): void
    {
        // Legacy imports render no book-info block; the parser has to fall
        // back to OG metadata rather than throw.
        $this->assertMatchesGolden(
            'humanitas_product_bare',
            Parser::parseProductPage(self::fixture('product_without_book_info.html'))
        );
    }

    public function test_parse_index_page_wraps_the_same_urls(): void
    {
        $urls = Parser::parseSitemapUrls(self::fixture('index_page.html'));
        $wrapped = Parser::parseIndexPage(self::fixture('index_page.html'));

        self::assertSame(
            array_map(static fn (string $u): array => ['url' => $u], $urls),
            $wrapped
        );
    }

    // ------------------------------------------------------------- URL rules

    public function test_the_pagination_query_is_stripped_from_card_urls(): void
    {
        // CMSMS echoes cntnt01page=N onto every card; the product is the same
        // whichever result page it appeared on, so leaving it would create a
        // separate discovered_urls row per page.
        foreach (Parser::parseSitemapUrls(self::fixture('index_page.html')) as $url) {
            self::assertStringNotContainsString('cntnt01page', $url);
            self::assertStringNotContainsString('?', $url);
        }
    }

    public function test_only_product_paths_are_accepted(): void
    {
        $html = '<a class="book-item" href="/produktas/kategorija/knyga/">ok</a>'
            . '<a class="book-item" href="/kategorija/not-a-product/">no</a>'
            . '<a class="book-item" href="https://elsewhere.test/produktas/x/">no</a>';

        self::assertSame(
            ['https://www.humanitas.lt/produktas/kategorija/knyga'],
            Parser::parseSitemapUrls($html)
        );
    }

    // ----------------------------------------------------------- stock rules

    public function test_the_inline_out_of_stock_script_variable_is_not_a_stock_signal(): void
    {
        // The template inlines `var out_of_stock = 'Likutis nepakankamas';`
        // on EVERY product. Scanning it would mark the whole catalogue out of
        // stock, so scripts are stripped before sniffing.
        $html = '<script>var out_of_stock = \'Likutis nepakankamas\';</script>'
            . '<div class="cart-container"><div class="cart-price">'
            . '<div class="price-container"><div class="discount">14.25 €</div>'
            . '<div class="price">15.00 €</div></div></div></div></div></div>';

        $result = Parser::parseProductPage($html);

        self::assertTrue($result['in_stock']);
        self::assertSame('14.25', $result['price']);
        self::assertSame('15.00', $result['price_original']);
    }

    public function test_a_hidden_price_block_means_out_of_stock(): void
    {
        $result = Parser::parseProductPage('<div class="cart-price price-hidden" data-cart-price=""></div>');

        self::assertFalse($result['in_stock']);
    }

    public function test_a_disabled_cart_button_means_out_of_stock(): void
    {
        $result = Parser::parseProductPage(
            '<a href="#" class="ext_button orange-style uppercase disabled">į krepšelį</a>'
        );

        self::assertFalse($result['in_stock']);
    }

    public function test_a_priced_but_unbuyable_listing_is_out_of_stock(): void
    {
        // Third state: a cart-price block with a label but no price element,
        // and the button is NOT disabled — the other two detectors miss it.
        // ~3.9% of the catalogue: listed but unpriced.
        $result = Parser::parseProductPage(
            '<div class="cart-price"><div class="label">Kaina:</div></div>'
        );

        self::assertFalse($result['in_stock']);
    }

    // -------------------------------------------------------- Formatas field

    public function test_dimensions_in_the_format_field_do_not_become_a_format(): void
    {
        // `Formatas:` overloads binding and physical dimensions. Letting
        // "240 x 202" through would trip the format_is_dimensions validator.
        foreach (['240 x 202', '9.25×7.5', '23,5x18 cm.', '170 × 230 mm'] as $dimension) {
            $result = Parser::parseProductPage(
                '<div class="book-info"><b>Formatas:</b> ' . $dimension . ' <br></div>'
            );

            self::assertNull($result['format'], "dimensions leaked as format: {$dimension}");
            self::assertNull($result['cover_type']);
            self::assertSame($dimension, $result['properties']['dimensions'] ?? null);
        }
    }

    public function test_a_real_binding_becomes_the_format(): void
    {
        $result = Parser::parseProductPage(
            '<div class="book-info"><b>Formatas:</b> Kieti viršeliai <br></div>'
        );

        self::assertSame('hardcover', $result['format']);
        self::assertSame('Kieti viršeliai', $result['cover_type']);
    }

    public function test_the_empty_selector_placeholder_is_ignored(): void
    {
        $result = Parser::parseProductPage(
            '<div class="book-info"><b>Formatas:</b> pasirinkite <br></div>'
        );

        self::assertNull($result['format']);
        self::assertNull($result['cover_type']);
    }

    // ------------------------------------------------------- language gate

    public function test_a_non_lithuanian_book_is_blocked(): void
    {
        // The catalogue mixes LT and EN under LT-named branches. The gate runs
        // AFTER classification so book_score still reflects real signals; only
        // is_book_product flips, which makes the scan mark it non_product.
        $result = Parser::parseProductPage(
            '<meta property="og:title" content="Some English Book"/>'
            . '<div class="book-info"><b>ISBN:</b> 9786094802966 <br>'
            . '<b>Autorius:</b> An Author <br>'
            . '<b>Leidinio kalba:</b> Anglų <br></div>'
        );

        self::assertFalse($result['is_book_product']);
        self::assertGreaterThan(0, $result['book_score'], 'score should still reflect the signals');
        self::assertContains(
            'blocked_non_lt_language',
            array_column($result['book_score_reasons'], 'key')
        );
    }

    public function test_a_missing_language_lets_the_book_through(): void
    {
        // Legacy imports have no language field; dropping them would cost
        // real LT books — the same lesson as pegasas.
        $result = Parser::parseProductPage(
            '<meta property="og:title" content="Lietuviška knyga"/>'
            . '<div class="book-info"><b>ISBN:</b> 9786094802966 <br>'
            . '<b>Autorius:</b> An Author <br>'
            . '<b>Leidimo metai:</b> 2022 <br></div>'
        );

        self::assertTrue($result['is_book_product']);
    }

    public function test_lithuanian_passes_the_gate(): void
    {
        $result = Parser::parseProductPage(self::fixture('product_with_book_info.html'));

        self::assertTrue($result['is_book_product']);
        self::assertSame('Lietuvių', $result['properties']['language']);
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
