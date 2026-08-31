<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

final class BookIsbn extends Model
{
    protected $table = 'book_isbns';

    public $timestamps = false;

    protected $fillable = ['book_id', 'isbn', 'isbn_type'];
}
