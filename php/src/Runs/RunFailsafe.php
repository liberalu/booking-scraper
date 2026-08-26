<?php

declare(strict_types=1);

namespace BookScraper\Runs;

use BookScraper\Database;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use InvalidArgumentException;
use PDO;
use Throwable;

/**
 * Finalises a run through a FRESH connection, ported from
 * finalize_run_failsafe() in book_scraper/db/repo.py.
 *
 * Fresh because the caller's connection may be unusable — mid-failed
 * transaction after an earlier bad query — and a statement timeout because
 * a hung database must not block shutdown. Exceptions are swallowed and
 * logged: leaving the row zombie (later reaped) is strictly worse than a
 * logged finalize failure.
 */
final class RunFailsafe
{
    /** Terminal statuses that must not be overwritten. */
    private const TERMINAL = ['completed', 'failed'];

    /**
     * @param  bool  $resumableAfterFailure  Flags the row so the next run
     *   adopts its pending scrape_url_items. Stalls are recoverable: the
     *   queue still holds valid work.
     */
    public static function finalize(
        int $runId,
        string $status,
        string $reason,
        bool $resumableAfterFailure = false,
        ?string $dsn = null,
    ): bool {
        try {
            // A dedicated PDO connection, not the Eloquent one: this runs on
            // paths where the shared connection may already be broken.
            $pdo = self::connect($dsn);
            $pdo->exec("set statement_timeout = '5s'");

            // Guard: a spider's own close path may already have finished the
            // run successfully. Without this, the failsafe clobbers a
            // completed status to failed.
            $statement = $pdo->prepare('select status from scrape_runs where id = ?');
            $statement->execute([$runId]);
            $current = $statement->fetchColumn();

            if ($current === false || in_array((string) $current, self::TERMINAL, true)) {
                return false;
            }

            $update = $pdo->prepare(
                'update scrape_runs
                    set status = ?, finished_at = now(), close_reason = ?,
                        resumable_after_failure = ?
                  where id = ?'
            );
            // (int), not the bool: PDO binds PHP `false` as an empty string and
            // Postgres rejects that for a boolean, so every call that left
            // $resumableAfterFailure at its default failed — and the failure is
            // swallowed by the catch below. The three crash paths in bin/crawl
            // all take that default, which is why a crawl killed by an
            // exception never recorded its reason: the run stayed `running`
            // until the reaper relabelled it `heartbeat_timeout` a minute later.
            $update->execute([$status, $reason, (int) $resumableAfterFailure, $runId]);

            $event = $pdo->prepare(
                'insert into scrape_run_events (run_id, event_type, created_at, actor, payload)
                 values (?, ?, now(), ?, ?::jsonb)'
            );
            $event->execute([
                $runId,
                $status === 'failed' ? RunEvent::FAILED : RunEvent::COMPLETED,
                RunEvent::ACTOR_SYSTEM,
                json_encode(['reason' => $reason], JSON_THROW_ON_ERROR),
            ]);

            return true;
        } catch (Throwable $e) {
            fwrite(STDERR, sprintf(
                "  finalize failed for run %d (%s): %s\n",
                $runId,
                $reason,
                $e->getMessage()
            ));

            return false;
        }
    }

    /**
     * Records a lifecycle event without touching run status.
     *
     * A null payload stays NULL in the column — Python's
     * `emit_scrape_run_event` defaults `payload=None`, and an empty JSON
     * object would read back differently in the timeline card.
     *
     * @param array<string, mixed>|null $payload
     */
    public static function recordEvent(
        int $runId,
        string $eventType,
        ?array $payload = null,
        string $actor = RunEvent::ACTOR_SYSTEM,
    ): void {
        if (!in_array($eventType, RunEvent::ALL, true)) {
            throw new InvalidArgumentException(
                "unknown scrape run event_type: '{$eventType}'"
            );
        }
        DB::table('scrape_run_events')->insert([
            'run_id' => $runId,
            'event_type' => $eventType,
            'created_at' => Carbon::now('UTC'),
            'actor' => $actor,
            'payload' => $payload === null
                ? null
                : json_encode($payload, JSON_THROW_ON_ERROR),
        ]);
    }

    /**
     * A standalone PDO handle. Built from the same DSN resolution as
     * Database so a caller in a forked child needs no extra config.
     */
    public static function connect(?string $dsn = null): PDO
    {
        $config = Database::connectionConfig($dsn);

        return new PDO(
            sprintf(
                'pgsql:host=%s;port=%d;dbname=%s',
                $config['host'],
                $config['port'],
                $config['database']
            ),
            $config['username'],
            $config['password'],
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
        );
    }
}
