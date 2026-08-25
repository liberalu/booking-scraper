<?php

declare(strict_types=1);

namespace BookScraper\Crawler;

use BookScraper\Runs\RunEvent;
use BookScraper\Runs\RunFailsafe;
use PDO;
use Throwable;

/**
 * Heartbeat writer and stall detector, running in a FORKED CHILD.
 *
 * The Python version runs both in-process — the heartbeat on Twisted's
 * worker pool specifically so a hung psycopg2 call cannot freeze the
 * reactor (that froze runs 194/195). roach is synchronous with no event
 * loop, so an in-process timer would be worse: any blocking call in the
 * crawl stops the heartbeat entirely and the dashboard reaper kills a run
 * that is merely slow.
 *
 * A separate process sidesteps that: the child keeps ticking no matter
 * what the parent is doing, which is strictly stronger than a thread.
 *
 * Parent → child signalling is the mtime of a marker file. Crude on
 * purpose: no shared memory, no sockets, and it survives a parent stuck
 * inside a blocking syscall, which is exactly the case being detected.
 */
final class Watchdog
{
    /** Statuses whose heartbeat should keep ticking. A paused run is alive. */
    private const TICKING_STATUSES = ['running', 'paused'];

    private ?int $childPid = null;

    private readonly string $markerPath;

    public function __construct(
        private readonly int $runId,
        private readonly string $shop,
        private readonly string $phase,
        private readonly float $stallTimeout,
        private readonly float $heartbeatInterval = 5.0,
        private readonly int $maxResumeAttempts = 10,
        ?string $markerPath = null,
        private readonly ?string $dsn = null,
    ) {
        $this->markerPath = $markerPath
            ?? sys_get_temp_dir() . "/book-scraper-activity-{$runId}-" . getmypid();
    }

    public function markerPath(): string
    {
        return $this->markerPath;
    }

    /** Called by the parent on every response/item. Must stay cheap. */
    public function recordActivity(): void
    {
        // touch() is one syscall and the child only reads mtime.
        @touch($this->markerPath);
    }

