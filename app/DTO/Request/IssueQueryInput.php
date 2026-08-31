<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class IssueQueryInput
{
    public function __construct(
        public ?string $state,
        public string $shop,
        public string $issueType,
        public ?int $runId,
        public string $severity,
        public ?string $urlType,
        public ?string $bookType,
        public string $search,
        public ?string $sortBy,
        public ?string $order,
        public ?int $page,
        public ?int $perPage,
        public ?string $kind,
        public ?string $groupBy,
        public ?int $days,
    ) {}
}
