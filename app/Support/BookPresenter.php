<?php

declare(strict_types=1);

namespace App\Support;

use App\Models\ShopBook;

/** Port of _book_dict in book_scraper/dashboard/routes/api.py. */
final class BookPresenter
{
    /** @return array<string, mixed> */
    public static function toArray(ShopBook $sb): array
    {
        return [
            'id' => $sb->id,
            'title' => $sb->title,
            'author' => $sb->author ?: '—',
            'shop' => $sb->shop->name ?? '—',
            'isbn' => $sb->isbn,
            'sku' => $sb->sku,
            'price' => $sb->price !== null ? '€' . number_format((float) $sb->price, 2, '.', '') : '—',
            'price_raw' => $sb->price !== null ? (float) $sb->price : null,
            'status' => self::status($sb),
            // Python hardcodes 0; per-book issue counts come from the detail page.
            'issues' => 0,
            'updated' => RunPresenter::relative($sb->last_seen_at),
            'url' => $sb->url,
            'publisher' => $sb->publisher,
            'year' => $sb->year,
            'format' => $sb->format,
            'type' => $sb->type,
            'in_stock' => $sb->in_stock,
            'is_active' => $sb->is_active,
            'first_seen_at' => RunPresenter::iso($sb->first_seen_at),
            'last_seen_at' => RunPresenter::iso($sb->last_seen_at),
            'planned_availability_date' => $sb->planned_availability_date?->toDateString(),
            'rating' => $sb->rating !== null ? (float) $sb->rating : null,
            'review_count' => $sb->review_count,
            'book_id' => $sb->book_id,
        ];
    }

    /** active / out (was active, now flagged) / delisted (never flagged). */
    private static function status(ShopBook $sb): string
    {
        if ($sb->is_active) {
            return 'active';
        }

        return $sb->inactive_since !== null ? 'out' : 'delisted';
    }
}
