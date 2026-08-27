<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/**
 * Book/non-book verdict for a discovered URL, written by the discover
 * phase's classifier.
 *
 * @property int $discovered_url_id
 * @property int|null $book_score
 * @property bool|null $is_book_product
 */
final class UrlClassification extends Model
{
    protected $table = 'url_classifications';

    public $timestamps = false;

    protected $casts = [
        'book_score' => 'integer',
        'is_book_product' => 'boolean',
    ];

    public function discoveredUrl(): BelongsTo
    {
        return $this->belongsTo(DiscoveredUrl::class, 'discovered_url_id');
    }
}
