<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Support\UrlUtils;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class UrlUtilsDiacriticsTest extends TestCase
{
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

    public function test_parse_url_corrupts_utf8_paths_where_it_still_does(): void
    {
        $path = parse_url('https://vaga.lt/asmeninis-tobulėjimas', PHP_URL_PATH);

        if ($path === '/asmeninis-tobulėjimas') {
            self::markTestSkipped(
                'parse_url() handles UTF-8 paths correctly on this build ('
                .PHP_VERSION.'), so it is not the reason UrlUtils::split() '
                .'exists here. The workaround still has to stay: other builds '
                .'of the same version do corrupt them.'
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
