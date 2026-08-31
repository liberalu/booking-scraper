<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Support\ValidationRules;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class ValidateHelpersDifferentialTest extends TestCase
{
    private static function golden(): array
    {
        static $golden = null;
        $golden ??= json_decode(
            (string) file_get_contents(__DIR__.'/../golden/validate_predicates.json'),
            true,
            flags: JSON_THROW_ON_ERROR
        );

        return $golden;
    }

    public static function tokenizeCases(): iterable
    {
        foreach (self::golden()['tokenize'] as $i => $case) {
            yield "case {$i}: ".mb_substr((string) $case['input'], 0, 40) => [
                (string) $case['input'],
                $case['tokens'],
            ];
        }
    }

    #[DataProvider('tokenizeCases')]
    public function test_tokenize_matches_python(string $input, array $expected): void
    {
        $tokens = ValidationRules::tokenize($input);

        sort($tokens, SORT_STRING);

        self::assertSame($expected, $tokens);
    }

    public static function slugTitleCases(): iterable
    {
        foreach (self::golden()['slug_title'] as $i => $case) {
            yield "case {$i}: ".mb_substr((string) $case['slug'], 0, 40) => [
                (string) $case['slug'],
                (string) $case['title'],
                (bool) $case['should_flag'],
                (bool) $case['diacritic_lossy'],
            ];
        }
    }

    #[DataProvider('slugTitleCases')]
    public function test_slug_predicates_match_python(
        string $slug,
        string $title,
        bool $shouldFlag,
        bool $lossy,
    ): void {
        self::assertSame(
            $shouldFlag,
            ValidationRules::shouldFlagSlugTitle($slug, $title),
            'shouldFlagSlugTitle diverged'
        );
        self::assertSame(
            $lossy,
            ValidationRules::looksDiacriticLossy($slug, $title),
            'looksDiacriticLossy diverged'
        );
    }

    public static function nonBookTitleCases(): iterable
    {
        foreach (self::golden()['non_book_title'] as $i => $case) {
            yield "case {$i}" => [(string) $case['title'], (bool) $case['result']];
        }
    }

    #[DataProvider('nonBookTitleCases')]
    public function test_non_book_title_matches_python(string $title, bool $expected): void
    {
        self::assertSame($expected, ValidationRules::titleIndicatesNonBook($title));
    }

    public static function nonBookCategoryCases(): iterable
    {
        foreach (self::golden()['non_book_categories'] as $i => $case) {
            yield "case {$i}" => [$case['categories'], (bool) $case['result']];
        }
    }

    #[DataProvider('nonBookCategoryCases')]
    public function test_non_book_categories_match_python(array $categories, bool $expected): void
    {
        self::assertSame($expected, ValidationRules::categoriesIndicateNonBook($categories));
    }

    public static function urlAliasCases(): iterable
    {
        foreach (self::golden()['url_alias'] as $i => $case) {
            yield "case {$i}" => [
                (string) $case['canon'],
                (string) $case['alias'],
                (bool) $case['genuine'],
            ];
        }
    }

    #[DataProvider('urlAliasCases')]
    public function test_url_alias_matches_python(string $canon, string $alias, bool $expected): void
    {
        self::assertSame($expected, ValidationRules::isGenuineUrlAlias($canon, $alias));
    }

    public function test_diacritic_loss_signature(): void
    {
        self::assertTrue(
            ValidationRules::looksDiacriticLossy('kale-du-pu-ga-2196148', 'Kalėdų pūga'),
            'fragment re-merge is the smoking gun'
        );
        self::assertFalse(
            ValidationRules::looksDiacriticLossy('kaledu-puga', 'Kalėdų pūga'),
            'correct transliteration must not flag'
        );
        self::assertFalse(
            ValidationRules::looksDiacriticLossy('kaledu-puga-2-as-leidimas', 'Kalėdų pūga'),
            'extra slug text is not fragmentation'
        );
        self::assertFalse(
            ValidationRules::looksDiacriticLossy('kale-du-pu-ga', 'Kalėdų pūga…'),
            'a truncated title cannot be judged'
        );
    }
}
