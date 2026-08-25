<?php

declare(strict_types=1);

namespace BookScraper\Casts;

use Illuminate\Contracts\Database\Eloquent\CastsAttributes;
use Illuminate\Database\Eloquent\Model;

/**
 * Cast for a Postgres `text[]` / `varchar[]` column (shop_books.categories).
 *
 * Eloquent has no native PG array support and would hand back the raw
 * literal `{"Grožinė literatūra","Romanai"}`. Quoting is parsed properly
 * rather than split on commas: category names can legitimately contain a
 * comma, and a naive split would silently shard one category into two —
 * which then feeds the book/non-book classifier.
 *
 * @implements CastsAttributes<list<string>, list<string>>
 */
final class PostgresTextArray implements CastsAttributes
{
    /** @return list<string> */
    public function get(Model $model, string $key, mixed $value, array $attributes): array
    {
        if ($value === null || $value === '') {
            return [];
        }
        if (is_array($value)) {
            return array_values($value);
        }

        return self::parse((string) $value);
    }

    public function set(Model $model, string $key, mixed $value, array $attributes): ?string
    {
        if ($value === null) {
            return null;
        }
        $items = is_array($value) ? $value : [$value];

        return self::encode(array_map('strval', array_values($items)));
    }

    /** @return list<string> */
    public static function parse(string $literal): array
    {
        $literal = trim($literal);
        if ($literal === '{}' || $literal === '') {
            return [];
        }
        // Drop the enclosing braces before scanning elements.
        if (str_starts_with($literal, '{') && str_ends_with($literal, '}')) {
            $literal = substr($literal, 1, -1);
        }

        $items = [];
        $current = '';
        $wasQuoted = false;
        $inQuotes = false;
        $escaped = false;
        $length = strlen($literal);

        for ($i = 0; $i < $length; $i++) {
            $char = $literal[$i];

            if ($escaped) {
                $current .= $char;
                $escaped = false;
                continue;
            }
            if ($char === '\\') {
                $escaped = true;
                continue;
            }
            if ($char === '"') {
                $inQuotes = !$inQuotes;
                // Remember the element was quoted: that is the only thing
                // separating the string 'NULL' from a real SQL null, and
                // the only thing that makes a quoted empty string real.
                $wasQuoted = true;
                continue;
            }
            if ($char === ',' && !$inQuotes) {
                $items[] = [$current, $wasQuoted];
                $current = '';
                $wasQuoted = false;
                continue;
            }
            $current .= $char;
        }
        $items[] = [$current, $wasQuoted];

        $out = [];
        foreach ($items as [$value, $quoted]) {
            if ($quoted) {
                $out[] = $value;
                continue;
            }
            // Unquoted: NULL is the null marker and whitespace is padding.
            $trimmed = trim($value);
            if ($trimmed !== '' && $trimmed !== 'NULL') {
                $out[] = $trimmed;
            }
        }

        return $out;
    }

    /** @param list<string> $items */
    public static function encode(array $items): string
    {
        if ($items === []) {
            return '{}';
        }
        $quoted = array_map(
            static fn (string $item): string => '"' . str_replace(['\\', '"'], ['\\\\', '\\"'], $item) . '"',
            $items
        );

        return '{' . implode(',', $quoted) . '}';
    }
}
