<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Runs\RunEvent;
use App\Support\Database;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use InvalidArgumentException;
use PDO;
use Throwable;

final class RunFailsafeRepository
{
    private const TERMINAL = ['completed', 'failed'];

    public function finalize(
        int $runId,
        string $status,
        string $reason,
        bool $resumableAfterFailure = false,
        ?string $dsn = null,
    ): bool {
        try {

            $pdo = $this->connect($dsn);
            $pdo->exec("set statement_timeout = '5s'");

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

    /** @param array<string, mixed>|null $payload */
    public function recordEvent(
        int $runId,
        string $eventType,
        ?array $payload = null,
        string $actor = RunEvent::ACTOR_SYSTEM,
    ): void {
        if (! in_array($eventType, RunEvent::ALL, true)) {
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

    public function connect(?string $dsn = null): PDO
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
