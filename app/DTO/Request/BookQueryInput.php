<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class BookQueryInput
{
    public function __construct(
        public int $page,
        public int $perPage,
        public ?int $year,
        public ?int $shopCountMin,
        public ?int $shopCountMax,
        public ?bool $hasIsbn,
        public ?bool $hasShops,
        public ?bool $hasConflicts,
        public ?string $dataSource,
        public string $search,
        public ?string $format,
    ) {}

    public function withPagination(int $page, int $perPage): self
    {
        return new self(
            page: $page,
            perPage: $perPage,
            year: $this->year,
            shopCountMin: $this->shopCountMin,
            shopCountMax: $this->shopCountMax,
            hasIsbn: $this->hasIsbn,
            hasShops: $this->hasShops,
            hasConflicts: $this->hasConflicts,
            dataSource: $this->dataSource,
            search: $this->search,
            format: $this->format,
        );
    }
}
