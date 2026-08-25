<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\RunPresenter;
use BookScraper\Models\CronJob;
use BookScraper\Models\ScrapeRun;
use Cron\CronExpression;
use Illuminate\Support\Carbon;
use Throwable;

/**
 * GET /api/schedule — next firing time + last success per enabled cron job.
 * Feeds the "Next run in 4h 23m" / "Last success: 3h ago" badges.
 */
final class ScheduleController
{
    public function __invoke(): array
    {
        $now = Carbon::now('UTC');

        $items = CronJob::with('shop')
            ->where('enabled', true)
            ->orderBy('id')
            ->get()
            ->map(function (CronJob $job) use ($now): array {
                [$nextAt, $nextInSeconds] = self::nextFiring($job->cron_expression, $now);

                $lastOk = ScrapeRun::where('shop_id', $job->shop_id)
                    ->where('phase', $job->runPhase())
                    ->where('status', 'completed')
                    ->orderByRaw('finished_at desc nulls last')
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

    /**
     * An unparseable expression yields nulls rather than a 500 — a typo in
     * one job shouldn't take down the whole schedule badge.
     *
     * @return array{0: string|null, 1: int|null}
     */
    private static function nextFiring(string $expression, Carbon $now): array
    {
        try {
            $next = Carbon::instance(
                (new CronExpression($expression))->getNextRunDate($now)
            )->utc();
        } catch (Throwable) {
            return [null, null];
        }

        return [RunPresenter::iso($next), (int) $now->diffInRealSeconds($next, true)];
    }
}
