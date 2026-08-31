<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ShopBook;

final readonly class UpsertResult
{
    /** @param list<array{field: string, old: mixed, new: mixed}> $changes */
    public function __construct(
        public ShopBook $shopBook,
        public bool $created,
        public ?string $oldPrice,
        public array $changes,
    ) {}
}
