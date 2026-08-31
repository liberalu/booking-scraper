<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\Models\CronJob;
use App\Repositories\CronReadRepository;

final readonly class CronQuery
{
    public function __construct(private CronReadRepository $jobs) {}

    /** @return array<string, mixed> */
    public function index(): array
    {
        return $this->jobs->index();
    }

    /** @return array<string, mixed> */
    public function show(CronJob $job): array
    {
        return $this->jobs->show($job);
    }
}
