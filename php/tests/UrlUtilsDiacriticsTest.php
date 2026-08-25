<?php

declare(strict_types=1);

namespace BookScraper\Tests;

use BookScraper\UrlUtils;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

/**
 * Guards the parse_url() landmine.
 *
 * PHP's parse_url() substitutes '_' for some non-ASCII bytes in the path,
 * so `/asmeninis-tobulėjimas` comes back as `/asmeninis-tobul\xc4_jimas`.
 * Most of the catalogue has Lithuanian diacritics in its slugs, so using
 * it would corrupt `normalized_url` for the majority of rows — and since
 * that column backs a unique constraint, the corruption shows up as
 * duplicate products rather than as an error. UrlUtils uses an RFC 3986
 * regex instead; these tests fail if anyone swaps it back.
 */
final class UrlUtilsDiacriticsTest extends TestCase
{
    /** @return list<array{0: string}> */
    public static function diacriticUrls(): array
    {
        return [
            ['https://vaga.lt/asmeninis-tobulėjimas'],
            ['https://vaga.lt/kalėdų-pūga'],
            ['https://vaga.lt/šviesa-ir-šešėliai'],
            ['https://vaga.lt/žąsų-ganytojas'],
            ['https://vaga.lt/grožinė-literatūra?page=2'],
            ['https://vaga.lt/ąčęėįšųūž'],
        ];
    }

    #[DataProvider('diacriticUrls')]
    public function test_preserves_utf8_path_bytes(string $url): void
    {
        $normalized = UrlUtils::normalize($url);

        self::assertSame($url, $normalized);
        self::assertTrue(
            mb_check_encoding($normalized, 'UTF-8'),
            'normalize() emitted invalid UTF-8'
        );
        self::assertStringNotContainsString(
            '_',
            $normalized,
            'a byte was replaced with "_" — parse_url() is back'
        );
    }

    public function test_parse_url_still_corrupts_and_is_why_we_avoid_it(): void
    {
        // Documents the upstream behaviour being worked around. If a future
        // PHP release fixes parse_url(), this fails and UrlUtils::split()
        // could be simplified.
        $path = parse_url('https://vaga.lt/asmeninis-tobulėjimas', PHP_URL_PATH);

        self::assertNotSame(
            '/asmeninis-tobulėjimas',
            $path,
            'parse_url() no longer corrupts UTF-8 paths — UrlUtils::split() can be revisited'
        );
    }
}
