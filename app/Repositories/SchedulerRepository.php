<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\CronJob;
use App\Repositories\Contracts\SchedulerRepositoryInterface;
use Illuminate\Support\Facades\DB;

final class SchedulerRepository implements SchedulerRepositoryInterface
{
    private const LOCK_NAMESPACE = 7351;

    /** @return iterable<CronJob> */
    public function enabledJobs(): iterable
    {
        return CronJob::orderBy('id')->with('shop')->where('enabled', true)->get();
    }

    public function activePhase(CronJob $job): ?string
    {
        $run = DB::table('scrape_runs')
            ->where('shop_id', $job->shop_id)
            ->whereIn('status', ['running', 'stopping'])
            ->orderBy('id')
            ->first();

        return DatabaseRow::nullable($run)?->nullableString('phase');
    }

    public function tryAcquireShop(int $shopId): bool
    {
        return DatabaseRow::from(DB::selectOne(
            'select pg_try_advisory_lock(?, ?) as acquired',
            [self::LOCK_NAMESPACE, $shopId],
        ))->bool('acquired');
    }

    public function releaseShop(int $shopId): bool
    {
        return DatabaseRow::from(DB::selectOne(
            'select pg_advisory_unlock(?, ?) as released',
            [self::LOCK_NAMESPACE, $shopId],
        ))->bool('released');
    }
}
