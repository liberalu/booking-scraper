<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\CronJob;
use App\Models\ScrapeRun;
use App\Support\RunPresenter;
use Cron\CronExpression;
use Illuminate\Support\Carbon;
use Throwable;

final class ScheduleReadRepository
{
    /** @return array<string, mixed> */
    public function __invoke(): array
    {
        $now = Carbon::now('UTC');

        $items = CronJob::orderBy('id')
            ->with('shop')
            ->where('enabled', true)
            ->get()
            ->map(function (CronJob $job) use ($now): array {
                [$nextAt, $nextInSeconds] = $this->nextFiring($job->cron_expression, $now);

                $lastOk = ScrapeRun::orderByRaw('finished_at desc nulls last')
                    ->where('shop_id', $job->shop_id)
                    ->where('phase', $job->runPhase())
                    ->where('status', 'completed')
                    ->first();

                return [
                    'shop' => $job->shop->name,
                    'phase' => $job->phase,
                    'cron_expression' => $job->cron_expression,
                    'next_run_at' => $nextAt,
                    'next_run_in_s' => $nextInSeconds,
                    'last_success_at' => RunPresenter::iso($lastOk?->finished_at),
                    'last_run_at' => RunPresenter::iso($job->last_run_at),
                ];
            })
            ->all();

        return ['items' => $items];
    }

    /** @return array{string|null, int|null} */
    private function nextFiring(string $expression, Carbon $now): array
    {
        try {
            $next = Carbon::instance(
                (new CronExpression($expression))->getNextRunDate($now)
            )->utc();
        } catch (Throwable) {
            return [null, null];
        }

        return [RunPresenter::iso($next), (int) $now->diffInSeconds($next, true)];
    }
}
