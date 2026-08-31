<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class ShopBookQueryInput
{
    public function __construct(
        public int $page,
        public int $perPage,
        public string $shop,
        public string $search,
        public string $category,
        public string $type,
        public string $format,
        public string $missingField,
        public string $active,
        public string $linked,
        public string $sortBy,
        public string $sortOrder,
        public bool $hasIsbn,
        public bool $urlUnreachable,
    ) {}
}
