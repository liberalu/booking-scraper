<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\CronJob;

final class PostPhaseRepository
{
    public function chainTarget(int $cronJobId): ?CronJob
    {
        $job = CronJob::find($cronJobId);
        if ($job === null || $job->chain_to_job_id === null) {
            return null;
        }

        return CronJob::with('shop')->find($job->chain_to_job_id);
    }
}
