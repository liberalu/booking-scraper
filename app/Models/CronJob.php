<?php

declare(strict_types=1);

namespace App\Models;

use App\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Support\Carbon;

/**
 * @property int $id
 * @property int $shop_id
 * @property int|null $chain_to_job_id
 * @property string $phase
 * @property string|null $strategy
 * @property bool $enabled
 * @property string $cron_expression
 * @property Carbon|null $last_run_at
 * @property string|null $args
 * @property Shop $shop
 */
final class CronJob extends Model
{
    use HasSqlAlchemyDefaults;

    public const TIMESTAMP_DEFAULTS = ['created_at'];

    protected $table = 'cron_jobs';

    public $timestamps = false;

    protected $casts = [
        'enabled' => 'boolean',
        'last_run_at' => 'datetime',
        'created_at' => 'datetime',
    ];

    /** @return BelongsTo<Shop, $this> */
    public function shop(): BelongsTo
    {
        return $this->belongsTo(Shop::class, 'shop_id');
    }

    /** @return BelongsTo<CronJob, $this> */
    public function chainTo(): BelongsTo
    {
        return $this->belongsTo(self::class, 'chain_to_job_id');
    }

    public function runPhase(): string
    {
        if ($this->phase === 'scan') {
            return 'scan';
        }
        if ($this->phase === 'discover' && $this->strategy !== null && $this->strategy !== '') {
            return "discover_{$this->strategy}";
        }

        return $this->phase;
    }
}
