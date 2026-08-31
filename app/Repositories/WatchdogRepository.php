<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Runs\RunEvent;
use PDO;
use RuntimeException;

final class WatchdogRepository
{
    private ?PDO $connection = null;

    public function __construct(
        private readonly RunFailsafeRepository $connections = new RunFailsafeRepository,
    ) {}

    public function connect(?string $dsn): void
    {
        $this->connection = $this->connections->connect($dsn);
    }

    public function heartbeat(int $runId): ?string
    {
        $connection = $this->connection();
        $connection->exec("set statement_timeout = '2s'");
        $update = $connection->prepare(
            "update scrape_runs set last_heartbeat = now()
              where id = ? and status in ('running', 'paused')",
        );
        $update->execute([$runId]);

        $select = $connection->prepare('select status from scrape_runs where id = ?');
        $select->execute([$runId]);
        $status = $select->fetchColumn();

        return $status === false ? null : (string) $status;
    }

    public function restartDepth(int $runId): int
    {
        return $this->scalarInt(
            'select count(*) from scrape_run_events where run_id = ? and event_type = ?',
            [$runId, RunEvent::RESTARTED],
        );
    }

    public function processedCount(int $runId): int
    {
        return $this->scalarInt(
            'select urls_processed from scrape_runs where id = ?',
            [$runId],
        );
    }

    public function recordRestart(int $runId, int $attempt, int $processed): void
    {
        $insert = $this->connection()->prepare(
            'insert into scrape_run_events (run_id, event_type, created_at, actor, payload)
             values (?, ?, now(), ?, ?::jsonb)',
        );
        $insert->execute([
            $runId,
            RunEvent::RESTARTED,
            RunEvent::ACTOR_SYSTEM,
            json_encode([
                'reason' => 'stall_timeout',
                'attempt' => $attempt,
                'urls_processed_snapshot' => $processed,
            ], JSON_THROW_ON_ERROR),
        ]);
    }

    /** @param list<mixed> $bindings */
    private function scalarInt(string $sql, array $bindings): int
    {
        $statement = $this->connection()->prepare($sql);
        $statement->execute($bindings);
        $value = $statement->fetchColumn();
        if (is_int($value)) {
            return $value;
        }
        if (is_string($value) && preg_match('/^-?\d+$/', $value) === 1) {
            return (int) $value;
        }

        throw new RuntimeException('Watchdog count query did not return an integer.');
    }

    private function connection(): PDO
    {
        return $this->connection
            ?? throw new RuntimeException('watchdog repository is not connected');
    }
}
