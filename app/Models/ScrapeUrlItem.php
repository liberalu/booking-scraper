<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use App\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/**
 * Persistent work queue for the scan phase — this is what makes a run
 * resumable. Rows left in `processing` by a dead process are reset to
 * `pending` on the next start.
 *
 * @property int $id
 * @property int $run_id
 * @property string $url
 * @property string $status
 * @property int $attempts
 */
final class ScrapeUrlItem extends Model
{
    protected $table = 'scrape_url_items';

    public $timestamps = false;

    use HasSqlAlchemyDefaults;

    public const TIMESTAMP_DEFAULTS = ['created_at'];

    protected $fillable = [
        'run_id', 'shop_id', 'discovered_url_id', 'url', 'url_type',
        'status', 'created_at', 'claimed_at', 'done_at', 'http_status',
        'request_delay_s', 'delay_source', 'retry_count', 'attempts',
        'response_bytes',
    ];

    protected $casts = [
        'http_status' => 'integer',
        'retry_count' => 'integer',
        'attempts' => 'integer',
        'response_bytes' => 'integer',
        'request_delay_s' => 'float',
        'created_at' => 'datetime',
        'claimed_at' => 'datetime',
        'done_at' => 'datetime',
    ];

    public function run(): BelongsTo
    {
        return $this->belongsTo(ScrapeRun::class, 'run_id');
    }

    public function discoveredUrl(): BelongsTo
    {
        return $this->belongsTo(DiscoveredUrl::class, 'discovered_url_id');
    }
}
