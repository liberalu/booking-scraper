<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\CronJob;
use App\Support\Database;
use Illuminate\Support\Facades\DB;

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

    public function databaseUrl(): string
    {
        $dsn = Database::bootedDsn();
        if ($dsn !== null) {
            return $dsn;
        }

        $config = DatabaseRow::from(DB::connection()->getConfig());

        return sprintf(
            'postgresql://%s:%s@%s:%s/%s',
            rawurlencode($config->nullableString('username') ?? ''),
            rawurlencode($config->nullableString('password') ?? ''),
            $config->nullableString('host') ?? '127.0.0.1',
            $config->nullableInt('port') ?? 5432,
            $config->nullableString('database') ?? '',
        );
    }
}
