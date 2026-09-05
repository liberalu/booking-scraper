<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\CronJob;
use App\Support\RunPresenter;
use Cron\CronExpression;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use Throwable;

final class CronReadRepository
{
    private const array DISCOVER_STRATEGIES = [
        'sitemap', 'categories', 'full_crawl', 'graphql', 'lupasearch',
    ];

    private const int AVG_WINDOW = 30;

    /** @return array<string, mixed> */
    public function index(): array
    {
        $now = Date::now('UTC');

        $cronJobs = CronJob::orderBy('id')->with(['shop', 'chainTo.shop'])->get();
        $metricsByJob = $this->metricsForJobs($cronJobs);
        $jobs = [];
        foreach ($cronJobs as $job) {
            $runPhase = $this->runPhase($job->phase, $job->strategy);
            [$nextAt, $nextInSeconds] = $this->nextFiring($job->cron_expression, $now);
            $metrics = $metricsByJob[$this->metricKey($job->shop_id, $runPhase)] ?? [
                'last_status' => null,
                'avg_dur_s' => null,
            ];
            $chain = $job->chainTo;

            $jobs[] = [
                'id' => $job->id,
                'name' => $this->jobName($job),
                'shop' => $job->shop->name,
                'phase' => $job->phase,
                'strategy' => $job->strategy ?? '',
                'args' => $job->args,
                'cron' => $job->cron_expression,
                'enabled' => $job->enabled,
                'last' => RunPresenter::relative($job->last_run_at),
                'last_run_at' => RunPresenter::iso($job->last_run_at),
                'last_status' => $metrics['last_status'] ?? 'ok',

                'next' => $job->enabled ? $this->formatNext($nextInSeconds) : '—',
                'next_run_at' => $job->enabled ? $nextAt : null,
                'avg_dur' => $this->formatDuration($metrics['avg_dur_s']),
                'chain_to_id' => $job->chain_to_job_id,
                'chain_to_name' => $chain !== null ? $this->jobName($chain) : null,
            ];
        }

        return ['jobs' => $jobs];
    }

    private function jobName(CronJob $job): string
    {
        return sprintf('%s.%s.%s', $job->shop->name, $job->phase, $job->strategy ?? 'default');
    }

    private function runPhase(string $phase, ?string $strategy): string
    {
        if ($phase === 'scan') {
            return 'scan';
        }
        if ($strategy !== null && in_array($strategy, self::DISCOVER_STRATEGIES, true)) {
            return "discover_{$strategy}";
        }

        return $phase === '' ? 'scan' : $phase;
    }

    /**
     * @param  iterable<CronJob>  $jobs
     * @return array<string, array{last_status: string|null, avg_dur_s: float|null}>
     */
    private function metricsForJobs(iterable $jobs): array
    {
        $shopIds = [];
        $phases = [];
        $wanted = [];
        $metrics = [];
        foreach ($jobs as $job) {
            $phase = $this->runPhase($job->phase, $job->strategy);
            $key = $this->metricKey($job->shop_id, $phase);
            $wanted[$key] = true;
            $metrics[$key] = ['last_status' => null, 'avg_dur_s' => null];
            $shopIds[$job->shop_id] = $job->shop_id;
            $phases[$phase] = $phase;
        }
        if ($wanted === []) {
            return [];
        }

        $ranked = DB::table('scrape_runs')
            ->select('shop_id', 'phase', 'status', 'started_at', 'finished_at')
            ->selectRaw('row_number() over (
                partition by shop_id, phase order by finished_at desc nulls last, id desc
            ) as terminal_rank')
            ->selectRaw('row_number() over (
                partition by shop_id, phase, status order by finished_at desc nulls last, id desc
            ) as status_rank')
            ->whereIn('shop_id', array_values($shopIds))
            ->whereIn('phase', array_values($phases))
            ->whereIn('status', ['completed', 'failed']);

        $durations = [];
        foreach (DB::query()->fromSub($ranked, 'runs')->get() as $raw) {
            $run = DatabaseRow::from($raw);
            $key = $this->metricKey($run->int('shop_id'), $run->string('phase'));
            if (! isset($wanted[$key])) {
                continue;
            }
            if ($run->int('terminal_rank') === 1) {
                $metrics[$key] = [
                    'last_status' => $run->string('status') === 'completed' ? 'ok' : 'fail',
                    'avg_dur_s' => $metrics[$key]['avg_dur_s'],
                ];
            }
            if ($run->string('status') === 'completed'
                && $run->int('status_rank') <= self::AVG_WINDOW
                && $run->nullableString('finished_at') !== null
                && $run->nullableString('started_at') !== null) {
                $durations[$key][] = $run->dateTime('started_at')
                    ->diffInSeconds($run->dateTime('finished_at'), true);
            }
        }

        foreach ($durations as $durationKey => $values) {
            $metrics[$durationKey] = [
                'last_status' => $metrics[$durationKey]['last_status'],
                'avg_dur_s' => array_sum($values) / count($values),
            ];
        }

        return $metrics;
    }

