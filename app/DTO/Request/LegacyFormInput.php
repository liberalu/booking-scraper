<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class LegacyFormInput
{
    public function __construct(
        public float $downloadDelay,
        public int $concurrentRequestsPerDomain,
        public string $shop,
        public string $search,
        public string $author,
        public string $publisher,
        public string $category,
        public string $format,
        public string $missing,
        public string $active,
        public bool $hasIsbn,
        public string $output,
    ) {}
}
