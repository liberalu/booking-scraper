<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ShopBook;

/**
 * Outcome of ShopBookRepository::upsert(), mirroring the Python tuple
 * `(shop_book, created, old_price, changes)`.
 *
 * `oldPrice` is what the row held before this scrape — the pipeline needs
 * it to decide whether to append a `prices` row.
 */
final readonly class UpsertResult
{
    /** @param list<array{field: string, old: string|null, new: string|null}> $changes */
    public function __construct(
        public ShopBook $shopBook,
        public bool $created,
        public ?string $oldPrice,
        public array $changes,
    ) {}
}
