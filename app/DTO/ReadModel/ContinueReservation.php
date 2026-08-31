<?php

declare(strict_types=1);

namespace App\DTO\ReadModel;

final readonly class ContinueReservation
{
    public function __construct(
        public string $phase,
        public RunStateSnapshot $previous,
    ) {}
}
