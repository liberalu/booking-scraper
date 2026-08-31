<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Support\UrlUtils;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class UrlUtilsDifferentialTest extends TestCase
{
    public static function urls(): iterable
    {
        $golden = json_decode(
            (string) file_get_contents(__DIR__.'/../golden/urls.json'),
            true,
            flags: JSON_THROW_ON_ERROR
        );

        foreach ($golden as $input => $expected) {
            yield $input => [(string) $input, (string) $expected];
        }
    }

    #[DataProvider('urls')]
    public function test_matches_python(string $input, string $expected): void
    {
        self::assertSame($expected, UrlUtils::normalize($input));
    }
}
