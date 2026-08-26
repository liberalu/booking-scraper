<?php

declare(strict_types=1);

namespace BookScraper\Crawler;

use BookScraper\Database;
use BookScraper\Models\CronJob;
use BookScraper\Runs\RunEvent;
use BookScraper\Runs\RunFailsafe;
use BookScraper\Services\MatchService;
use Illuminate\Support\Facades\DB;
use Throwable;

/**
 * What happens after a scan or discover run closes.
 *
 * Two independent things, in priority order:
 *
 *  1. If this run was fired by a cron job that chains to another, spawn the
 *     chained job.
 *  2. Otherwise, link new books by ISBN (match step 1 — one UPDATE) and fire
 *     a validate run, so data-quality state never lags a scrape. Skipped when
 *     the cron chain already targets match or validate: firing both would
 *     double-run the validator.
 *
 * Every failure in here is swallowed and reported. A crawl that wrote its
 * rows successfully must not be marked failed because a follow-up could not
 * be spawned.
 */
final class PostPhase
{
    private const SPAWN_CONTEXT = 'post-phase-auto';

    /** Runs after a SUCCESSFUL scan or discover. */
    public static function after(
        string $phase,
        string $shopName,
        int $runId,
        ?int $cronJobId,
    ): void {
        $chainJob = $cronJobId === null ? null : self::chainTarget($cronJobId);

        if ($chainJob !== null) {
            self::spawnCronChain($chainJob, $shopName);
            if (in_array($chainJob->phase, ['match', 'validate'], true)) {
                // The chain covers it — running our own validate too would
                // produce two validate runs for one scrape.
                return;
            }
        }

        if (!self::autoTriggerEnabled()) {
            fwrite(STDOUT, "post-phase: disabled via env, skipping\n");

            return;
        }

        try {
            $linked = (new MatchService())->isbnMatch($shopName);
            printf("post-phase: ISBN-match linked %d shop_book(s)\n", $linked);
        } catch (Throwable $e) {
            fwrite(STDERR, "post-phase: ISBN-match failed: {$e->getMessage()}\n");
        }

        self::spawnValidate($shopName);
    }

    /**
     * Runs after a FAILED scan or discover.
     *
     * The skipped chain is recorded rather than passed over silently, so a
     * gap in a cron chain is visible on the run's timeline instead of having
     * to be inferred from the absence of a run.
     */
    public static function chainSkipped(int $runId, ?int $cronJobId, string $reason): void
    {
        if ($cronJobId === null) {
            return;
        }
        try {
            RunFailsafe::recordEvent($runId, RunEvent::CHAIN_SKIPPED, [
                'parent_reason' => $reason,
                'cron_job_id' => $cronJobId,
            ]);
        } catch (Throwable $e) {
            fwrite(STDERR, "post-phase: could not record chain_skipped: {$e->getMessage()}\n");
        }
    }

    /** The job this one chains to, or null. */
    private static function chainTarget(int $cronJobId): ?CronJob
    {
        try {
            $job = CronJob::find($cronJobId);
            if ($job === null || $job->chain_to_job_id === null) {
                return null;
            }

            return CronJob::with('shop')->find((int) $job->chain_to_job_id);
        } catch (Throwable $e) {
            fwrite(STDERR, "post-phase: chain lookup failed: {$e->getMessage()}\n");

            return null;
        }
    }

    private static function spawnCronChain(CronJob $job, string $parentShop): void
    {
        $shop = $job->shop->name ?? $parentShop;
        $cmd = self::crawlerCommand($job->phase, $shop);
        if ($cmd === null) {
            return;
        }
        if ($job->phase === 'discover' && $job->strategy) {
            $cmd[] = "--strategy={$job->strategy}";
        }
        $cmd[] = "--cron-job-id={$job->id}";
        if (($job->args ?? '') !== '') {
            foreach (preg_split('/\s+/', trim((string) $job->args), -1, PREG_SPLIT_NO_EMPTY) ?: [] as $arg) {
                $cmd[] = $arg;
            }
        }
        $cmd[] = '--database=' . self::databaseUrl();

        $log = self::detach($cmd, 'cron-chain', $shop);
        printf("post-phase: spawned chain job %d (%s) log=%s\n", $job->id, $job->phase, $log);
    }

    private static function spawnValidate(string $shopName): void
    {
        $binary = self::phpBinary();
        $script = dirname(__DIR__) . '/bin/validate';
        if ($binary === null || !is_file($script)) {
            fwrite(STDERR, "post-phase: validate binary not found, skipping\n");

            return;
        }
        $cmd = [$binary, $script, "--shop={$shopName}", '--database=' . self::databaseUrl()];
        $log = self::detach($cmd, self::SPAWN_CONTEXT, $shopName);
        printf("post-phase: spawned validate for %s log=%s\n", $shopName, $log);
    }

