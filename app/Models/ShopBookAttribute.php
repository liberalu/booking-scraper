<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

/**
 * Format-specific key/value metadata (pages, cover_type, duration,
 * narrator…), unique on (shop_book_id, key).
 *
 * @property int $shop_book_id
 * @property string $key
 * @property string|null $value
 */
final class ShopBookAttribute extends Model
{
    protected $table = 'shop_book_attributes';

    public $timestamps = false;

    protected $fillable = ['shop_book_id', 'key', 'value'];
}
