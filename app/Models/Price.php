<?php

declare(strict_types=1);

namespace App\Models;

use App\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

final class Price extends Model
{
    protected $table = 'prices';

    public $timestamps = false;

    use HasSqlAlchemyDefaults;

    public const TIMESTAMP_DEFAULTS = ['scraped_at'];

    protected $fillable = [
        'shop_book_id', 'price', 'price_original', 'in_stock',
        'scraped_at', 'scrape_run_id',
    ];

    protected $casts = [
        'in_stock' => 'boolean',
        'scraped_at' => 'datetime',
    ];

    protected $guarded = ['discount_pct'];

    /** @return BelongsTo<ShopBook, $this> */
    public function shopBook(): BelongsTo
    {
        return $this->belongsTo(ShopBook::class, 'shop_book_id');
    }
}
