<?php

declare(strict_types=1);

namespace App\Support;

use Normalizer;

final class ValidationRules
{
    private const array NON_BOOK_CATEGORY_KEYWORDS = [
        'zaisl',
        'zaidim',
        'delion',
        'sasiuvin',
        'kortel',
        'zemelap',
        'rastin',
        'hobio',
        'mokyklin',
        'popier',
        'lavinam',
        'stalo zaid',
    ];

    private const string NON_BOOK_TITLE = '/\((DVD|Blu[-\s]?ray|CD|MP3|VHS|USB|Vinyl)\)'
        .'|\b(rinkinys|komplektas|set|bundle)\b'
        .'|kompaktine|audioknyga|audio kasete|garsine knyga/i';

    private const string OPENCART_ROUTE = '/index\.php\?route=product(?:\/|%2F)product&product_id=\d+/i';

    private const string LT_DIACRITICS = 'ąčęėįšųūžĄČĘĖĮŠŲŪŽ';

    private const string TRUNCATED_TITLE = '/(?:…|\.\.\.)\s*$/u';

    private const string SLUG_SKU_SUFFIX = '/-\d+$/';

    private const string TOKEN_DEDUP_DIGIT = '/^([a-z]{2,})\d+$/';

    /** @return list<string> */
    public static function tokenize(?string $value): array
    {
        if ($value === null || $value === '') {
            return [];
        }

        preg_match_all('/[a-z0-9]+/', self::foldAscii($value), $matches);

        return array_values(array_unique(self::strings($matches[0])));
    }

    public static function foldAscii(string $value): string
    {
        $lower = mb_strtolower($value, 'UTF-8');
        $nfd = Normalizer::normalize($lower, Normalizer::FORM_D);

        return preg_replace('/\p{Mn}/u', '', $nfd === false ? $lower : $nfd) ?? $lower;
    }

    public static function slugFromUrl(string $url): string
    {
        $trimmed = rtrim($url, '/');
        $position = strrpos($trimmed, '/');

        return $position === false ? $trimmed : substr($trimmed, $position + 1);
    }

    public static function shouldFlagSlugTitle(?string $slug, ?string $title): bool
    {
        if ($slug === null || $slug === '' || $title === null || $title === '') {
            return false;
        }

        $slugTokens = self::tokenize($slug);
        $titleTokens = self::tokenize($title);
        if ($slugTokens === [] || $titleTokens === []) {
            return false;
        }

        foreach ($slugTokens as $token) {
            if (preg_match(self::TOKEN_DEDUP_DIGIT, $token, $m) === 1) {
                $slugTokens[] = $m[1];
            }
        }

        return array_intersect($slugTokens, $titleTokens) === [];
    }

    public static function looksDiacriticLossy(?string $slug, ?string $title): bool
    {
        if ($slug === null || $slug === '' || $title === null || $title === '') {
            return false;
        }

        if (preg_match(self::TRUNCATED_TITLE, $title) === 1) {
            return false;
        }

        $nfc = Normalizer::normalize($title, Normalizer::FORM_C);
        preg_match_all('/[^\W\d_]+/u', $nfc === false ? $title : $nfc, $matches);

        $diacriticWords = array_values(array_filter(
            self::strings($matches[0]),
            self::hasLithuanianDiacritic(...)
        ));
        if ($diacriticWords === []) {
            return false;
        }

        $cleaned = preg_replace(
            self::SLUG_SKU_SUFFIX,
            '',
            trim(mb_strtolower($slug, 'UTF-8'), '/')
        ) ?? '';

        $pieces = array_values(array_filter(
            explode('-', $cleaned),
            static fn (string $piece): bool => $piece !== ''
                && preg_match('/^\p{L}+$/u', $piece) === 1
        ));
        $count = count($pieces);
        if ($count < 2) {
            return false;
        }

        $whole = $pieces;

        foreach ($diacriticWords as $word) {
            $target = self::foldAscii($word);

            if (strlen($target) < 4 || in_array($target, $whole, true)) {
                continue;
            }
            for ($i = 0; $i < $count; $i++) {
                $accumulated = '';
                for ($j = $i; $j < $count; $j++) {
                    $accumulated .= $pieces[$j];
                    if (strlen($accumulated) > strlen($target)) {
                        break;
                    }

                    if ($accumulated === $target && $j > $i) {
                        return true;
                    }
                }
            }
        }

        return false;
    }

    private static function hasLithuanianDiacritic(string $word): bool
    {
        $characters = preg_split('//u', self::LT_DIACRITICS, -1, PREG_SPLIT_NO_EMPTY);

        return array_any($characters !== false ? $characters : [], fn ($char): bool => str_contains($word, $char));
    }

    /** @param list<string>|null $categories */
    public static function categoriesIndicateNonBook(?array $categories): bool
    {
        if ($categories === null || $categories === []) {
            return false;
        }

        $folded = self::foldAscii(implode(' | ', $categories));

        return array_any(self::NON_BOOK_CATEGORY_KEYWORDS, fn ($keyword): bool => str_contains($folded, $keyword));
    }

    public static function titleIndicatesNonBook(?string $title): bool
    {
        return $title !== null && $title !== ''
            && preg_match(self::NON_BOOK_TITLE, $title) === 1;
    }

    public static function isGenuineUrlAlias(?string $canonUrl, ?string $aliasUrl): bool
    {
        if ($canonUrl === null || $canonUrl === '' || $aliasUrl === null || $aliasUrl === '') {
            return false;
        }
        if (preg_match(self::OPENCART_ROUTE, $aliasUrl) === 1
            || preg_match(self::OPENCART_ROUTE, $canonUrl) === 1) {
            return false;
        }

        $canon = rtrim(urldecode(explode('?', $canonUrl, 2)[0]), '/');
        $alias = rtrim(urldecode(explode('?', $aliasUrl, 2)[0]), '/');
        if ($canon === $alias) {
            return false;
        }

        return self::slugFromUrl($canon) !== self::slugFromUrl($alias);
    }

    /** @return list<string> */
    private static function strings(mixed $values): array
    {
        if (! is_array($values)) {
            return [];
        }

        $strings = [];
        foreach ($values as $value) {
            if (is_string($value)) {
                $strings[] = $value;
            }
        }

        return $strings;
    }
}
