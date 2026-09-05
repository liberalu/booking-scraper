<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

/**
 * @property int $id
 * @property int $shop_book_id
 * @property string $key
 * @property mixed $value
 */
final class ShopBookAttribute extends Model
{
    protected $table = 'shop_book_attributes';

    public $timestamps = false;

    protected $fillable = ['shop_book_id', 'key', 'value'];
}
