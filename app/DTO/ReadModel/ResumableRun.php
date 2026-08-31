<?php

declare(strict_types=1);

namespace App\DTO\ReadModel;

final readonly class ResumableRun
{
    public function __construct(
        public int $id,
        public int $shopId,
        public string $phase,
        public string $status,
        public bool $resumableAfterFailure,
    ) {}
}
