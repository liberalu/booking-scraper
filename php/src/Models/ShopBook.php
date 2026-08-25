<?php

declare(strict_types=1);

namespace BookScraper\Models;

use BookScraper\Casts\PostgresTextArray;
use BookScraper\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

/**
 * One row per book-as-it-appears-in-a-shop. Unique on (shop_id, url).
 *
 * `book_id` is written only by the match phase and is deliberately not
 * fillable here: match linkage is strictly ISBN-exact, and a scraper
 * writing it would reintroduce the `match_isbn_drift` class of bug.
 *
 * @property int $id
 * @property int $shop_id
 * @property string $url
 * @property string $title
 * @property string|null $isbn
 * @property list<string> $categories
 * @property bool $in_stock
 * @property bool $is_active
 */
final class ShopBook extends Model
{
    protected $table = 'shop_books';

    public $timestamps = false;

    use HasSqlAlchemyDefaults;

    /** Columns Postgres has no default for; see the trait. */
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

    public function shop(): BelongsTo
    {
        return $this->belongsTo(Shop::class, 'shop_id');
    }

    public function prices(): HasMany
    {
        return $this->hasMany(Price::class, 'shop_book_id');
    }
}
