<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

final class Book extends Model
{
    protected $table = 'books';

    public $timestamps = false;
}
