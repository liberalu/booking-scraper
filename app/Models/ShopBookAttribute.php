<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

final class ShopBookAttribute extends Model
{
    protected $table = 'shop_book_attributes';

    public $timestamps = false;

    protected $fillable = ['shop_book_id', 'key', 'value'];
}
