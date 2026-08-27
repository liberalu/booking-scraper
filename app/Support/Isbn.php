<?php

declare(strict_types=1);

namespace App\Support;

/**
 * Port of book_scraper/isbn.py. Kept behaviourally identical — the
 * double-prefix rejection and the "978/979 is not an ISBN-10 group id"
 * rule both exist to stop known corruption signatures, not as tidiness.
 */
final class Isbn
{
    private const ISBN_13 = '/^97[89]\d{10}$/';
    private const ISBN_10 = '/^\d{9}[\dXx]$/';

    /** Double-prefix corruption fingerprints — see isbn.py for the why. */
    private const DOUBLE_PREFIXED = ['9789789', '9799789', '9789979', '9799979'];

    public static function normalize(?string $raw): string
    {
        return $raw === null ? '' : str_replace(['-', ' '], '', $raw);
    }

    public static function isValid(?string $raw): bool
    {
        $cleaned = self::normalize($raw);

        if (preg_match(self::ISBN_13, $cleaned) === 1) {
            if (in_array(substr($cleaned, 0, 7), self::DOUBLE_PREFIXED, true)) {
                return false;
            }

            return self::checksum13($cleaned) % 10 === 0;
        }

        if (preg_match(self::ISBN_10, $cleaned) === 1) {
            // 978/979 are EAN Bookland prefixes, never ISBN-10 group ids.
            if (in_array(substr($cleaned, 0, 3), ['978', '979'], true)) {
                return false;
            }
            $total = 0;
            foreach (str_split($cleaned) as $i => $c) {
                $total += (($c === 'X' || $c === 'x') ? 10 : (int) $c) * (10 - $i);
            }

            return $total % 11 === 0;
        }

        return false;
    }

    public static function toIsbn13(?string $raw): ?string
    {
        $cleaned = self::normalize($raw);
        if ($cleaned === '') {
            return null;
        }
        if (preg_match(self::ISBN_13, $cleaned) === 1) {
            return $cleaned;
        }
        if (preg_match(self::ISBN_10, $cleaned) === 1) {
            if (in_array(substr($cleaned, 0, 3), ['978', '979'], true)) {
                return null;
            }
            $body = '978' . substr($cleaned, 0, 9);

            return $body . (string) ((10 - self::checksum13($body) % 10) % 10);
        }

        return null;
    }

    public static function toIsbn10(?string $raw): ?string
    {
        $cleaned = self::normalize($raw);
        if ($cleaned === '') {
            return null;
        }
        if (preg_match(self::ISBN_10, $cleaned) === 1) {
            return strtoupper($cleaned);
        }
        if (preg_match(self::ISBN_13, $cleaned) === 1) {
            if (!str_starts_with($cleaned, '978')) {
                return null;
            }
            $body = substr($cleaned, 3, 9);
            $total = 0;
            foreach (str_split($body) as $i => $d) {
                $total += (int) $d * (10 - $i);
            }
            $check = (11 - $total % 11) % 11;

            return $body . ($check === 10 ? 'X' : (string) $check);
        }

        return null;
    }

    /** Weighted 1,3,1,3… sum used by both the ISBN-13 check and conversion. */
    private static function checksum13(string $digits): int
    {
        $total = 0;
        foreach (str_split($digits) as $i => $d) {
            $total += (int) $d * ($i % 2 === 0 ? 1 : 3);
        }

        return $total;
    }
}
