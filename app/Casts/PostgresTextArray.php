<?php

declare(strict_types=1);

namespace App\Casts;

use Illuminate\Contracts\Database\Eloquent\CastsAttributes;
use Illuminate\Database\Eloquent\Model;
use InvalidArgumentException;

/** @implements CastsAttributes<list<string>, list<string>|string> */
final class PostgresTextArray implements CastsAttributes
{
    /** @return list<string> */
    public function get(Model $model, string $key, mixed $value, array $attributes): array
    {
        if ($value === null || $value === '') {
            return [];
        }
        if (is_array($value)) {
            return $this->stringList($value);
        }

        if (! is_string($value)) {
            throw new InvalidArgumentException("{$key} must be a PostgreSQL array literal or string list.");
        }

        return self::parse($value);
    }

    public function set(Model $model, string $key, mixed $value, array $attributes): ?string
    {
        if ($value === null) {
            return null;
        }
        $items = is_array($value) ? $this->stringList($value) : [$value];

        return self::encode($items);
    }

    /** @return list<string> */
    public static function parse(string $literal): array
    {
        $literal = trim($literal);
        if ($literal === '{}' || $literal === '') {
            return [];
        }

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
                $inQuotes = ! $inQuotes;

                $wasQuoted = true;

                continue;
            }
            if ($char === ',' && ! $inQuotes) {
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
            static fn (string $item): string => '"'.str_replace(['\\', '"'], ['\\\\', '\\"'], $item).'"',
            $items
        );

        return '{'.implode(',', $quoted).'}';
    }

    /**
     * @param  array<array-key, mixed>  $items
     * @return list<string>
     */
    private function stringList(array $items): array
    {
        $strings = [];
        foreach ($items as $item) {
            if (! is_string($item)) {
                throw new InvalidArgumentException('PostgreSQL text arrays may contain only strings.');
            }
            $strings[] = $item;
        }

        return $strings;
    }
}
