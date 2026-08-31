<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class CronMutationInput
{
    public function __construct(
        public string $shop,
        public ?string $phase,
        public ?string $cronExpression,
        public ?int $chainToId,
        public bool $clearChain,
        public ?string $strategy,
    ) {}
}
