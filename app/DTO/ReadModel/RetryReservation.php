<?php

declare(strict_types=1);

namespace App\DTO\ReadModel;

final readonly class RetryReservation
{
    public function __construct(
        public int $matches,
        public bool $terminal,
        public string $status,
        public ?RunStateSnapshot $previous,
    ) {}
}
