<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class UrlQueryInput
{
    public function __construct(
        public int $page,
        public int $perPage,
        public string $sortBy,
        public string $sortOrder,
        public string $shop,
        public string $urlType,
        public string $search,
        public string $isBook,
        public bool $hasBook,
        public bool $failing,
    ) {}
}
