<?php

declare(strict_types=1);

namespace App\Models\Concerns;

use Illuminate\Support\Carbon;

/**
 * Mirrors SQLAlchemy's model-level `default=` values.
 *
 * Several NOT NULL columns in this schema have no *server* default — the
 * Python models declare them Python-side (`default="unmatched"`,
 * `default=datetime.utcnow`). Eloquent knows nothing about those, so any
 * write path that doesn't set them explicitly inserts NULL and trips the
 * constraint. Declaring them once per model means every PHP writer gets the
 * same defaults the Python writers get, instead of each call site
 * remembering.
 *
 * Scalar defaults go in the model's $attributes; timestamp defaults need a
 * value at insert time, so they are listed in TIMESTAMP_DEFAULTS and filled
 * on create.
 */
trait HasSqlAlchemyDefaults
{
    public static function bootHasSqlAlchemyDefaults(): void
    {
        static::creating(function ($model): void {
            foreach ($model::TIMESTAMP_DEFAULTS as $column) {
                if ($model->{$column} === null) {
                    $model->{$column} = Carbon::now('UTC');
                }
            }
        });
    }
}
