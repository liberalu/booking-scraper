<?php

declare(strict_types=1);

namespace App\Models;

use App\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/**
 * A scheduled phase run. `phase` + `strategy` are stored separately here,
 * while scrape_runs stores the combined value ('discover_sitemap') — see
 * runPhase() for the mapping, which is load-bearing: 'scan' takes no
 * strategy suffix regardless of strategy, because 'scan_delta' is not a
 * valid scrape_phase enum value.
 *
 * @property int $id
 * @property int $shop_id
 * @property string $phase
 * @property string|null $strategy
 * @property string $cron_expression
 * @property bool $enabled
 */
final class CronJob extends Model
{
    use HasSqlAlchemyDefaults;

    /** `created_at` is a Python-side SQLAlchemy default, not a server one. */
    public const TIMESTAMP_DEFAULTS = ['created_at'];

    protected $table = 'cron_jobs';

    public $timestamps = false;

    protected $casts = [
        'enabled' => 'boolean',
        'last_run_at' => 'datetime',
        'created_at' => 'datetime',
    ];

    public function shop(): BelongsTo
    {
        return $this->belongsTo(Shop::class, 'shop_id');
    }

    public function chainTo(): BelongsTo
    {
        return $this->belongsTo(self::class, 'chain_to_job_id');
    }

    /** The scrape_runs.phase value this job produces. */
    public function runPhase(): string
    {
        if ($this->phase === 'scan') {
            return 'scan';
        }
        if ($this->phase === 'discover' && $this->strategy) {
            return "discover_{$this->strategy}";
        }

        return $this->phase;
    }
}
