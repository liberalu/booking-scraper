<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\Repositories\OverviewReadRepository;

final readonly class OverviewQuery
{
    public function __construct(private OverviewReadRepository $overview) {}

    /** @return array<string, mixed> */
    public function __invoke(): array
    {
        return ($this->overview)();
    }
}
