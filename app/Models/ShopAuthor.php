<?php

declare(strict_types=1);

namespace App\Models;

use App\Models\Concerns\HasSqlAlchemyDefaults;
use Illuminate\Database\Eloquent\Model;

final class ShopAuthor extends Model
{
    protected $table = 'shop_authors';

    public $timestamps = false;

    use HasSqlAlchemyDefaults;

    public const array TIMESTAMP_DEFAULTS = ['created_at'];

    protected $fillable = ['name', 'normalized_name', 'created_at', 'canonical_author_id'];

    protected $casts = ['created_at' => 'datetime'];
}
