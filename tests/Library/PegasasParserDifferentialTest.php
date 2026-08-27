<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Parsers\Pegasas\Parser;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

/**
 * pegasas is JSON-only (Magento GraphQL and LupaSearch), so the port is
 * checked the same way as vaga's: identical fixtures through both
 * implementations, compared field by field against golden dumped from the
 * Python parser.
 */
final class PegasasParserDifferentialTest extends TestCase
{
    private const FIXTURES = __DIR__ . '/../../fixtures';
    private const GOLDEN = __DIR__ . '/golden';

    public function test_graphql_category_matches_python(): void
    {
        $this->assertMatchesGolden(
            'pegasas_graphql',
            Parser::parseCategoryPage(self::fixture('pegasas_graphql_category.json'))
        );
    }

    public function test_lupasearch_response_matches_python(): void
    {
        $this->assertMatchesGolden(
            'pegasas_lupasearch',
            Parser::parseLupasearchResponse(self::fixture('pegasas_lupasearch_page1.json'))
        );
    }

    public function test_product_page_matches_python(): void
    {
        $this->assertMatchesGolden(
            'pegasas_product',
            Parser::parseProductPage(self::fixture('pegasas_graphql_category.json'))
        );
    }

    public function test_scan_url_rewrite_matches_python(): void
    {
        $golden = self::golden('pegasas_rewrite');
        foreach ($golden as $case) {
            self::assertSame(
                self::sorted($case['result']),
                self::sorted(Parser::rewriteScanUrl($case['url'])),
                "rewriteScanUrl diverged for {$case['url']}"
            );
        }
    }

    public function test_a_non_json_body_is_treated_as_the_pwa_shell(): void
    {
        // Product pages serve a React shell; the scan spider must close the
        // row cleanly rather than raise.
        $result = Parser::parseProductPage('<!doctype html><html><div id="root"></div></html>');

        self::assertNull($result['title']);
        self::assertFalse($result['is_book_product']);
        self::assertSame('non_book', $result['type']);
        self::assertSame(
            [['key' => 'pwa_shell_no_data', 'points' => 0]],
            $result['book_score_reasons']
        );
    }

    public function test_an_empty_graphql_match_is_reported_distinctly(): void
    {
        // Distinct reason key from the shell case, so a missing SKU is
        // diagnosable separately from a bypassed rewrite.
        $result = Parser::parseProductPage('{"data":{"products":{"items":[]}}}');

        self::assertSame(
            [['key' => 'graphql_no_match', 'points' => 0]],
            $result['book_score_reasons']
        );
    }

    public function test_pegasas_has_no_sitemap(): void
    {
        self::assertSame([], Parser::parseSitemapUrls('<urlset><url><loc>x</loc></url></urlset>'));
    }

    // --------------------------------------------------------- type derivation

    public function test_audio_wins_over_every_other_flag(): void
    {
        self::assertSame('audio', Parser::deriveBookType(true, true, true, true));
    }

    public function test_category_evidence_overrides_a_false_is_book_flag(): void
    {
        // Magento reports is_book=false on real textbooks and illustrated
        // children's titles; category names are the corrective signal.
        self::assertSame(
            'book',
            Parser::deriveBookType(false, false, false, hasBookCategory: true)
        );
        self::assertSame('non_book', Parser::deriveBookType(false, false, false, false));
    }

    #[DataProvider('bookCategoryNames')]
    public function test_book_category_substrings_are_diacritic_insensitive(string $name, bool $expected): void
    {
        self::assertSame($expected, Parser::categoriesIndicateBook([$name]));
    }

    /** @return array<string, array{0: string, 1: bool}> */
    public static function bookCategoryNames(): array
    {
        return [
            'knygos' => ['Knygos', true],
            'grozine with diacritics' => ['Grožinė literatūra', true],
            'mokslo literatura' => ['Mokslo literatūra', true],
            'vadoveliai' => ['Vadovėliai', true],
            'pratybos' => ['Pratybos', true],
            'cosmetics' => ['Kosmetika', false],
            'toys' => ['Žaislai', false],
            'stationery' => ['Raštinės prekės', false],
        ];
    }

    // ---------------------------------------------------------------- ISBN

    #[DataProvider('isbnCases')]
    public function test_isbn_coercion(string $raw, ?string $expected): void
    {
        self::assertSame($expected, Parser::coerceIsbn($raw));
    }

    /** @return array<string, array{0: string, 1: string|null}> */
    public static function isbnCases(): array
    {
        return [
            'valid isbn13' => ['9789955082484', '9789955082484'],
            'hyphenated' => ['978-9955-08-248-4', '9789955082484'],
            // pegasas stores this ISBN-10 with a wrong check digit; the
            // 9-digit core still identifies the book.
            'isbn10 bad check digit' => ['9955082484', '9789955082484'],
            'valid isbn10' => ['0306406152', '9780306406157'],
            // A sticker-kit GTIN, not Bookland space.
            'non bookland ean' => ['4010070612345', null],
            'garbage' => ['not-an-isbn', null],
            'empty' => ['', null],
        ];
    }

    // -------------------------------------------------------------- helpers

    private function assertMatchesGolden(string $name, mixed $actual): void
    {
        self::assertSame(self::sorted(self::golden($name)), self::sorted($actual));
    }

    private static function golden(string $name): mixed
    {
        return json_decode(
            (string) file_get_contents(self::GOLDEN . "/{$name}.json"),
            true,
            flags: JSON_THROW_ON_ERROR
        );
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
