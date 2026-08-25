<?php

declare(strict_types=1);

namespace BookScraper\Services;

use Normalizer;

/**
 * Predicates behind the validator's noisier checks, ported from
 * book_scraper/services/validate.py.
 *
 * Each one exists to suppress a specific false-positive class observed in
 * production; the counts in the comments are from the Python source.
 */
final class ValidateHelpers
{
    /**
     * Lithuanian category keywords marking a legitimate non-book product.
     * Stored diacritic-stripped; the blob is folded before matching.
     */
    private const NON_BOOK_CATEGORY_KEYWORDS = [
        'zaisl',      // žaislai (toys)
        'zaidim',     // žaidimai (games)
        'delion',     // dėlionės (puzzles)
        'sasiuvin',   // sąsiuviniai (notebooks)
        'kortel',     // kortelės (cards)
        'zemelap',    // žemėlapiai (maps)
        'rastin',     // raštinės prekės (office supplies)
        'hobio',      // hobio prekės
        'mokyklin',   // mokyklinės prekės (school supplies)
        'popier',     // popieriaus gaminiai (paper goods)
        'lavinam',    // lavinamieji (educational toys)
        'stalo zaid', // stalo žaidimai (board games)
    ];

    /** Title markers that identify a non-book (patogupirkti's /knyga/ sells DVDs too). */
    private const NON_BOOK_TITLE = '/\((DVD|Blu[-\s]?ray|CD|MP3|VHS|USB|Vinyl)\)'
        . '|\b(rinkinys|komplektas|set|bundle)\b'
        . '|kompaktine|audioknyga|audio kasete|garsine knyga/i';

    /**
     * OpenCart exposes every product at both a SEO slug and a raw
     * `index.php?route=product/product&product_id=N` URL. Both shapes
     * coexist by platform design, so flagging them as aliases is noise.
     */
    private const OPENCART_ROUTE = '/index\.php\?route=product(?:\/|%2F)product&product_id=\d+/i';

    private const LT_DIACRITICS = 'ąčęėįšųūžĄČĘĖĮŠŲŪŽ';

    /** A trailing ellipsis means the stored title is truncated. */
    private const TRUNCATED_TITLE = '/(?:…|\.\.\.)\s*$/u';

    /** Trailing numeric SKU suffix, e.g. "-2196148". */
    private const SLUG_SKU_SUFFIX = '/-\d+$/';

    /** WooCommerce dedup digit glued to a slug token: "sidhartha2". */
    private const TOKEN_DEDUP_DIGIT = '/^([a-z]{2,})\d+$/';

    /**
     * Lowercase, strip diacritics, extract alphanumeric runs.
     *
     * Splitting on everything non-alphanumeric is what lets title tokens
     * survive Lithuanian typography („menulio, geles", e.knyga) that would
     * otherwise glue onto adjacent words.
     *
     * Returned as a list, NOT as array keys: PHP coerces numeric-string
     * keys to integers, so a token like "18" would come back as int 18 and
     * stop comparing equal to the string form.
     *
     * @return list<string> unique tokens
     */
    public static function tokenize(?string $value): array
    {
        if ($value === null || $value === '') {
            return [];
        }

        preg_match_all('/[a-z0-9]+/', self::foldAscii($value), $matches);

        return array_values(array_unique($matches[0]));
    }

    /** Lowercase + drop combining marks: ė→e, š→s, ž→z, ų→u, ą→a. */
    public static function foldAscii(string $value): string
    {
        $lower = mb_strtolower($value, 'UTF-8');
        $nfd = Normalizer::normalize($lower, Normalizer::FORM_D);

        return preg_replace('/\p{Mn}/u', '', $nfd === false ? $lower : $nfd) ?? $lower;
    }

    /** The slug is the last path segment of the product URL. */
    public static function slugFromUrl(string $url): string
    {
        $trimmed = rtrim($url, '/');
        $position = strrpos($trimmed, '/');

        return $position === false ? $trimmed : substr($trimmed, $position + 1);
    }

    /**
     * True when slug and title share no tokens at all. Zero overlap is the
     * threshold; anything softer flagged legitimate subtitles.
     */
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

        // A WooCommerce dedup digit ("sidhartha2") would never match the bare
        // title token. Widen only the slug side, so a genuinely different
        // slug still has zero overlap and stays flagged.
        foreach ($slugTokens as $token) {
            if (preg_match(self::TOKEN_DEDUP_DIGIT, $token, $m) === 1) {
                $slugTokens[] = $m[1];
            }
        }

