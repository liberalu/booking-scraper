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
 * GET /api/cron — the schedule table.
 */
final class CronController
{
    /** Strategies that become part of the scrape_runs.phase value. */
    private const DISCOVER_STRATEGIES = [
        'sitemap', 'categories', 'full_crawl', 'graphql', 'lupasearch',
    ];

    /** How many completed runs the average duration is taken over. */
    private const AVG_WINDOW = 30;

    public function index(): array
    {
        $now = Carbon::now('UTC');

        $jobs = [];
        foreach (CronJob::with('shop')->orderBy('id')->get() as $job) {
            $runPhase = self::runPhase($job->phase, $job->strategy);
            [$nextAt, $nextInSeconds] = self::nextFiring($job->cron_expression, $now);
            $metrics = self::metrics($job->shop_id, $runPhase);

            $chain = $job->chain_to_job_id !== null
                ? CronJob::with('shop')->find($job->chain_to_job_id)
                : null;

            $jobs[] = [
                'id' => $job->id,
                'name' => self::jobName($job),
                'shop' => $job->shop->name,
                'phase' => $job->phase,
                'strategy' => $job->strategy ?: '',
                'args' => $job->args ?: '',
                'cron' => $job->cron_expression,
                'enabled' => $job->enabled,
                'last' => RunPresenter::relative($job->last_run_at),
                'last_run_at' => RunPresenter::iso($job->last_run_at),
                'last_status' => $metrics['last_status'] ?? 'ok',
                // A disabled job has no next firing to show.
                'next' => $job->enabled ? self::formatNext($nextInSeconds) : '—',
                'next_run_at' => $job->enabled ? $nextAt : null,
                'avg_dur' => self::formatDuration($metrics['avg_dur_s']),
                'chain_to_id' => $job->chain_to_job_id,
                'chain_to_name' => $chain !== null ? self::jobName($chain) : null,
            ];
        }

        return ['jobs' => $jobs];
    }

    private static function jobName(CronJob $job): string
    {
        return sprintf('%s.%s.%s', $job->shop->name, $job->phase, $job->strategy ?: 'default');
    }

    /**
     * The scrape_runs.phase this job produces.
     *
     * discover jobs fold the strategy into the phase; for scan the strategy
     * is UI-only metadata (delta/full) and the phase stays plain 'scan'.
     */
    private static function runPhase(string $phase, ?string $strategy): string
    {
        if ($phase === 'scan') {
            return 'scan';
        }
        if ($strategy !== null && in_array($strategy, self::DISCOVER_STRATEGIES, true)) {
            return "discover_{$strategy}";
        }

        return $phase ?: 'scan';
    }

    /** @return array{last_status: string|null, avg_dur_s: float|null} */
    private static function metrics(int $shopId, string $runPhase): array
    {
        $lastRun = ScrapeRun::where('shop_id', $shopId)
            ->where('phase', $runPhase)
            ->whereIn('status', ['completed', 'failed'])
            ->orderByRaw('finished_at desc nulls last')
            ->first();

        $recent = ScrapeRun::where('shop_id', $shopId)
            ->where('phase', $runPhase)
            ->where('status', 'completed')
            ->whereNotNull('finished_at')
            ->orderByRaw('finished_at desc nulls last')
            ->limit(self::AVG_WINDOW)
            ->get();

        $durations = [];
        foreach ($recent as $run) {
            if ($run->finished_at !== null && $run->started_at !== null) {
                $durations[] = $run->started_at->diffInRealSeconds($run->finished_at, true);
            }
        }

        return [
            'last_status' => $lastRun === null
                ? null
                : ($lastRun->status === 'completed' ? 'ok' : 'fail'),
            'avg_dur_s' => $durations === [] ? null : array_sum($durations) / count($durations),
        ];
    }

    /** @return array{0: string|null, 1: int|null} */
    private static function nextFiring(string $expression, Carbon $now): array
    {
        try {
            $next = Carbon::instance((new CronExpression($expression))->getNextRunDate($now))->utc();
        } catch (Throwable) {
            // A typo in one job must not blank the whole table.
            return [null, null];
        }

        return [RunPresenter::iso($next), (int) $now->diffInRealSeconds($next, true)];
    }

    private static function formatNext(?int $seconds): string
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

    private static function formatDuration(?float $seconds): string
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

    // --------------------------------------------------------------- detail

    /** Fire times are shown in the operator's timezone, not UTC. */
    private const DISPLAY_TZ = 'Europe/Vilnius';

    private const UPCOMING_COUNT = 5;

