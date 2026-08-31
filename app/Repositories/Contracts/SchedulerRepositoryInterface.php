<?php

declare(strict_types=1);

namespace App\Repositories\Contracts;

use App\Models\CronJob;

interface SchedulerRepositoryInterface
{
    /** @return iterable<CronJob> */
    public function enabledJobs(): iterable;

    public function activePhase(CronJob $job): ?string;

    public function tryAcquireShop(int $shopId): bool;

    public function releaseShop(int $shopId): bool;
}
