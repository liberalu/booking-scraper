<?php

declare(strict_types=1);

namespace BookScraper\Crawler;

use BookScraper\Isbn;
use BookScraper\Markdown;

/**
 * The checks and corrections applied between parsing and storage, ported from
 * ValidationPipeline.
 *
 * It both validates and rewrites: an out-of-range year is cleared or unswapped
 * with pages, an ISBN that fails its checksum is dropped rather than stored, a
 * description arrives as HTML and is stored as Markdown. Skipping this layer
 * does not merely lose the issue log — it stores data the reference
 * implementation would have refused or fixed.
 *
 * A `DropItem` in upstream becomes a `reject` result here: same outcome, no
 * exception for something that is an ordinary parse outcome.
 */
final class ItemValidator
{
    private const MIN_YEAR = 1800;

    private const MAX_YEAR = 2030;

    /** Matches an opening or closing tag, as _HTML_TAG_RE does. */
    private const HTML_TAG = '/<[a-zA-Z\/][^>]*>/';

    /** Formats that cannot have a page count. */
    private const PAGED_FORMATS = ['book', 'hardcover', 'paperback'];

    /**
     * @param  array<string, mixed>  $parsed
     * @param  array{allowed_keys: list<string>, rules: array<string, array{enum?: list<string>, pattern?: string}>}|null  $attributeSchema
     * @return array{item: array<string, mixed>, reject: string|null}
     *         `reject` is the reason the item must not be stored, or null.
     */
    public static function apply(
        array $parsed,
        string $url,
        ?array $attributeSchema = null,
    ): array {
        // Price first: an unparseable one drops the item, and there is no
        // point validating the rest of a row that will not be stored.
        if (array_key_exists('price', $parsed) && $parsed['price'] !== null) {
            $price = self::decimal($parsed['price']);
            if ($price === null) {
                IssueBuffer::add('invalid_price', 'price', $url, (string) $parsed['price']);

                return ['item' => $parsed, 'reject' => "Invalid price: {$parsed['price']}"];
            }
            $parsed['price'] = $price;
        }

        if (array_key_exists('price_original', $parsed) && $parsed['price_original'] !== null) {
            $original = self::decimal($parsed['price_original']);
            if ($original === null) {
                IssueBuffer::add(
                    'invalid_price_original',
                    'price_original',
                    $url,
                    (string) $parsed['price_original']
                );
                // Unlike `price`, a bad original price is dropped rather than
                // dropping the item: it is decoration on a usable row.
                $parsed['price_original'] = null;
            } else {
                $parsed['price_original'] = $original;
            }
        }

        self::checkPriceAnomalies($parsed, $url);

        // Descriptions are stored as Markdown regardless of the shop's markup.
        $description = $parsed['description'] ?? null;
        if (is_string($description) && str_contains($description, '<') && str_contains($description, '>')) {
            $parsed['description'] = Markdown::fromHtml($description);
        }

        if (($parsed['title'] ?? null) === null || $parsed['title'] === '') {
            IssueBuffer::add('missing_title', 'title', $url);

            return ['item' => $parsed, 'reject' => 'Missing title'];
        }

        $parsed = self::validateYear($parsed, $url);

        if (array_key_exists('isbn', $parsed) && $parsed['isbn'] !== null) {
            $isbn = (string) $parsed['isbn'];
            if (Isbn::isValid($isbn)) {
                $parsed['isbn'] = Isbn::normalize($isbn);
            } else {
                // Stored as null, not as-is: a wrong ISBN would link the book
                // to the wrong canonical record.
                IssueBuffer::add('invalid_isbn', 'isbn', $url, $isbn);
                $parsed['isbn'] = null;
            }
        }

        foreach (['title', 'author', 'publisher'] as $field) {
            if (is_string($parsed[$field] ?? null)) {
                $parsed[$field] = trim($parsed[$field]) ?: null;
            }
        }

        if ($url === '' || !str_starts_with($url, 'http://') && !str_starts_with($url, 'https://')) {
            IssueBuffer::add('invalid_url', 'url', $url);

            return ['item' => $parsed, 'reject' => "Invalid URL: {$url}"];
        }

        self::checkContentQuality($parsed, $url);
        self::checkFormatConsistency($parsed, $url);
        if ($attributeSchema !== null) {
            self::checkAttributes($parsed, $url, $attributeSchema);
        }

        return ['item' => $parsed, 'reject' => null];
    }

