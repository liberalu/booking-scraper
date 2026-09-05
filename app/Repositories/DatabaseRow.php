<?php

declare(strict_types=1);

namespace App\Repositories;

use Carbon\CarbonImmutable;
use DateTimeInterface;
use UnexpectedValueException;

final readonly class DatabaseRow
{
    /** @param array<string, mixed> $values */
    private function __construct(private array $values) {}

    public static function from(mixed $row): self
    {
        if (is_object($row)) {
            $row = get_object_vars($row);
        }
        if (! is_array($row)) {
            throw new UnexpectedValueException('Database result row must be an object or array.');
        }

        $values = [];
        foreach ($row as $key => $value) {
            if (is_string($key)) {
                $values[$key] = $value;
            }
        }

        return new self($values);
    }

    public static function nullable(mixed $row): ?self
    {
        return $row === null ? null : self::from($row);
    }

    public function value(string $column): mixed
    {
        return $this->values[$column] ?? null;
    }

    public function has(string $column): bool
    {
        return array_key_exists($column, $this->values);
    }

    public function string(string $column): string
    {
        $value = $this->nullableString($column);
        if ($value === null) {
            throw $this->invalid($column, 'string');
        }

        return $value;
    }

    public function nullableString(string $column): ?string
    {
        $value = $this->value($column);
        if ($value === null) {
            return null;
        }
        if (is_string($value)) {
            return $value;
        }
        if (is_int($value) || is_float($value)) {
            return (string) $value;
        }

        throw $this->invalid($column, 'string or null');
    }

    public function int(string $column): int
    {
        $value = $this->nullableInt($column);
        if ($value === null) {
            throw $this->invalid($column, 'integer');
        }

        return $value;
    }

    public function nullableInt(string $column): ?int
    {
        $value = $this->value($column);
        if ($value === null) {
            return null;
        }
        if (is_int($value)) {
            return $value;
        }
        if (is_string($value) && preg_match('/^-?\d+$/', $value) === 1) {
            return (int) $value;
        }

        throw $this->invalid($column, 'integer or null');
    }

    public function float(string $column): float
    {
        $value = $this->nullableFloat($column);
        if ($value === null) {
            throw $this->invalid($column, 'number');
        }

        return $value;
    }

    public function nullableFloat(string $column): ?float
    {
        $value = $this->value($column);
        if ($value === null) {
            return null;
        }
        if (is_int($value) || is_float($value)) {
            return (float) $value;
        }
        if (is_string($value) && is_numeric($value)) {
            return (float) $value;
        }

        throw $this->invalid($column, 'number or null');
    }

    public function bool(string $column): bool
    {
        $value = $this->value($column);
        if ($value === null) {
            throw $this->invalid($column, 'boolean');
        }

        return $this->toBool($column, $value);
    }

    public function nullableBool(string $column): ?bool
    {
        $value = $this->value($column);
        if ($value === null) {
            return null;
        }

        return $this->toBool($column, $value);
    }

    private function toBool(string $column, mixed $value): bool
    {
        if (is_bool($value)) {
            return $value;
        }
        if (in_array($value, [1, '1', 't', 'true'], true)) {
            return true;
        }
        if (in_array($value, [0, '0', 'f', 'false'], true)) {
            return false;
        }

        throw $this->invalid($column, 'boolean');
    }

    public function dateTime(string $column): CarbonImmutable
    {
        $value = $this->value($column);
        if ($value instanceof DateTimeInterface || is_string($value) || is_int($value) || is_float($value)) {
            return CarbonImmutable::parse($value);
        }

        throw $this->invalid($column, 'date and time');
    }

    private function invalid(string $column, string $expected): UnexpectedValueException
    {
        return new UnexpectedValueException("Database column {$column} must contain {$expected}.");
    }
}