    /** How many terminal runs the heatmap strip shows. */
    private const HEATMAP_RUNS = 24;

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function show(int $jobId): mixed
    {
        $job = CronJob::with('shop')->find($jobId);
        if ($job === null) {
            return response()->json(['detail' => 'Job not found'], 404);
        }

        $runPhase = self::runPhase($job->phase, $job->strategy);
        $now = Carbon::now('UTC');

        $terminal = fn () => ScrapeRun::where('shop_id', $job->shop_id)
            ->where('phase', $runPhase)
            ->whereIn('status', ['completed', 'failed']);

        // Oldest-first so the strip reads left to right chronologically.
        $last24 = $terminal()
            ->orderByRaw('finished_at desc nulls last')
            ->limit(self::HEATMAP_RUNS)
            ->get()
            ->reverse()
            ->map(fn ($r): string => $r->status === 'completed' ? 'ok' : 'fail')
            ->values()
            ->all();

        $runs24h = $terminal()->where('finished_at', '>=', $now->copy()->subHours(24))->get();
        $runs30d = $terminal()->where('finished_at', '>=', $now->copy()->subDays(30))->get();

        $ok30d = $runs30d->where('status', 'completed')->count();
        $durations = $runs30d
            ->filter(fn ($r): bool => $r->status === 'completed'
                && $r->finished_at !== null && $r->started_at !== null)
            ->map(fn ($r): float => (float) $r->started_at->diffInRealSeconds($r->finished_at, true))
            ->all();

        $lastRun = $terminal()->orderByRaw('finished_at desc nulls last')->first();

        $recentRuns = ScrapeRun::where('shop_id', $job->shop_id)
            ->where('phase', $runPhase)
            ->orderByDesc('started_at')
            ->limit(20)
            ->get()
            ->map(function ($run): array {
                $duration = ($run->finished_at !== null && $run->started_at !== null)
                    ? round((float) $run->started_at->diffInRealSeconds($run->finished_at, true), 6)
                    : null;

                return [
                    'id' => $run->id,
                    'started' => RunPresenter::relative($run->started_at),
                    'started_at' => RunPresenter::iso($run->started_at),
                    'dur' => self::formatDuration($duration),
                    'dur_s' => $duration,
                    'items' => $run->items_added + $run->items_updated,
                    'errors' => $run->error_count,
                    'status' => $run->status,
                ];
            })->all();

        $avgDuration = $durations === [] ? null : array_sum($durations) / count($durations);

        return [
            'id' => $job->id,
            'name' => self::jobName($job),
            'shop' => $job->shop->name,
            'phase' => $job->phase,
            'strategy' => $job->strategy ?: '',
            'cron' => $job->cron_expression,
            'enabled' => $job->enabled,
            'last_run_at' => RunPresenter::iso($job->last_run_at),
            'chain_to_id' => $job->chain_to_job_id,
            'upcoming' => $job->enabled ? self::upcoming($job->cron_expression, $now) : [],
            'last24' => $last24,
            'stats' => [
                'total_24h' => $runs24h->count(),
                'ok_24h' => $runs24h->where('status', 'completed')->count(),
                'fail_24h' => $runs24h->where('status', 'failed')->count(),
                'success_rate_30d' => $runs30d->count() > 0
                    ? round($ok30d / $runs30d->count() * 100, 1)
                    : null,
                'avg_dur' => self::formatDuration($avgDuration),
                'avg_dur_s' => $avgDuration,
                'last_status' => $lastRun === null
                    ? null
                    : ($lastRun->status === 'completed' ? 'ok' : 'fail'),
                'last_run_ago' => $lastRun !== null
                    ? RunPresenter::relative($lastRun->finished_at)
                    : '—',
            ],
            'runs' => $recentRuns,
        ];
    }

    /**
     * The next few fire times, labelled relative to the operator's day.
     *
     * @return list<array{when: string, at: string, date: string}>
     */
    private static function upcoming(string $expression, Carbon $now): array
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
                $next = Carbon::instance($cron->getNextRunDate($cursor))->utc();
            } catch (Throwable) {
                break;
            }
            $cursor = $next->copy()->addSecond();

            $local = $next->copy()->setTimezone(self::DISPLAY_TZ);
            $date = $local->toDateString();
            // Cast: diffInDays returns a float, so a strict === 1 never matches.
            $daysAway = (int) Carbon::parse($today)->diffInDays(Carbon::parse($date), false);

            $upcoming[] = [
                'when' => self::formatNext((int) $now->diffInRealSeconds($next, true)),
                'at' => $local->format('H:i'),
                'date' => match (true) {
                    $date === $today => 'today',
                    $daysAway === 1 => 'tomorrow',
                    // Python uses %-d (no zero padding).
                    default => $local->format('j M'),
                },
            ];
        }

        return $upcoming;
    }
}
