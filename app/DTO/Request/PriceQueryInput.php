<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class PriceQueryInput
{
    public function __construct(
        public int $days,
        public int $page,
        public int $perPage,
        public string $shop,
    ) {}
}