    /**
     * Fork the watchdog. Returns false when pcntl is unavailable, in which
     * case the caller runs unsupervised rather than not at all.
     */
    public function start(): bool
    {
        if (!function_exists('pcntl_fork')) {
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

        // Child. Never return: the parent's shutdown path must not run twice.
        $this->supervise(posix_getppid());
        exit(0);
    }

    /** Stop the watchdog. Safe to call when it never started. */
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

    // ------------------------------------------------------------- child

    private function supervise(int $parentPid): void
    {
        // The child opens its OWN connection: inheriting the parent's would
        // let two processes write on one socket.
        try {
            $pdo = RunFailsafe::connect($this->dsn);
        } catch (Throwable $e) {
            fwrite(STDERR, "  watchdog: cannot connect ({$e->getMessage()})\n");

            return;
        }

        $running = true;
        pcntl_signal(SIGTERM, static function () use (&$running): void {
            $running = false;
        });

        while ($running) {
            // Sleep first so the very first tick doesn't race the parent
            // still creating the run row.
            $this->interruptibleSleep($this->heartbeatInterval);
            pcntl_signal_dispatch();
            if (!$running) {
                break;
            }

            // Parent gone: nothing to supervise, and the exit path (or the
            // reaper) owns the run row from here.
            if (posix_kill($parentPid, 0) === false) {
                return;
            }

            $status = $this->tick($pdo);

            // Operator pressed Stop on the dashboard.
            if ($status === 'stopping') {
                fwrite(STDERR, "  watchdog: operator stop requested — signalling parent\n");
                posix_kill($parentPid, SIGTERM);

                return;
            }
            // Someone else finalised the run (reaper, operator); stop ticking
            // so a late write can't make a dead row look alive.
            if ($status !== null && !in_array($status, self::TICKING_STATUSES, true)) {
                return;
            }

            if ($this->isStalled()) {
                $this->handleStall($parentPid);

                return;
            }
        }
    }

    /** Refresh the heartbeat and report the run's current status. */
    private function tick(PDO $pdo): ?string
    {
        try {
            // A per-statement timeout so a hung database can't pile up ticks.
            $pdo->exec("set statement_timeout = '2s'");
            $update = $pdo->prepare(
                "update scrape_runs set last_heartbeat = now()
                  where id = ? and status in ('running', 'paused')"
            );
            $update->execute([$this->runId]);

            $select = $pdo->prepare('select status from scrape_runs where id = ?');
            $select->execute([$this->runId]);
            $status = $select->fetchColumn();

            return $status === false ? null : (string) $status;
        } catch (Throwable $e) {
            // A failed tick is survivable — the next one may succeed, and the
            // reaper is the backstop if they all fail.
            fwrite(STDERR, "  watchdog: heartbeat failed ({$e->getMessage()})\n");

            return 'running';
        }
    }

    private function isStalled(): bool
    {
        clearstatcache(true, $this->markerPath);
        $mtime = @filemtime($this->markerPath);
        if ($mtime === false) {
            // No marker means the parent never got going; let the timeout
            // apply from the watchdog's own start instead of firing at once.
            return false;
        }

        return (time() - $mtime) > $this->stallTimeout;
    }

    /**
     * Fail the run, then decide whether to restart it.
     *
     * Order matters: the run is finalised BEFORE the parent is killed, so a
     * parent that dies badly can't leave the row zombie-running.
     */
    private function handleStall(int $parentPid): void
    {
        fwrite(STDERR, sprintf(
            "  watchdog: no activity for %.0fs — failing run %d and stopping the crawl\n",
            $this->stallTimeout,
            $this->runId
        ));

        // resumable: the queue still holds pending URLs worth adopting.
        RunFailsafe::finalize($this->runId, 'failed', 'stall_timeout', true, $this->dsn);

        posix_kill($parentPid, SIGTERM);

        $this->maybeRestart();
    }

    /**
     * Spawn a replacement process when policy allows.
     *
     * The decision is re-read from the database rather than passed in,
     * because the restart events it counts are written by earlier processes
     * in the same chain.
     */
    private function maybeRestart(): void
    {
        try {
            $pdo = RunFailsafe::connect($this->dsn);

            $depth = (int) $this->scalar(
                $pdo,
                'select count(*) from scrape_run_events where run_id = ? and event_type = ?',
                [$this->runId, RunEvent::RESTARTED]
            );
            if ($depth >= $this->maxResumeAttempts) {
                fwrite(STDERR, sprintf(
                    "  watchdog: restart cap reached (%d/%d) — leaving run failed for an operator\n",
                    $depth,
                    $this->maxResumeAttempts
                ));

                return;
            }

            $processed = (int) $this->scalar(
                $pdo,
                'select urls_processed from scrape_runs where id = ?',
                [$this->runId]
            );

            // Snapshot goes on the event so the zero-progress circuit breaker
            // can tell a stuck chain from a slow one.
            $insert = $pdo->prepare(
                'insert into scrape_run_events (run_id, event_type, created_at, actor, payload)
                 values (?, ?, now(), ?, ?::jsonb)'
            );
            $insert->execute([
                $this->runId,
                RunEvent::RESTARTED,
                RunEvent::ACTOR_SYSTEM,
                json_encode([
                    'reason' => 'stall_timeout',
                    'attempt' => $depth + 1,
                    'urls_processed_snapshot' => $processed,
                ], JSON_THROW_ON_ERROR),
            ]);

            $this->spawnReplacement($depth + 1);
        } catch (Throwable $e) {
            fwrite(STDERR, "  watchdog: restart bookkeeping failed ({$e->getMessage()})\n");
        }
    }

    private function spawnReplacement(int $attempt): void
    {
        $binary = PHP_BINARY;
        $script = dirname(__DIR__) . '/bin/crawl';

        $command = sprintf(
            '%s %s %s --shop=%s --resumed-attempt=%d',
            escapeshellarg($binary),
            escapeshellarg($script),
            escapeshellarg($this->phase),
            escapeshellarg($this->shop),
            $attempt
        );

        // Detached: this child is about to exit, and the replacement must
        // outlive it. setsid via `&` + nohup keeps it off our process group.
        $detached = sprintf('nohup %s > /dev/null 2>&1 &', $command);
        fwrite(STDERR, "  watchdog: restarting — attempt {$attempt}\n");
        exec($detached);
    }

    private function scalar(PDO $pdo, string $sql, array $bindings): mixed
    {
        $statement = $pdo->prepare($sql);
        $statement->execute($bindings);

        return $statement->fetchColumn();
    }

    /** sleep() that still notices SIGTERM promptly. */
    private function interruptibleSleep(float $seconds): void
    {
        $deadline = microtime(true) + $seconds;
        while (microtime(true) < $deadline) {
            usleep(200_000);
            pcntl_signal_dispatch();
        }
    }
}
