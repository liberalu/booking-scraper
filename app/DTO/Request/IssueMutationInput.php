<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class IssueMutationInput
{
    public function __construct(
        public string $state,
        public int $days,
        public string $issueType,
        public string $shop,
    ) {}
}
