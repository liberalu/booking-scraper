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
 * @property string $phase
 * @property string $status
 * @property Carbon|null $started_at
 * @property Carbon|null $finished_at
 * @property Carbon|null $last_heartbeat
 * @property int|null $urls_total
 * @property int $urls_processed
 * @property int $items_added
 * @property int $items_updated
 * @property int $errors_4xx
 * @property int $errors_5xx
 * @property int $error_count
 * @property string|null $close_reason
 * @property bool $resumable_after_failure
 * @property int|null $pid
 * @property Shop $shop
 */
final class ScrapeRun extends Model
{
    protected $table = 'scrape_runs';

    public $timestamps = false;

    use HasSqlAlchemyDefaults;

    public const array TIMESTAMP_DEFAULTS = ['started_at'];

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

    /** @return BelongsTo<Shop, $this> */
    public function shop(): BelongsTo
    {
        return $this->belongsTo(Shop::class, 'shop_id');
    }
}