    private function metricKey(int $shopId, string $phase): string
    {
        return "{$shopId}:{$phase}";
    }

    /** @return array{string|null, int|null} */
    private function nextFiring(string $expression, Carbon $now): array
    {
        try {
            $next = Date::instance((new CronExpression($expression))->getNextRunDate($now))->utc();
        } catch (Throwable) {

            return [null, null];
        }

        return [RunPresenter::iso($next), (int) $now->diffInSeconds($next, true)];
    }

    private function formatNext(?int $seconds): string
    {
        if ($seconds === null) {
            return '—';
        }
        if ($seconds < 60) {
            return 'in < 1m';
        }
        $minutes = intdiv($seconds, 60);
        if ($minutes < 60) {
            return "in {$minutes}m";
        }
        $hours = intdiv($minutes, 60);
        $minutes %= 60;

        return $minutes > 0 ? "in {$hours}h {$minutes}m" : "in {$hours}h";
    }

    private function formatDuration(?float $seconds): string
    {
        if ($seconds === null) {
            return '—';
        }
        $total = (int) $seconds;
        $s = $total % 60;
        $m = intdiv($total, 60) % 60;
        $h = intdiv($total, 3600);

        if ($h > 0) {
            return $m > 0 ? "{$h}h {$m}m" : "{$h}h";
        }
        if ($m > 0) {
            return $s > 0 ? "{$m}m {$s}s" : "{$m}m";
        }

        return "{$s}s";
    }

    private const string DISPLAY_TZ = 'Europe/Vilnius';

    private const int UPCOMING_COUNT = 5;

    private const int HEATMAP_RUNS = 24;