    /** @param array<string, mixed> $parsed */
    private static function checkPriceAnomalies(array $parsed, string $url): void
    {
        $price = $parsed['price'] ?? null;
        $inStock = $parsed['in_stock'] ?? null;

        if ($price === null) {
            // Some shops legitimately publish no price for an out-of-stock
            // book, so only flag one that claims to be available.
            if ($inStock !== false) {
                IssueBuffer::add('missing_price', 'price', $url);
            }

            return;
        }

        if ((float) $price === 0.0 && $inStock !== false) {
            IssueBuffer::add('zero_price', 'price', $url, (string) $price);
        }

        $original = $parsed['price_original'] ?? null;
        if ($original !== null && (float) $original > 0 && (float) $price > (float) $original) {
            IssueBuffer::add(
                'price_higher_than_original',
                'price',
                $url,
                "{$price}>{$original}"
            );
        }
    }

    /**
     * Normalise the year, then report on what changed.
     *
     * Split exactly as upstream splits it: the normalisation is silent, and
     * the issue is decided afterwards by comparing the value before and
     * after. That comparison is an identity check, which is where a latent
     * upstream bug lives — see yearIssue().
     *
     * @param  array<string, mixed>  $parsed
     * @return array<string, mixed>
     */
    private static function validateYear(array $parsed, string $url): array
    {
        if (!array_key_exists('year', $parsed) || $parsed['year'] === null) {
            return $parsed;
        }
        $before = $parsed['year'];
        $parsed = self::normaliseYear($parsed);
        $after = $parsed['year'];

        self::yearIssue($url, $before, $after);

        return $parsed;
    }

    /**
     * `year_pages_swap` when the value changed, `invalid_year` when it was
     * cleared.
     *
     * The change test is identity, not numeric equality, so a year supplied
     * as the STRING "2024" — normalised to the int 2024 — reads as a swap and
     * reports `year_pages_swap` with raw_value 2024. That is wrong, and it is
     * reproduced on purpose: every parser returns an int today (all 14
     * production occurrences of this issue carry a genuine page count: 20,
     * 50, 320, 784…), so the path is latent, and silently "fixing" it here
     * would make the port diverge from the behaviour it is measured against.
     * The upstream fix is to compare numerically.
     */
    private static function yearIssue(string $url, mixed $before, mixed $after): void
    {
        if ($after === null) {
            IssueBuffer::add('invalid_year', 'year', $url, (string) $before);

            return;
        }
        if ($before !== $after) {
            IssueBuffer::add('year_pages_swap', 'year', $url, (string) $before);
        }
    }

    /**
     * @param  array<string, mixed>  $parsed
     * @return array<string, mixed>
     */
    private static function normaliseYear(array $parsed): array
    {
        $raw = $parsed['year'];
        if (!is_numeric($raw)) {
            $parsed['year'] = null;

            return $parsed;
        }
        $year = (int) $raw;
        if ($year >= self::MIN_YEAR && $year <= self::MAX_YEAR) {
            $parsed['year'] = $year;

            return $parsed;
        }

        // Out of range is usually a page count in the wrong field: some shops
        // swap the two. Pages live in `properties` for most shops and at the
        // top level for patogupirkti.
        $properties = is_array($parsed['properties'] ?? null) ? $parsed['properties'] : null;
        $pagesValue = null;
        if ($properties !== null && array_key_exists('pages', $properties)) {
            $pagesValue = $properties['pages'];
        } elseif (($parsed['pages'] ?? null) !== null) {
            $pagesValue = $parsed['pages'];
        }

        if ($pagesValue !== null && is_numeric($pagesValue)) {
            $pages = (int) $pagesValue;
            if ($pages >= self::MIN_YEAR && $pages <= self::MAX_YEAR) {
                $parsed['year'] = $pages;
                if ($properties !== null && array_key_exists('pages', $properties)) {
                    $properties['pages'] = $year;
                    $parsed['properties'] = $properties;
                } else {
                    $parsed['pages'] = $year;
                }

                return $parsed;
            }
        }

        $parsed['year'] = null;

        return $parsed;
    }

