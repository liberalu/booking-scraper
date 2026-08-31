<?php

declare(strict_types=1);

namespace App\Support;

use Normalizer;

final class CoverType
{
    private const CANONICAL = [
        'hardcover', 'paperback', 'ebook', 'audiobook', 'cd', 'dvd', 'book',
    ];

    private const DIMENSION = '/^\s*\d+\s*[xX×]\s*\d+(\s*(mm|cm))?\s*$/iu';

    public static function toFormat(?string $coverType): ?string
    {
        if ($coverType === null || $coverType === '') {
            return null;
        }
        foreach (explode(',', $coverType) as $segment) {
            $mapped = self::mapSegment($segment);
            if ($mapped !== null) {
                return $mapped;
            }
        }

        return null;
    }

    private static function mapSegment(string $segment): ?string
    {
        $s = trim($segment);
        if ($s === '' || preg_match(self::DIMENSION, $s) === 1) {
            return null;
        }

        $lower = mb_strtolower($s, 'UTF-8');
        if (in_array($lower, self::CANONICAL, true)) {
            return $lower;
        }

        $stripped = self::stripDiacritics($lower);

        if (str_contains($stripped, 'puskiet') || str_contains($stripped, 'puskie')) {
            return 'hardcover';
        }
        if (str_contains($stripped, 'kiet') || preg_match('/\bketi\b/u', $stripped) === 1) {
            return 'hardcover';
        }
        if (str_contains($stripped, 'minkst')) {
            return 'paperback';
        }

        return null;
    }

    public static function stripDiacritics(string $s): string
    {
        $nfd = Normalizer::normalize($s, Normalizer::FORM_D);

        return preg_replace('/\p{Mn}/u', '', $nfd === false ? $s : $nfd) ?? $s;
    }
}