    /** @return array<string, mixed> */
    public function show(CronJob $job): array
    {
        $job->load('shop');

        $runPhase = $this->runPhase($job->phase, $job->strategy);
        $now = Date::now('UTC');

        $terminal = fn (): Builder => DB::table('scrape_runs')
            ->where('shop_id', $job->shop_id)
            ->where('phase', $runPhase)
            ->whereIn('status', ['completed', 'failed']);

        $last24Rows = $terminal()
            ->orderByRaw('finished_at desc nulls last')
            ->limit(self::HEATMAP_RUNS)
            ->get()
            ->all();
        $last24 = [];
        foreach (array_reverse($last24Rows) as $raw) {
            $last24[] = DatabaseRow::from($raw)->string('status') === 'completed' ? 'ok' : 'fail';
        }

        $runs24h = $terminal()->where('finished_at', '>=', $now->copy()->subHours(24))->get()->all();
        $runs30d = $terminal()->where('finished_at', '>=', $now->copy()->subDays(30))->get()->all();

        $ok30d = 0;
        $ok24h = 0;
        $failed24h = 0;
        foreach ($runs24h as $raw) {
            $status = DatabaseRow::from($raw)->string('status');
            $ok24h += $status === 'completed' ? 1 : 0;
            $failed24h += $status === 'failed' ? 1 : 0;
        }
        $durations = [];
        foreach ($runs30d as $raw) {
            $run = DatabaseRow::from($raw);
            if ($run->string('status') !== 'completed') {
                continue;
            }
            $ok30d++;
            if ($run->nullableString('finished_at') !== null && $run->nullableString('started_at') !== null) {
                $durations[] = $run->dateTime('started_at')->diffInSeconds($run->dateTime('finished_at'), true);
            }
        }

        $lastRun = DatabaseRow::nullable(
            $terminal()->orderByRaw('finished_at desc nulls last')->first(),
        );

        $recentRows = DB::table('scrape_runs')
            ->where('shop_id', $job->shop_id)
            ->where('phase', $runPhase)
            ->latest('started_at')
            ->limit(20)
            ->get();
        $recentRuns = [];
        foreach ($recentRows as $raw) {
            $run = DatabaseRow::from($raw);
            $startedAt = $run->nullableString('started_at');
            $finishedAt = $run->nullableString('finished_at');
            $duration = $startedAt !== null && $finishedAt !== null
                ? round($run->dateTime('started_at')->diffInSeconds($run->dateTime('finished_at'), true), 6)
                : null;
            $recentRuns[] = [
                'id' => $run->int('id'),
                'started' => RunPresenter::relative($startedAt === null ? null : Date::parse($startedAt)),
                'started_at' => RunPresenter::iso($startedAt === null ? null : Date::parse($startedAt)),
                'dur' => $this->formatDuration($duration),
                'dur_s' => $duration,
                'items' => $run->int('items_added') + $run->int('items_updated'),
                'errors' => $run->int('error_count'),
                'status' => $run->string('status'),
            ];
        }

        $avgDuration = $durations === [] ? null : array_sum($durations) / count($durations);

        return [
            'id' => $job->id,
            'name' => $this->jobName($job),
            'shop' => $job->shop->name,
            'phase' => $job->phase,
            'strategy' => $job->strategy ?? '',
            'cron' => $job->cron_expression,
            'enabled' => $job->enabled,
            'last_run_at' => RunPresenter::iso($job->last_run_at),
            'chain_to_id' => $job->chain_to_job_id,
            'upcoming' => $job->enabled ? $this->upcoming($job->cron_expression, $now) : [],
            'last24' => $last24,
            'stats' => [
                'total_24h' => count($runs24h),
                'ok_24h' => $ok24h,
                'fail_24h' => $failed24h,
                'success_rate_30d' => count($runs30d) > 0
                    ? round($ok30d / count($runs30d) * 100, 1)
                    : null,
                'avg_dur' => $this->formatDuration($avgDuration),
                'avg_dur_s' => $avgDuration,
                'last_status' => $lastRun instanceof DatabaseRow
                    ? $lastRun->string('status') === 'completed' ? 'ok' : 'fail'
                    : (null),
                'last_run_ago' => $lastRun instanceof DatabaseRow
                    ? RunPresenter::relative(
                        $lastRun->nullableString('finished_at') === null
                            ? null
                            : Date::parse($lastRun->string('finished_at')),
                    )
                    : '—',
            ],
            'runs' => $recentRuns,
        ];
    }

    /** @return list<array{when: string, at: string, date: string}> */
    private function upcoming(string $expression, Carbon $now): array
    {
        try {
            $cron = new CronExpression($expression);
        } catch (Throwable) {
            return [];
        }

        $today = $now->copy()->setTimezone(self::DISPLAY_TZ)->toDateString();
        $upcoming = [];
        $cursor = $now->copy();

        for ($i = 0; $i < self::UPCOMING_COUNT; $i++) {
            try {
                $next = Date::instance($cron->getNextRunDate($cursor))->utc();
            } catch (Throwable) {
                break;
            }
            $cursor = $next->copy()->addSecond();

            $local = $next->copy()->setTimezone(self::DISPLAY_TZ);
            $date = $local->toDateString();

            $daysAway = (int) Date::parse($today)->diffInDays(Date::parse($date), false);

            $upcoming[] = [
                'when' => $this->formatNext((int) $now->diffInSeconds($next, true)),
                'at' => $local->format('H:i'),
                'date' => match (true) {
                    $date === $today => 'today',
                    $daysAway === 1 => 'tomorrow',

                    default => $local->format('j M'),
                },
            ];
        }

        return $upcoming;
    }
}
