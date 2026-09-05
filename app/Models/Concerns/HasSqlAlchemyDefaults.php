<?php

declare(strict_types=1);

namespace App\Models\Concerns;

use Illuminate\Support\Facades\Date;

trait HasSqlAlchemyDefaults
{
    public static function bootHasSqlAlchemyDefaults(): void
    {
        static::creating(function (self $model): void {
            $defaults = constant($model::class.'::TIMESTAMP_DEFAULTS');
            foreach ($defaults as $column) {
                if ($model->getAttribute($column) === null) {
                    $model->setAttribute($column, Date::now('UTC'));
                }
            }
        });
    }
}
