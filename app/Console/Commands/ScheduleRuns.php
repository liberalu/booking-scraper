<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Models\CronJob;
use App\Repositories\Contracts\SchedulerRepositoryInterface;
use App\Support\CrawlSpawner;
use App\Support\CronSchedule;
use DateTimeImmutable;
use DateTimeZone;
use Illuminate\Console\Command;
use Throwable;

final class ScheduleRuns extends Command
{
    protected $signature = 'runs:schedule
        {--watch : keep checking instead of exiting after one pass}
        {--interval=30 : seconds between checks in --watch mode}
        {--max-per-tick=2 : most jobs to fire in one pass}
        {--dry-run : report what would fire, spawn nothing}';

    protected $description = 'Fire the schedules in cron_jobs';

    /** @var array<int, int> */
    private array $firedAt = [];

    public function __construct(private readonly SchedulerRepositoryInterface $schedules)
    {
        parent::__construct();
    }

    public function handle(): int
    {
        $interval = max(5, (int) $this->option('interval'));
        $maxPerTick = max(1, (int) $this->option('max-per-tick'));
        $dryRun = $this->option('dry-run');

        if ($dryRun) {
            $this->comment('dry run — nothing will be spawned');
        }

        do {
            try {
                $this->tick($maxPerTick, $dryRun);
            } catch (Throwable $e) {

                $this->error('scheduler tick failed: '.$e->getMessage());
                if (! $this->option('watch')) {
                    return self::FAILURE;
                }
            }
            if ($this->option('watch')) {
                sleep($interval);
            }
        } while ($this->option('watch'));

        return self::SUCCESS;
    }

    private function tick(int $maxPerTick, bool $dryRun): void
    {
        $now = new DateTimeImmutable('now', new DateTimeZone('UTC'));
        $due = CronSchedule::due(
            $this->schedules->enabledJobs(),
            $now,
            $this->firedAt
        );

        if ($due === []) {
            return;
        }

        $fired = 0;
        foreach ($due as $item) {
            $job = $item['job'];
            $dueAt = $item['due'];
            $mode = $item['mode'];
            $unknownArgs = $item['unknownArgs'];
            $shop = $job->shop->name;

            if ($unknownArgs !== []) {

                $this->warn(sprintf(
                    'cron job #%d: unrecognised args %s — spawning without them',
                    $job->id,
                    implode(' ', $unknownArgs)
                ));
            }

            if ($fired >= $maxPerTick) {

                $this->line(sprintf(
                    '  deferring cron job #%d (%s %s) — %d already fired this tick',
                    $job->id,
                    $shop,
                    $job->runPhase(),
                    $fired
                ));

                continue;
            }

            if (! $this->schedules->tryAcquireShop($job->shop_id)) {
                $this->line(sprintf(
                    '  skipping cron job #%d (%s %s) — another scheduler owns this shop',
                    $job->id,
                    $shop,
                    $job->runPhase(),
                ));

                continue;
            }

            try {
                $active = $this->activePhase($job);
                if ($active !== null) {
                    $this->line(sprintf(
                        '  skipping cron job #%d (%s %s) — %s is already running for this shop',
                        $job->id,
                        $shop,
                        $job->runPhase(),
                        $active,
                    ));

                    continue;
                }

                $this->info(sprintf(
                    'cron job #%d due %s — %s %s%s',
                    $job->id,
                    $dueAt->format('Y-m-d H:i:s\Z'),
                    $shop,
                    $job->runPhase(),
                    $mode === 'full' ? ' (full rescan)' : '',
                ));

                if ($dryRun) {
                    $fired++;

                    continue;
                }

                try {
                    $result = CrawlSpawner::spawn(
                        phase: $job->phase,
                        shop: $shop,
                        strategy: $job->strategy ?? '',
                        mode: $mode,
                        cronJobId: $job->id,
                        role: 'cron',
                    );
                } catch (Throwable $e) {
                    $this->error("  spawn failed for cron job #{$job->id}: ".$e->getMessage());

                    continue;
                }

                $this->firedAt[$job->id] = $dueAt->getTimestamp();
                $fired++;
                $pid = $result['pid'];
                $pidLabel = $pid === null ? 'unknown' : (string) $pid;
                $this->line("  pid={$pidLabel} log={$result['log']}");
                if ($pid !== null) {
                    $this->awaitRunRegistration($job, $pid);
                }
            } finally {
                $this->schedules->releaseShop($job->shop_id);
            }
        }
    }

    private function activePhase(CronJob $job): ?string
    {

        return $this->schedules->activePhase($job);
    }

    private function awaitRunRegistration(CronJob $job, int $pid): void
    {
        $deadline = microtime(true) + 3.0;
        while (microtime(true) < $deadline) {
            if ($this->activePhase($job) !== null) {
                return;
            }
            if (function_exists('posix_kill') && ! posix_kill($pid, 0)) {
                return;
            }
            usleep(50_000);
        }

        $this->warn("  crawl pid={$pid} did not register a run before the scheduler lock expired");
    }
}
