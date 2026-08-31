<?php

declare(strict_types=1);

namespace App\Models;

use App\Casts\PostgresTextArray;
use App\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Support\Carbon;

/**
 * @property int $id
 * @property int $shop_id
 * @property string $url
 * @property string $title
 * @property string|null $author
 * @property string|null $isbn
 * @property string|null $sku
 * @property string|null $publisher
 * @property int|null $year
 * @property string|null $format
 * @property string $type
 * @property string|null $description
 * @property string|null $image_url
 * @property list<string>|null $categories
 * @property numeric-string|null $price
 * @property numeric-string|null $price_original
 * @property bool $in_stock
 * @property bool $is_active
 * @property Carbon|null $planned_availability_date
 * @property-write Carbon|string|null $planned_availability_date
 * @property numeric-string|null $rating
 * @property int|null $review_count
 * @property int|null $book_id
 * @property int|null $last_run_id
 * @property Carbon $first_seen_at
 * @property Carbon $last_seen_at
 * @property Carbon|null $inactive_since
 * @property Shop $shop
 */
final class ShopBook extends Model
{
    protected $table = 'shop_books';

    public $timestamps = false;

    use HasSqlAlchemyDefaults;

    public const TIMESTAMP_DEFAULTS = ['first_seen_at', 'last_seen_at'];

    protected $attributes = [
        'in_stock' => true,
        'is_active' => true,
        'match_status' => 'unmatched',
        'type' => 'book',
    ];

    protected $fillable = [
        'shop_id', 'url', 'title', 'author', 'sku', 'isbn', 'publisher',
        'year', 'format', 'type', 'description', 'image_url', 'categories',
        'price', 'price_original', 'in_stock', 'planned_availability_date',
        'rating', 'review_count', 'last_run_id', 'last_run_action',
        'created_run_id', 'is_active', 'inactive_since',
        'first_seen_at', 'last_seen_at',
    ];

    protected $casts = [
        'categories' => PostgresTextArray::class,
        'year' => 'integer',
        'review_count' => 'integer',
        'in_stock' => 'boolean',
        'is_active' => 'boolean',
        'planned_availability_date' => 'date',
        'first_seen_at' => 'datetime',
        'last_seen_at' => 'datetime',
        'inactive_since' => 'datetime',
    ];

    /** @return BelongsTo<Shop, $this> */
    public function shop(): BelongsTo
    {
        return $this->belongsTo(Shop::class, 'shop_id');
    }

    /** @return HasMany<Price, $this> */
    public function prices(): HasMany
    {
        return $this->hasMany(Price::class, 'shop_book_id');
    }
}
