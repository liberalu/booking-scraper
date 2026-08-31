<?php

declare(strict_types=1);

namespace App\Models;

use App\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

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

    /** @return BelongsTo<ScrapeRun, $this> */
    public function run(): BelongsTo
    {
        return $this->belongsTo(ScrapeRun::class, 'run_id');
    }

    /** @return BelongsTo<DiscoveredUrl, $this> */
    public function discoveredUrl(): BelongsTo
    {
        return $this->belongsTo(DiscoveredUrl::class, 'discovered_url_id');
    }
}
