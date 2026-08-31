<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/**
 * @property int $book_score
 * @property bool $is_book_product
 * @property list<array<string, mixed>> $reasons
 */
final class UrlClassification extends Model
{
    protected $table = 'url_classifications';

    public $timestamps = false;

    protected $casts = [
        'book_score' => 'integer',
        'is_book_product' => 'boolean',
        'reasons' => 'array',
    ];

    /** @return BelongsTo<DiscoveredUrl, $this> */
    public function discoveredUrl(): BelongsTo
    {
        return $this->belongsTo(DiscoveredUrl::class, 'discovered_url_id');
    }
}
