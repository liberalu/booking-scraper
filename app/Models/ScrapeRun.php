<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use App\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Support\Carbon;

/**
 * One row per phase run. `last_heartbeat` is what the reaper watches, so
 * a long-running phase must keep touching it or it gets reaped as stalled.
 *
 * @property int $id
 * @property int $shop_id
 * @property string $phase
 * @property string $status
 * @property int $urls_processed
 */
final class ScrapeRun extends Model
{
    protected $table = 'scrape_runs';

    public $timestamps = false;

    use HasSqlAlchemyDefaults;

    public const TIMESTAMP_DEFAULTS = ['started_at'];

    protected $attributes = [
        'urls_processed' => 0,
        'items_added' => 0,
        'items_updated' => 0,
        'errors_4xx' => 0,
        'errors_5xx' => 0,
        'error_count' => 0,
        'resumable_after_failure' => false,
    ];

    protected $fillable = [
        'shop_id', 'phase', 'status', 'started_at', 'finished_at',
        'urls_total', 'urls_processed', 'items_added', 'items_updated',
        'errors_4xx', 'errors_5xx', 'error_count', 'last_heartbeat',
        'pid', 'close_reason', 'resumable_after_failure',
    ];

    protected $casts = [
        'urls_total' => 'integer',
        'urls_processed' => 'integer',
        'items_added' => 'integer',
        'items_updated' => 'integer',
        'errors_4xx' => 'integer',
        'errors_5xx' => 'integer',
        'error_count' => 'integer',
        'pid' => 'integer',
        'resumable_after_failure' => 'boolean',
        'started_at' => 'datetime',
        'finished_at' => 'datetime',
        'last_heartbeat' => 'datetime',
    ];

    public function shop(): BelongsTo
    {
        return $this->belongsTo(Shop::class, 'shop_id');
    }

    public static function start(int $shopId, string $phase): self
    {
        return self::create([
            'shop_id' => $shopId,
            'phase' => $phase,
            'status' => 'running',
            'started_at' => Carbon::now('UTC'),
            'last_heartbeat' => Carbon::now('UTC'),
            'pid' => getmypid() ?: null,
        ]);
    }

    public function heartbeat(): void
    {
        // Bypass the model so a heartbeat never flushes half-built state.
        static::withoutEvents(fn () => self::whereKey($this->id)
            ->update(['last_heartbeat' => Carbon::now('UTC')]));
    }

    public function finish(string $status, ?string $closeReason = null): void
    {
        $this->update([
            'status' => $status,
            'finished_at' => Carbon::now('UTC'),
            'close_reason' => $closeReason,
        ]);
    }
}
