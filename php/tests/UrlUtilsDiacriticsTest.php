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

    /**
     * Documents the upstream behaviour UrlUtils::split() works around — and
     * skips where that behaviour is absent, because it is not universal.
     *
     * It is not even a matter of version. On PHP 8.4.24 from Homebrew,
     * parse_url() turns the `ė` in this path (C4 97) into `_` (5F); on PHP
     * 8.4.24 from shivammathur/setup-php on Ubuntu, the same call returns the
     * path intact. So the workaround has to stay regardless, and asserting the
     * corruption unconditionally just turns a healthy environment red — which
     * is what it did on CI's first run.
     *
     * The invariant that actually matters is covered on every environment by
     * test_preserves_utf8_path_bytes above: normalize() keeps the bytes. This
     * test only reports on the underlying platform.
     */
    public function test_parse_url_corrupts_utf8_paths_where_it_still_does(): void
    {
        $path = parse_url('https://vaga.lt/asmeninis-tobulėjimas', PHP_URL_PATH);

        if ($path === '/asmeninis-tobulėjimas') {
            self::markTestSkipped(
                'parse_url() handles UTF-8 paths correctly on this build ('
                . PHP_VERSION . '), so it is not the reason UrlUtils::split() '
                . 'exists here. The workaround still has to stay: other builds '
                . 'of the same version do corrupt them.'
            );
        }

        self::assertNotSame(
            '/asmeninis-tobulėjimas',
            $path,
            'parse_url() corrupted the path in some way other than expected'
        );
        self::assertStringContainsString(
            '_',
            (string) $path,
            'expected the documented byte-to-underscore substitution'
        );
    }
}
