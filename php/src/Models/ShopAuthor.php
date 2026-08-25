<?php

declare(strict_types=1);

namespace BookScraper\Models;

use Illuminate\Database\Eloquent\Model;
use BookScraper\Models\Concerns\HasSqlAlchemyDefaults;

/**
 * Author as a shop spells it. `normalized_name` is the dedupe key and is
 * shared across shops, so two shops writing "J. R. R. Tolkien" and
 * "j.r.r. tolkien" converge on one row.
 *
 * @property int $id
 * @property string $name
 * @property string $normalized_name
 */
final class ShopAuthor extends Model
{
    protected $table = 'shop_authors';

    public $timestamps = false;

    use HasSqlAlchemyDefaults;

    public const TIMESTAMP_DEFAULTS = ['created_at'];

    protected $fillable = ['name', 'normalized_name', 'created_at', 'canonical_author_id'];

    protected $casts = ['created_at' => 'datetime'];
}
