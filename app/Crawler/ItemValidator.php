<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Support\Isbn;
use App\Support\Markdown;

/**
 * @phpstan-import-type ParsedItem from CrawlerTypes
 * @phpstan-import-type AttributeSchema from CrawlerTypes
 */
final class ItemValidator
{
    private const MIN_YEAR = 1800;

    private const MAX_YEAR = 2030;

    private const HTML_TAG = '/<[a-zA-Z\/][^>]*>/';

    private const PAGED_FORMATS = ['book', 'hardcover', 'paperback'];

    /**
     * @param  ParsedItem  $parsed
     * @param  AttributeSchema|null  $attributeSchema
     * @return array{item: ParsedItem, reject: string|null}
     */
    public static function apply(
        array $parsed,
        string $url,
        ?array $attributeSchema = null,
        IssueBuffer $issues = new IssueBuffer,
    ): array {

        if (array_key_exists('price', $parsed) && $parsed['price'] !== null) {
            $price = self::decimal($parsed['price']);
            if ($price === null) {
                $rawPrice = self::displayValue($parsed['price']);
                $issues->add('invalid_price', 'price', $url, $rawPrice);

                return ['item' => $parsed, 'reject' => "Invalid price: {$rawPrice}"];
            }
            $parsed['price'] = $price;
        }

        if (array_key_exists('price_original', $parsed) && $parsed['price_original'] !== null) {
            $original = self::decimal($parsed['price_original']);
            if ($original === null) {
                $issues->add(
                    'invalid_price_original',
                    'price_original',
                    $url,
                    self::displayValue($parsed['price_original'])
                );

                $parsed['price_original'] = null;
            } else {
                $parsed['price_original'] = $original;
            }
        }

        self::checkPriceAnomalies($parsed, $url, $issues);

        $description = $parsed['description'] ?? null;
        if (is_string($description) && str_contains($description, '<') && str_contains($description, '>')) {
            $parsed['description'] = Markdown::fromHtml($description);
        }

        if (($parsed['title'] ?? null) === null || $parsed['title'] === '') {
            $issues->add('missing_title', 'title', $url);

            return ['item' => $parsed, 'reject' => 'Missing title'];
        }

        $parsed = self::validateYear($parsed, $url, $issues);

        if (array_key_exists('isbn', $parsed) && $parsed['isbn'] !== null) {
            $isbn = self::scalarString($parsed['isbn']);
            if ($isbn !== null && Isbn::isValid($isbn)) {
                $parsed['isbn'] = Isbn::normalize($isbn);
            } else {

                $issues->add('invalid_isbn', 'isbn', $url, self::displayValue($parsed['isbn']));
                $parsed['isbn'] = null;
            }
        }

        foreach (['title', 'author', 'publisher'] as $field) {
            if (is_string($parsed[$field] ?? null)) {
                $trimmed = trim($parsed[$field]);
                $parsed[$field] = $trimmed !== '' ? $trimmed : null;
            }
        }

        if ($url === '' || ! str_starts_with($url, 'http://') && ! str_starts_with($url, 'https://')) {
            $issues->add('invalid_url', 'url', $url);

            return ['item' => $parsed, 'reject' => "Invalid URL: {$url}"];
        }

        self::checkContentQuality($parsed, $url, $issues);
        self::checkFormatConsistency($parsed, $url, $issues);
        if ($attributeSchema !== null) {
            self::checkAttributes($parsed, $url, $attributeSchema, $issues);
        }

        return ['item' => $parsed, 'reject' => null];
    }

    /** @param ParsedItem $parsed */
    private static function checkPriceAnomalies(array $parsed, string $url, IssueBuffer $issues): void
    {
        $price = $parsed['price'] ?? null;
        $inStock = $parsed['in_stock'] ?? null;

        if ($price === null) {

            if ($inStock !== false) {
                $issues->add('missing_price', 'price', $url);
            }

            return;
        }

        $decimalPrice = self::decimal($price);
        if ($decimalPrice === null) {
            return;
        }
        $numericPrice = (float) $decimalPrice;
        if ($numericPrice === 0.0 && $inStock !== false) {
            $issues->add('zero_price', 'price', $url, $decimalPrice);
        }

        $original = $parsed['price_original'] ?? null;
        $decimalOriginal = self::decimal($original);
        if ($decimalOriginal !== null
            && (float) $decimalOriginal > 0.0
            && $numericPrice > (float) $decimalOriginal) {
            $issues->add(
                'price_higher_than_original',
                'price',
                $url,
                "{$decimalPrice}>{$decimalOriginal}"
            );
        }
    }

    /**
     * @param  ParsedItem  $parsed
     * @return ParsedItem
     */
    private static function validateYear(array $parsed, string $url, IssueBuffer $issues): array
    {
        if (! array_key_exists('year', $parsed) || $parsed['year'] === null) {
            return $parsed;
        }
        $before = $parsed['year'];
        $parsed = self::normaliseYear($parsed);
        $after = $parsed['year'];

        self::yearIssue($url, $before, $after, $issues);

        return $parsed;
    }

