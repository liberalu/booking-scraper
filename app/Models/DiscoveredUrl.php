<?php

declare(strict_types=1);

namespace App\Models;

use App\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasOne;
use Illuminate\Support\Carbon;

/**
 * @property int $id
 * @property int $shop_id
 * @property string $url
 * @property string $normalized_url
 * @property string $url_type
 * @property string|null $source
 * @property int $fail_count
 * @property int|null $last_http_status
 * @property Carbon|null $last_checked_at
 * @property Carbon $first_seen_at
 * @property Carbon $last_seen_at
 * @property int|null $shop_book_id
 * @property-read Shop $shop
 * @property-read ShopBook|null $shopBook
 * @property-read UrlClassification|null $classification
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

    /** @return BelongsTo<Shop, $this> */
    public function shop(): BelongsTo
    {
        return $this->belongsTo(Shop::class, 'shop_id');
    }

    /** @return BelongsTo<ShopBook, $this> */
    public function shopBook(): BelongsTo
    {
        return $this->belongsTo(ShopBook::class, 'shop_book_id');
    }

    /** @return HasOne<UrlClassification, $this> */
    public function classification(): HasOne
    {
        return $this->hasOne(UrlClassification::class, 'discovered_url_id');
    }
}
