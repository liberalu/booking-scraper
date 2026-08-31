<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Models\CronJob;
use App\Repositories\PostPhaseRepository;
use App\Runs\RunEvent;
use App\Runs\RunFailsafe;
use App\Runs\RunPhase;
use App\Services\MatchService;
use Throwable;

final class PostPhase
{
    private const SPAWN_CONTEXT = 'post-phase-auto';

    public function __construct(
        private readonly PostPhaseRepository $repository,
        private readonly MatchService $matcher,
        private readonly RunFailsafe $failsafe,
    ) {}

    public function after(
        string $phase,
        string $shopName,
        int $runId,
        ?int $cronJobId,
    ): void {
        $chainJob = $cronJobId === null ? null : $this->chainTarget($cronJobId);

        if ($chainJob !== null) {
            $this->spawnCronChain($chainJob);
            if (in_array($chainJob->phase, ['match', 'validate'], true)) {

                return;
            }
        }

        if (! $this->autoTriggerEnabled()) {
            fwrite(STDOUT, "post-phase: disabled via env, skipping\n");

            return;
        }

        try {
            $linked = $this->matcher->isbnMatch($shopName);
            printf("post-phase: ISBN-match linked %d shop_book(s)\n", $linked);
        } catch (Throwable $e) {
            fwrite(STDERR, "post-phase: ISBN-match failed: {$e->getMessage()}\n");
        }

        $this->spawnValidate($shopName);
    }

    public function chainSkipped(int $runId, ?int $cronJobId, string $reason): void
    {
        if ($cronJobId === null) {
            return;
        }
        try {
            $this->failsafe->recordEvent($runId, RunEvent::CHAIN_SKIPPED, [
                'parent_reason' => $reason,
                'cron_job_id' => $cronJobId,
            ]);
        } catch (Throwable $e) {
            fwrite(STDERR, "post-phase: could not record chain_skipped: {$e->getMessage()}\n");
        }
    }

    private function chainTarget(int $cronJobId): ?CronJob
    {
        try {
            return $this->repository->chainTarget($cronJobId);
        } catch (Throwable $e) {
            fwrite(STDERR, "post-phase: chain lookup failed: {$e->getMessage()}\n");

            return null;
        }
    }

    private function spawnCronChain(CronJob $job): void
    {
        $shop = $job->shop->name;
        $phase = $job->phase;
        $cmd = $this->crawlerCommand($phase, $shop);
        if ($cmd === null) {
            return;
        }
        if ($phase === 'discover' && $job->strategy !== null && $job->strategy !== '') {
            $cmd[] = "--strategy={$job->strategy}";
        }
        $cmd[] = "--cron-job-id={$job->id}";
        if (($job->args ?? '') !== '') {
            $args = preg_split('/\s+/', trim($job->args ?? ''), -1, PREG_SPLIT_NO_EMPTY);
            foreach ($args !== false ? $args : [] as $arg) {
                $cmd[] = $arg;
            }
        }
        $cmd[] = '--database='.$this->databaseUrl();

        $log = $this->detach($cmd, 'cron-chain', $shop);
        printf("post-phase: spawned chain job %d (%s) log=%s\n", $job->id, $phase, $log);
    }

    private function spawnValidate(string $shopName): void
    {
        $binary = $this->phpBinary();
        $script = dirname(__DIR__, 2).'/bin/validate';
        if ($binary === null || ! is_file($script)) {
            fwrite(STDERR, "post-phase: validate binary not found, skipping\n");

            return;
        }
        $cmd = [$binary, $script, "--shop={$shopName}", '--database='.$this->databaseUrl()];
        $log = $this->detach($cmd, self::SPAWN_CONTEXT, $shopName);
        printf("post-phase: spawned validate for %s log=%s\n", $shopName, $log);
    }

    /** @return list<string>|null */
    private function crawlerCommand(string $phase, string $shop): ?array
    {
        $binary = $this->phpBinary();
        if ($binary === null) {
            return null;
        }
        $runPhase = RunPhase::tryFrom($phase);
        if ($runPhase === null) {
            fwrite(STDERR, "post-phase: no crawler command for phase '{$phase}'\n");

            return null;
        }

        $command = in_array($runPhase, [RunPhase::Scan, RunPhase::Discover], true)
            ? [$binary, dirname(__DIR__, 2).'/artisan', 'crawler:run']
            : [$binary, dirname(__DIR__, 2).'/bin/'.$runPhase->script()];
        if (in_array($runPhase, [RunPhase::Scan, RunPhase::Discover], true)) {
            $command[] = $runPhase->value;
        }
        $command[] = "--shop={$shop}";

        return $command;
    }

    /** @param list<string> $cmd */
    private function detach(array $cmd, string $role, string $shop): string
    {
        $log = $this->logPath($role, $shop);
        $script = sprintf(
            'mkdir -p %s && nohup %s >> %s 2>&1 &',
            escapeshellarg(dirname($log)),
            implode(' ', array_map(
                static fn (string $argument): string => escapeshellarg($argument),
                $cmd,
            )),
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

    private function logPath(string $role, string $shop): string
    {
        $configuredDir = getenv('SPAWN_LOG_DIR');
        $dir = is_string($configuredDir) && $configuredDir !== ''
            ? $configuredDir
            : '/var/log/scrapy_runs';
        if (! $this->isUsableDir($dir)) {
            $fallback = sys_get_temp_dir().'/book-scraper-spawn';
            fwrite(STDERR, "post-phase: {$dir} is not writable, logging to {$fallback}\n");
            $dir = $fallback;
        }
        $stamp = (new \DateTimeImmutable('now', new \DateTimeZone('UTC')))->format('Ymd-Hisu');
        $slug = static function (string $value): string {
            $normalized = trim(
                preg_replace('/[^A-Za-z0-9._-]+/', '-', $value) ?? $value,
                '-',
            );

            return $normalized !== '' ? $normalized : 'unknown';
        };

        return sprintf('%s/spawn-%s-%s-%s.log', rtrim($dir, '/'), $stamp, $slug($role), $slug($shop));
    }

    private function isUsableDir(string $dir): bool
    {
        if (is_dir($dir)) {
            return is_writable($dir);
        }

        $parent = \dirname($dir);
        while ($parent !== '/' && $parent !== '.' && ! is_dir($parent)) {
            $parent = \dirname($parent);
        }

        return is_writable($parent);
    }

    private function phpBinary(): ?string
    {
        foreach ([getenv('CRAWLER_PHP_BINARY'), PHP_BINARY] as $candidate) {
            if (is_string($candidate) && $candidate !== '' && is_executable($candidate)) {
                return $candidate;
            }
        }

        return null;
    }

    private function databaseUrl(): string
    {
        return $this->repository->databaseUrl();
    }

    private function autoTriggerEnabled(): bool
    {

        $raw = getenv('POST_PHASE_AUTO_TRIGGER');
        if (! is_string($raw) || $raw === '') {
            $raw = getenv('POST_SCAN_AUTO_TRIGGER');
        }
        if (! is_string($raw) || $raw === '') {
            return true;
        }

        return in_array(strtolower($raw), ['1', 'true', 'yes', 'on'], true);
    }
}
