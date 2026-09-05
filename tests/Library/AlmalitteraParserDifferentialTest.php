<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Parsers\Almalittera\Parser;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class AlmalitteraParserDifferentialTest extends TestCase
{
    private const string FIXTURES = __DIR__.'/../fixtures/almalittera';

    private const string GOLDEN = __DIR__.'/../golden';

    public function test_products_json_matches_python(): void
    {
        $this->assertMatchesGolden(
            'alma_category',
            Parser::parseCategoryPage(self::fixture('products_page.json'))
        );
    }

    public function test_product_page_matches_python(): void
    {
        $this->assertMatchesGolden(
            'alma_product',
            Parser::parseProductPage(self::fixture('product_page.html'))
        );
    }

    public function test_ebook_page_matches_python(): void
    {
        $this->assertMatchesGolden(
            'alma_ebook',
            Parser::parseProductPage(self::fixture('ebook_page.html'))
        );
    }

    public function test_notebook_page_matches_python(): void
    {

        $this->assertMatchesGolden(
            'alma_notebook',
            Parser::parseProductPage(self::fixture('notebook_page.html'))
        );
    }

    public function test_the_notebook_is_classified_non_book(): void
    {

        $result = Parser::parseProductPage(self::fixture('notebook_page.html'));

        self::assertSame('non_book', $result['type']);
        self::assertFalse($result['is_book_product']);
    }

    public function test_the_ebook_is_typed_from_its_title(): void
    {

        $result = Parser::parseProductPage(self::fixture('ebook_page.html'));

        self::assertSame('ebook', $result['type']);
        self::assertSame('ebook', $result['format']);
    }

    public function test_malformed_products_json_yields_no_products(): void
    {
        foreach (['not json', '{}', '{"products": "nope"}', ''] as $body) {
            self::assertSame(
                ['products' => [], 'total' => null],
                Parser::parseCategoryPage($body)
            );
        }
    }

    public function test_total_is_null_because_shopify_exposes_no_count(): void
    {

        self::assertNull(Parser::parseCategoryPage(self::fixture('products_page.json'))['total']);
    }

    #[DataProvider('shopifyTypes')]
    public function test_type_from_shopify_fields(mixed $productType, mixed $tags, string $expected): void
    {
        self::assertSame($expected, Parser::bookTypeFromShopify($productType, $tags));
    }

    public static function shopifyTypes(): array
    {
        return [
            'epub product_type' => ['EPUB', [], 'ebook'],
            'lowercase epub' => ['epub', [], 'ebook'],
            'epub via tag list' => ['', ['EPUB', 'NEW'], 'ebook'],
            'epub via tag string' => ['', 'EPUB, NEW', 'ebook'],
            'mp3 product_type' => ['MP3', [], 'audio'],
            'audiobook product_type' => ['AUDIOBOOK', [], 'audio'],
            'mp3 via tag' => ['', ['MP3'], 'audio'],
            'blank means paper' => ['', [], 'book'],
            'null means paper' => [null, null, 'book'],
            'unknown type means paper' => ['HARDCOVER', [], 'book'],
        ];
    }

    #[DataProvider('vendors')]
    public function test_placeholder_vendors_are_treated_as_no_author(mixed $vendor, ?string $expected): void
    {
        self::assertSame($expected, Parser::vendorToAuthor($vendor));
    }

    public static function vendors(): array
    {
        return [
            'real author' => ['Jane Doe', 'Jane Doe'],
            'padded' => ['  Jane Doe  ', 'Jane Doe'],

            'placeholder' => ['Nėra autoriaus', null],
            'placeholder without diacritics' => ['Nera autoriaus', null],
            'placeholder mixed case' => ['NĖRA AUTORIAUS', null],
            'blank' => ['   ', null],
            'not a string' => [null, null],
        ];
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