        return array_intersect($slugTokens, $titleTokens) === [];
    }

    /**
     * True when a diacritic-bearing title word is *fragmented* across
     * adjacent slug pieces — the signature of a slug generator that drops
     * diacritics character by character instead of transliterating.
     *
     * The smoking gun is fragment re-merge, not a piece-vs-word count:
     *   "Kalėdų pūga" → buggy  "kale-du-pu-ga": kale+du re-merges to
     *                          "kaledu" (= folded Kalėdų). Flagged.
     *   "Kalėdų pūga" → correct "kaledu-puga": each word appears whole.
     *                          Not flagged.
     *
     * A raw count over-fired on slugs merely carrying extra text
     * (subtitles, "-2-as-leidimas", "-kopija"): there the diacritic words
     * are present whole, so nothing re-merges.
     */
    public static function looksDiacriticLossy(?string $slug, ?string $title): bool
    {
        if ($slug === null || $slug === '' || $title === null || $title === '') {
            return false;
        }
        // Truncated titles drop words the slug still carries, which would
        // manufacture spurious fragments.
        if (preg_match(self::TRUNCATED_TITLE, $title) === 1) {
            return false;
        }

        // NFC first: the database stores NFD, and without recomposing, the
        // diacritic membership test fails and the word regex treats each
        // combining mark as a boundary.
        $nfc = Normalizer::normalize($title, Normalizer::FORM_C);
        preg_match_all('/[^\W\d_]+/u', $nfc === false ? $title : $nfc, $matches);

        $diacriticWords = array_values(array_filter(
            $matches[0],
            static fn (string $word): bool => self::hasLithuanianDiacritic($word)
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
        // in_array on a handful of pieces; array keys would coerce numeric
        // strings, and slug pieces here are alphabetic anyway.
        $whole = $pieces;

        foreach ($diacriticWords as $word) {
            $target = self::foldAscii($word);
            // Short particles (aš→as, dėl→del) re-merge by accident, and a
            // word already present whole means correct transliteration.
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
                    // j > i means at least two pieces merged.
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
        foreach (preg_split('//u', self::LT_DIACRITICS, -1, PREG_SPLIT_NO_EMPTY) ?: [] as $char) {
            if (mb_strpos($word, $char) !== false) {
                return true;
            }
        }

        return false;
    }

    /**
     * True when a category contains a non-book keyword. Suppresses
     * `non_book_has_isbn` on puzzles, board games and notebooks that carry
     * a publisher-issued ISBN — many LT publishers register those.
     *
     * @param list<string>|null $categories
     */
    public static function categoriesIndicateNonBook(?array $categories): bool
    {
        if ($categories === null || $categories === []) {
            return false;
        }

        $folded = self::foldAscii(implode(' | ', array_map('strval', $categories)));
        foreach (self::NON_BOOK_CATEGORY_KEYWORDS as $keyword) {
            if (str_contains($folded, $keyword)) {
                return true;
            }
        }

        return false;
    }

    public static function titleIndicatesNonBook(?string $title): bool
    {
        return $title !== null && $title !== ''
            && preg_match(self::NON_BOOK_TITLE, $title) === 1;
    }

    /**
     * True when the alias really is a different URL shape — i.e. the two
     * survive URL-decoding and OpenCart-route stripping.
     */
    public static function isGenuineUrlAlias(?string $canonUrl, ?string $aliasUrl): bool
    {
        if ($canonUrl === null || $canonUrl === '' || $aliasUrl === null || $aliasUrl === '') {
            return false;
        }
        if (preg_match(self::OPENCART_ROUTE, $aliasUrl) === 1
            || preg_match(self::OPENCART_ROUTE, $canonUrl) === 1) {
            return false;
        }

        // Decode both sides: handles `mi%C5%A1ku-x` vs `mišku-x`. Query
        // strings go first — on these platforms identity lives in the path,
        // and `?search=`/`?autorius_id=` are navigation residue. (Route URLs,
        // where the query IS the identity, are filtered above.)
        $canon = rtrim(urldecode(explode('?', $canonUrl, 2)[0]), '/');
        $alias = rtrim(urldecode(explode('?', $aliasUrl, 2)[0]), '/');
        if ($canon === $alias) {
            return false;
        }

        // Re-apply the last-segment gate after decoding: the SQL gate runs on
        // raw strings, and decoded forms can match where raw ones don't.
        return self::slugFromUrl($canon) !== self::slugFromUrl($alias);
    }
}
