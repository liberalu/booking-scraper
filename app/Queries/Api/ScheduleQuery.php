<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\Repositories\ScheduleReadRepository;

final readonly class ScheduleQuery
{
    public function __construct(private ScheduleReadRepository $schedule) {}

    /** @return array<string, mixed> */
    public function __invoke(): array
    {
        return ($this->schedule)();
    }
}