    /** @param array<string, mixed> $parsed */
    private static function checkContentQuality(array $parsed, string $url): void
    {
        // `description` is exempt: it holds sanitised rich text by design.
        foreach (['title', 'author'] as $field) {
            $value = $parsed[$field] ?? null;
            if (is_string($value) && preg_match(self::HTML_TAG, $value) === 1) {
                IssueBuffer::add('html_in_text', $field, $url, mb_substr($value, 0, 100));
            }
        }

        $title = $parsed['title'] ?? null;
        if (!is_string($title)) {
            return;
        }
        $length = mb_strlen($title);
        if ($length < 2) {
            IssueBuffer::add('suspicious_title', 'title', $url, $title);
        } elseif ($length > 300) {
            IssueBuffer::add('suspicious_title', 'title', $url, "len={$length}");
        }
    }

    /** @param array<string, mixed> $parsed */
    private static function checkFormatConsistency(array $parsed, string $url): void
    {
        $format = $parsed['format'] ?? null;
        $properties = is_array($parsed['properties'] ?? null) ? $parsed['properties'] : [];

        if ($format === 'audiobook' && array_key_exists('pages', $properties)) {
            IssueBuffer::add('format_mismatch', 'format', $url, 'audiobook with pages');
        }
        if (in_array($format, self::PAGED_FORMATS, true) && array_key_exists('duration', $properties)) {
            IssueBuffer::add('format_mismatch', 'format', $url, "{$format} with duration");
        }
    }

    /**
     * @param array<string, mixed> $parsed
     * @param array{allowed_keys: list<string>, rules: array<string, array{enum?: list<string>, pattern?: string}>} $schema
     */
    private static function checkAttributes(array $parsed, string $url, array $schema): void
    {
        $properties = $parsed['properties'] ?? null;
        if (!is_array($properties)) {
            return;
        }
        $allowed = $schema['allowed_keys'] ?? [];

        foreach ($properties as $key => $value) {
            if (!in_array((string) $key, $allowed, true)) {
                IssueBuffer::add('attribute_unknown_key', 'properties', $url, "{$key}={$value}");
                continue;
            }
            $rule = $schema['rules'][$key] ?? null;
            if ($rule === null || $value === null) {
                continue;
            }
            $stringValue = (string) $value;
            if (isset($rule['enum']) && !in_array($stringValue, $rule['enum'], true)) {
                IssueBuffer::add(
                    'attribute_invalid_value',
                    (string) $key,
                    $url,
                    "not in enum: {$stringValue}"
                );
            }
            if (isset($rule['pattern'])
                && preg_match('/^(?:' . $rule['pattern'] . ')$/u', $stringValue) !== 1) {
                IssueBuffer::add(
                    'attribute_invalid_value',
                    (string) $key,
                    $url,
                    "pattern mismatch: {$stringValue}"
                );
            }
        }
    }

    /**
     * Decimal's string form, or null when the value is not a number.
     *
     * Python stores `str(Decimal(value))`, which keeps the scale it was given
     * ("12.30" stays "12.30"), so the string is passed through rather than
     * cast to float.
     */
    private static function decimal(mixed $value): ?string
    {
        if (is_int($value) || is_float($value)) {
            return (string) $value;
        }
        if (!is_string($value)) {
            return null;
        }
        $trimmed = trim($value);

        return preg_match('/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/', $trimmed) === 1
            ? $trimmed
            : null;
    }
}
