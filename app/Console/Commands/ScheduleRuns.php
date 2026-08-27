<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Support\CrawlSpawner;
use App\Support\CronSchedule;
use App\Models\CronJob;
use App\Models\ScrapeRun;
use DateTimeImmutable;
use DateTimeZone;
use Illuminate\Console\Command;
use Throwable;

/**
 * Fires the schedules in `cron_jobs`.
 *
 * Nothing else does. The dashboard's Schedules page writes these rows and
 * validates their expressions, and until the Python stack was removed a
 * crontab was rendered from them at container boot
 * (scripts/generate_crontab.py). With no container, this command is what turns
 * a row into a crawl — run it under a supervisor or as `--watch`.
 *
 * Deliberately not Laravel's scheduler: that still needs a system cron entry
 * to call `schedule:run` every minute, which is the same dependency with more
 * indirection. This owns its own loop, beside `runs:reap`.
 *
 * What it does NOT do, because something else already does:
 *
 *  - **Stamp `last_run_at`.** RunLifecycle does it when the run starts. One
 *    writer is worth more than a tidy-looking scheduler.
 *  - **Chain jobs.** PostPhase spawns `chain_to_job_id` when a run closes.
 *    Chained jobs still have their own expressions and are fired here too, on
 *    those expressions — exactly as the crontab did, which gave every enabled
 *    job a line regardless of chaining.
 *  - **Refuse concurrent runs of the same shop+phase.** The crawler's own
 *    preflight does that, and a spawn that hits it exits immediately.
 *
 * It does apply a stricter rule of its own: **one scheduled crawl per shop at
 * a time**, any phase. A drained backlog would otherwise start patogupirkti's
 * sitemap discover, its category discover and its scan together — three
 * concurrent crawls against one live shop, tripling the request rate the
 * per-shop delay is there to cap. The crontab never did this because its
 * windows were half an hour apart; a catch-up pass has no such spacing.
 *
 * `paused` deliberately does NOT count as in-flight, even though the crawler's
 * own preflight counts it. A paused run is parked by an operator and the reaper
 * leaves it alone by design (a paused run is alive, so its heartbeat going
 * quiet is expected) — so it can sit there indefinitely. There is one on
 * patogupirkti from May. Treating that as "busy" would silently stop every
 * schedule for that shop, forever, which is the failure this command exists to
 * prevent.
 */
final class ScheduleRuns extends Command
{
    protected $signature = 'runs:schedule
        {--watch : keep checking instead of exiting after one pass}
        {--interval=30 : seconds between checks in --watch mode}
        {--max-per-tick=2 : most jobs to fire in one pass}
        {--dry-run : report what would fire, spawn nothing}';

    protected $description = 'Fire the schedules in cron_jobs';

    /** @var array<int, int> job id => due timestamp already fired */
    private array $firedAt = [];

    public function handle(): int
    {
        $interval = max(5, (int) $this->option('interval'));
        $maxPerTick = max(1, (int) $this->option('max-per-tick'));
        $dryRun = (bool) $this->option('dry-run');

        if ($dryRun) {
            $this->comment('dry run — nothing will be spawned');
        }

        do {
            try {
                $this->tick($maxPerTick, $dryRun);
            } catch (Throwable $e) {
                // A tick must never kill the loop: the database going away for
                // a moment should not stop every future schedule.
                $this->error('scheduler tick failed: ' . $e->getMessage());
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
            CronJob::with('shop')->where('enabled', true)->orderBy('id')->get(),
            $now,
            $this->firedAt
        );

        if ($due === []) {
            return;
        }

        $fired = 0;
        foreach ($due as $item) {
            /** @var CronJob $job */
            $job = $item['job'];
            $shop = $job->shop->name ?? null;
            if ($shop === null) {
                $this->error("cron job #{$job->id} has no shop — skipping");
                continue;
            }

            if ($item['unknownArgs'] !== []) {
                // Reported, not dropped: the run about to be spawned does
                // something different from what the row asks for.
                $this->warn(sprintf(
                    'cron job #%d: unrecognised args %s — spawning without them',
                    $job->id,
                    implode(' ', $item['unknownArgs'])
                ));
            }

            if ($fired >= $maxPerTick) {
                // Left due on purpose: it fires on a later tick. Twelve
                // schedules whose windows all passed while this was down would
                // otherwise start twelve crawls at once.
                $this->line(sprintf(
                    '  deferring cron job #%d (%s %s) — %d already fired this tick',
                    $job->id,
                    $shop,
                    $job->runPhase(),
                    $fired
                ));
                continue;
            }

            $active = $this->activePhase($job);
            if ($active !== null) {
                $this->line(sprintf(
                    '  skipping cron job #%d (%s %s) — %s is already running for this shop',
                    $job->id,
                    $shop,
                    $job->runPhase(),
                    $active
                ));
                continue;
            }

            $this->info(sprintf(
                'cron job #%d due %s — %s %s%s',
                $job->id,
                $item['due']->format('Y-m-d H:i:s\Z'),
                $shop,
                $job->runPhase(),
                $item['mode'] === 'full' ? ' (full rescan)' : ''
            ));

            if ($dryRun) {
                $fired++;
                continue;
            }

            try {
                $result = CrawlSpawner::spawn(
                    phase: $job->phase,
                    shop: $shop,
                    strategy: (string) ($job->strategy ?? ''),
                    mode: $item['mode'],
                    cronJobId: $job->id,
                    role: 'cron',
                );
            } catch (Throwable $e) {
                $this->error("  spawn failed for cron job #{$job->id}: " . $e->getMessage());
                continue;
            }

            // Recorded only once the spawn succeeded, so a failure is retried
            // on the next tick rather than being marked done.
            $this->firedAt[$job->id] = $item['due']->getTimestamp();
            $fired++;
            $this->line("  pid={$result['pid']} log={$result['log']}");
        }
    }

    /**
     * The phase of an in-flight run for this job's SHOP, or null if idle.
     *
     * Any phase, not just this job's: see the note above about a backlog
     * starting three crawls against one shop at once. Excludes `paused`,
     * which can sit indefinitely.
     */
    private function activePhase(CronJob $job): ?string
    {
        // running and stopping only — see the note above on `paused`.
        $run = ScrapeRun::where('shop_id', $job->shop_id)
            ->whereIn('status', ['running', 'stopping'])
            ->orderBy('id')
            ->first();

        return $run === null ? null : (string) $run->phase;
    }
}