    private static function yearIssue(
        string $url,
        mixed $before,
        mixed $after,
        IssueBuffer $issues,
    ): void {
        if ($after === null) {
            $issues->add('invalid_year', 'year', $url, self::displayValue($before));

            return;
        }
        if (! is_numeric($before) || (int) $before !== $after) {
            $issues->add('year_pages_swap', 'year', $url, self::displayValue($before));
        }
    }

    /**
     * @param  ParsedItem  $parsed
     * @return ParsedItem
     */
    private static function normaliseYear(array $parsed): array
    {
        $raw = $parsed['year'];
        if (! is_numeric($raw)) {
            $parsed['year'] = null;

            return $parsed;
        }
        $year = (int) $raw;
        if ($year >= self::MIN_YEAR && $year <= self::MAX_YEAR) {
            $parsed['year'] = $year;

            return $parsed;
        }

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

    /** @param ParsedItem $parsed */
    private static function checkContentQuality(array $parsed, string $url, IssueBuffer $issues): void
    {

        foreach (['title', 'author'] as $field) {
            $value = $parsed[$field] ?? null;
            if (is_string($value) && preg_match(self::HTML_TAG, $value) === 1) {
                $issues->add('html_in_text', $field, $url, mb_substr($value, 0, 100));
            }
        }

        $title = $parsed['title'] ?? null;
        if (! is_string($title)) {
            return;
        }
        $length = mb_strlen($title);
        if ($length < 2) {
            $issues->add('suspicious_title', 'title', $url, $title);
        } elseif ($length > 300) {
            $issues->add('suspicious_title', 'title', $url, "len={$length}");
        }
    }

    /** @param ParsedItem $parsed */
    private static function checkFormatConsistency(array $parsed, string $url, IssueBuffer $issues): void
    {
        $format = $parsed['format'] ?? null;
        $properties = is_array($parsed['properties'] ?? null) ? $parsed['properties'] : [];

        if ($format === 'audiobook' && array_key_exists('pages', $properties)) {
            $issues->add('format_mismatch', 'format', $url, 'audiobook with pages');
        }
        if (in_array($format, self::PAGED_FORMATS, true) && array_key_exists('duration', $properties)) {
            $issues->add('format_mismatch', 'format', $url, "{$format} with duration");
        }
    }

    /**
     * @param  ParsedItem  $parsed
     * @param  AttributeSchema  $schema
     */
    private static function checkAttributes(
        array $parsed,
        string $url,
        array $schema,
        IssueBuffer $issues,
    ): void {
        $properties = $parsed['properties'] ?? null;
        if (! is_array($properties)) {
            return;
        }
        $allowed = $schema['allowed_keys'];

        foreach ($properties as $key => $value) {
            if (! is_string($key)) {
                $issues->add(
                    'attribute_unknown_key',
                    'properties',
                    $url,
                    self::displayValue($key).'='.self::displayValue($value),
                );

                continue;
            }
            if (! in_array($key, $allowed, true)) {
                $issues->add(
                    'attribute_unknown_key',
                    'properties',
                    $url,
                    $key.'='.self::displayValue($value),
                );

                continue;
            }
            $rule = $schema['rules'][$key] ?? null;
            if ($rule === null || $value === null) {
                continue;
            }
            $stringValue = self::scalarString($value);
            if ($stringValue === null) {
                $issues->add('attribute_invalid_value', $key, $url, 'value is not scalar');

                continue;
            }
            $enum = self::stringList($rule['enum'] ?? null);
            if ($enum !== null && ! in_array($stringValue, $enum, true)) {
                $issues->add(
                    'attribute_invalid_value',
                    $key,
                    $url,
                    "not in enum: {$stringValue}"
                );
            }
            $pattern = $rule['pattern'] ?? null;
            if (is_string($pattern)
                && preg_match('/^(?:'.$pattern.')$/u', $stringValue) !== 1) {
                $issues->add(
                    'attribute_invalid_value',
                    $key,
                    $url,
                    "pattern mismatch: {$stringValue}"
                );
            }
        }
    }

    private static function decimal(mixed $value): ?string
    {
        if (is_int($value) || is_float($value)) {
            return (string) $value;
        }
        if (! is_string($value)) {
            return null;
        }
        $trimmed = trim($value);

        return preg_match('/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/', $trimmed) === 1
            ? $trimmed
            : null;
    }

    private static function scalarString(mixed $value): ?string
    {
        if (is_string($value)) {
            return $value;
        }
        if (is_int($value) || is_float($value)) {
            return (string) $value;
        }

        return null;
    }

    private static function displayValue(mixed $value): string
    {
        $scalar = self::scalarString($value);
        if ($scalar !== null) {
            return $scalar;
        }
        if (is_bool($value)) {
            return $value ? 'true' : 'false';
        }
        if ($value === null) {
            return 'null';
        }

        $encoded = json_encode($value);

        return is_string($encoded) ? $encoded : get_debug_type($value);
    }

    /** @return list<string>|null */
    private static function stringList(mixed $value): ?array
    {
        if (! is_array($value)) {
            return null;
        }

        $strings = [];
        foreach ($value as $item) {
            if (! is_string($item)) {
                return null;
            }
            $strings[] = $item;
        }

        return $strings;
    }
}
