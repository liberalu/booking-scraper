<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Repositories\WatchdogRepository;
use App\Runs\RunFailsafe;
use Throwable;

final class Watchdog
{
    private const TICKING_STATUSES = ['running', 'paused'];

    private ?int $childPid = null;

    private readonly string $markerPath;

    private bool $supervising = true;

    public function __construct(
        private readonly int $runId,
        private readonly string $shop,
        private readonly string $phase,
        private readonly float $stallTimeout,
        private readonly float $heartbeatInterval = 5.0,
        private readonly int $maxResumeAttempts = 10,
        ?string $markerPath = null,
        private readonly ?string $dsn = null,
        private readonly RunFailsafe $failsafe = new RunFailsafe,
        private readonly WatchdogRepository $runs = new WatchdogRepository,
    ) {
        $this->markerPath = $markerPath
            ?? sys_get_temp_dir()."/book-scraper-activity-{$runId}-".getmypid();
    }

    public function markerPath(): string
    {
        return $this->markerPath;
    }

    public function recordActivity(): void
    {

        @touch($this->markerPath);
    }

    public function start(): bool
    {
        if (! function_exists('pcntl_fork')) {
            fwrite(STDERR, "  watchdog: pcntl unavailable — running unsupervised\n");

            return false;
        }

        $this->recordActivity();

        $pid = pcntl_fork();
        if ($pid === -1) {
            fwrite(STDERR, "  watchdog: fork failed — running unsupervised\n");

            return false;
        }
        if ($pid > 0) {
            $this->childPid = $pid;

            return true;
        }

        $this->supervise(posix_getppid());
        exit(0);
    }

    public function stop(): void
    {
        if ($this->childPid === null) {
            @unlink($this->markerPath);

            return;
        }

        posix_kill($this->childPid, SIGTERM);
        pcntl_waitpid($this->childPid, $status);
        $this->childPid = null;
        @unlink($this->markerPath);
    }

    private function supervise(int $parentPid): void
    {

        try {
            $this->runs->connect($this->dsn);
        } catch (Throwable $e) {
            fwrite(STDERR, "  watchdog: cannot connect ({$e->getMessage()})\n");

            return;
        }

        $this->supervising = true;
        pcntl_signal(SIGTERM, function (): void {
            $this->supervising = false;
        });

        while ($this->supervising) {

            $this->interruptibleSleep($this->heartbeatInterval);
            pcntl_signal_dispatch();
            if (! $this->supervising) {
                break;
            }

            if (posix_kill($parentPid, 0) === false) {
                return;
            }

            $status = $this->tick();

            if ($status === 'stopping') {
                fwrite(STDERR, "  watchdog: operator stop requested — signalling parent\n");
                posix_kill($parentPid, SIGTERM);

                return;
            }

            if ($status !== null && ! in_array($status, self::TICKING_STATUSES, true)) {
                return;
            }

            if ($this->isStalled()) {
                $this->handleStall($parentPid);

                return;
            }
        }
    }

    private function tick(): ?string
    {
        try {
            return $this->runs->heartbeat($this->runId);
        } catch (Throwable $e) {

            fwrite(STDERR, "  watchdog: heartbeat failed ({$e->getMessage()})\n");

            return 'running';
        }
    }

    private function isStalled(): bool
    {
        clearstatcache(true, $this->markerPath);
        $mtime = @filemtime($this->markerPath);
        if ($mtime === false) {

            return false;
        }

        return (time() - $mtime) > $this->stallTimeout;
    }

    private function handleStall(int $parentPid): void
    {
        fwrite(STDERR, sprintf(
            "  watchdog: no activity for %.0fs — failing run %d and stopping the crawl\n",
            $this->stallTimeout,
            $this->runId
        ));

        $this->failsafe->finalize($this->runId, 'failed', 'stall_timeout', true, $this->dsn);

        posix_kill($parentPid, SIGTERM);

        $this->maybeRestart();
    }

    private function maybeRestart(): void
    {
        try {
            $this->runs->connect($this->dsn);
            $depth = $this->runs->restartDepth($this->runId);
            if ($depth >= $this->maxResumeAttempts) {
                fwrite(STDERR, sprintf(
                    "  watchdog: restart cap reached (%d/%d) — leaving run failed for an operator\n",
                    $depth,
                    $this->maxResumeAttempts
                ));

                return;
            }

            $processed = $this->runs->processedCount($this->runId);
            $this->runs->recordRestart($this->runId, $depth + 1, $processed);

            $this->spawnReplacement($depth + 1);
        } catch (Throwable $e) {
            fwrite(STDERR, "  watchdog: restart bookkeeping failed ({$e->getMessage()})\n");
        }
    }

    private function spawnReplacement(int $attempt): void
    {
        $binary = PHP_BINARY;
        $artisan = dirname(__DIR__, 2).'/artisan';

        $command = sprintf(
            '%s %s crawler:run %s --shop=%s --resumed-attempt=%d',
            escapeshellarg($binary),
            escapeshellarg($artisan),
            escapeshellarg($this->phase),
            escapeshellarg($this->shop),
            $attempt
        );

        $detached = sprintf('nohup %s > /dev/null 2>&1 &', $command);
        fwrite(STDERR, "  watchdog: restarting — attempt {$attempt}\n");
        exec($detached);
    }

    private function interruptibleSleep(float $seconds): void
    {
        $deadline = microtime(true) + $seconds;
        while (microtime(true) < $deadline) {
            usleep(200_000);
            pcntl_signal_dispatch();
        }
    }
}
