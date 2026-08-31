<?php

declare(strict_types=1);

namespace App\Repositories\Contracts;

use App\Models\ScrapeRun;

interface RunLifecycleRepositoryInterface
{
    public function start(int $shopId, string $phase, ?int $urlsTotal): ScrapeRun;

    public function find(int $runId): ScrapeRun;

    public function adopt(int $runId): void;

    public function progress(
        int $runId,
        int $processed,
        int $added,
        int $updated,
        int $errors,
    ): void;

    public function finish(int $runId, string $status, ?string $closeReason): void;

    public function stampCronJob(int $shopId, string $phase, ?string $strategy): void;
}
