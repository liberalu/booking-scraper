<?php

declare(strict_types=1);

namespace BookScraper\Models;

use Illuminate\Database\Eloquent\Model;
use BookScraper\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasOne;

/**
 * Accumulate-only URL ledger, unique on (shop_id, normalized_url).
 * Rows are never deleted — `url_type` and `fail_count` carry the state.
 *
 * @property int $id
 * @property int $shop_id
 * @property string $url
 * @property string $normalized_url
 * @property string $source
 * @property string $url_type
 * @property int $fail_count
 */
final class DiscoveredUrl extends Model
{
    protected $table = 'discovered_urls';

    public $timestamps = false;

    use HasSqlAlchemyDefaults;

    public const TIMESTAMP_DEFAULTS = ['first_seen_at', 'last_seen_at'];

    protected $attributes = [
        'fail_count' => 0,
        'url_type' => 'unknown',
    ];

    protected $fillable = [
        'shop_id', 'url', 'normalized_url', 'source', 'url_type',
        'fail_count', 'last_http_status', 'last_checked_at',
        'first_seen_at', 'last_seen_at', 'last_seen_run_id', 'shop_book_id',
    ];

    protected $casts = [
        'fail_count' => 'integer',
        'last_http_status' => 'integer',
        'last_checked_at' => 'datetime',
        'first_seen_at' => 'datetime',
        'last_seen_at' => 'datetime',
    ];

    public function shop(): BelongsTo
    {
        return $this->belongsTo(Shop::class, 'shop_id');
    }

    public function shopBook(): BelongsTo
    {
        return $this->belongsTo(ShopBook::class, 'shop_book_id');
    }

    public function classification(): HasOne
    {
        return $this->hasOne(UrlClassification::class, 'discovered_url_id');
    }
}