    /** `crawl <phase>` for the phases this binary implements, else null. */
    private static function crawlerCommand(string $phase, string $shop): ?array
    {
        $binary = self::phpBinary();
        if ($binary === null) {
            return null;
        }
        if (in_array($phase, ['scan', 'discover'], true)) {
            return [$binary, dirname(__DIR__) . '/bin/crawl', $phase, "--shop={$shop}"];
        }
        if ($phase === 'validate') {
            return [$binary, dirname(__DIR__) . '/bin/validate', "--shop={$shop}"];
        }
        if ($phase === 'match') {
            // The full phase, not just step 1. Synthesis stays off unless
            // MATCH_SYNTHESIS_ENABLED says otherwise — bin/match reads it.
            return [$binary, dirname(__DIR__) . '/bin/match', "--shop={$shop}"];
        }
        fwrite(STDERR, "post-phase: no crawler command for phase '{$phase}'\n");

        return null;
    }

    /** Detached so the follow-up outlives this process. Returns the log path. */
    private static function detach(array $cmd, string $role, string $shop): string
    {
        $log = self::logPath($role, $shop);
        $script = sprintf(
            'mkdir -p %s && nohup %s >> %s 2>&1 &',
            escapeshellarg(dirname($log)),
            implode(' ', array_map('escapeshellarg', $cmd)),
            escapeshellarg($log)
        );
        $process = @proc_open(['/bin/sh', '-c', $script], [], $pipes);
        if (is_resource($process)) {
            proc_close($process);
        } else {
            fwrite(STDERR, "post-phase: spawn failed for {$role}\n");
        }

        return $log;
    }

    /**
     * Where a spawned follow-up writes its output.
     *
     * The default is a container path. Running from the CLI on a host, `mkdir
     * -p` on it fails and the whole spawn dies with it — which silently took
     * the post-phase validate with it the first time a crawl ran outside a
     * container. So an unwritable directory falls back to the system temp dir
     * rather than costing the run its follow-up: the log is a convenience, the
     * validate is not.
     */
    private static function logPath(string $role, string $shop): string
    {
        $dir = getenv('SPAWN_LOG_DIR') ?: '/var/log/scrapy_runs';
        if (! self::isUsableDir($dir)) {
            $fallback = sys_get_temp_dir() . '/book-scraper-spawn';
            fwrite(STDERR, "post-phase: {$dir} is not writable, logging to {$fallback}\n");
            $dir = $fallback;
        }
        $stamp = (new \DateTimeImmutable('now', new \DateTimeZone('UTC')))->format('Ymd-Hisu');
        $slug = static fn (string $v): string
            => trim(preg_replace('/[^A-Za-z0-9._-]+/', '-', $v) ?? $v, '-') ?: 'unknown';

        return sprintf('%s/spawn-%s-%s-%s.log', rtrim($dir, '/'), $stamp, $slug($role), $slug($shop));
    }

    /** Exists and is writable, or can be created. */
    private static function isUsableDir(string $dir): bool
    {
        if (is_dir($dir)) {
            return is_writable($dir);
        }

        // Walk up to the nearest existing ancestor: mkdir -p can only create
        // the missing part if that part is writable.
        $parent = \dirname($dir);
        while ($parent !== '/' && $parent !== '.' && ! is_dir($parent)) {
            $parent = \dirname($parent);
        }

        return is_writable($parent);
    }

    private static function phpBinary(): ?string
    {
        foreach ([getenv('CRAWLER_PHP_BINARY'), PHP_BINARY] as $candidate) {
            if (is_string($candidate) && $candidate !== '' && is_executable($candidate)) {
                return $candidate;
            }
        }

        return null;
    }

    /**
     * The database this process is using — passed explicitly so a follow-up
     * cannot end up on a different one than the crawl it follows.
     */
    private static function databaseUrl(): string
    {
        $dsn = Database::bootedDsn();
        if ($dsn !== null) {
            return $dsn;
        }
        $c = DB::connection()->getConfig();

        return sprintf(
            'postgresql://%s:%s@%s:%s/%s',
            rawurlencode((string) ($c['username'] ?? '')),
            rawurlencode((string) ($c['password'] ?? '')),
            $c['host'] ?? '127.0.0.1',
            $c['port'] ?? 5432,
            $c['database'] ?? ''
        );
    }

    private static function autoTriggerEnabled(): bool
    {
        // Legacy alias kept so an existing deploy's env keeps working.
        $raw = getenv('POST_PHASE_AUTO_TRIGGER');
        if (!is_string($raw) || $raw === '') {
            $raw = getenv('POST_SCAN_AUTO_TRIGGER');
        }
        if (!is_string($raw) || $raw === '') {
            return true;
        }

        return in_array(strtolower($raw), ['1', 'true', 'yes', 'on'], true);
    }
}
