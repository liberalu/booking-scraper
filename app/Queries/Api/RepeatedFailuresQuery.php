<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\Repositories\RepeatedFailureReadRepository;

final readonly class RepeatedFailuresQuery
{
    public function __construct(private RepeatedFailureReadRepository $failures) {}

    /** @return array<string, mixed> */
    public function __invoke(): array
    {
        return ($this->failures)();
    }
}
