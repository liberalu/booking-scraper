<?php

declare(strict_types=1);

namespace BookScraper\Models;

use Illuminate\Database\Eloquent\Model;

/**
 * ISBNs belonging to a canonical book. Read by the ISBN-drift guard to
 * decide whether an existing match is still valid.
 *
 * @property int $book_id
 * @property string $isbn
 * @property string $isbn_type
 */
final class BookIsbn extends Model
{
    protected $table = 'book_isbns';

    public $timestamps = false;

    protected $fillable = ['book_id', 'isbn', 'isbn_type'];
}
