<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ScrapeRun;
use App\Runs\RunEvent;
use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\DatabaseManager;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Facades\Date;

final readonly class ScrapeRunRepository
{
    public function __construct(
        private DatabaseManager $database,
        private RunFailsafeRepository $failsafe,
    ) {}

    public function requestStop(ScrapeRun $run): void
    {
        $this->transition($run, 'stopping', RunEvent::STOP_REQUESTED, null);
    }

    public function pause(ScrapeRun $run): void
    {
        $this->transition($run, 'paused', RunEvent::PAUSED, ['previous_status' => 'running']);
    }

    public function resume(ScrapeRun $run): void
    {
        $this->connection()->transaction(function () use ($run): void {
            ScrapeRun::whereKey($run->getKey())->update([
                'status' => 'running',
                'last_heartbeat' => Date::now('UTC'),
            ]);
            $this->failsafe->recordEvent(
                $run->id,
                RunEvent::RESUMED,
                ['previous_status' => 'paused'],
                RunEvent::ACTOR_OPERATOR,
            );
        });
    }

    public function acknowledgeFailures(
        ScrapeRun $run,
        string $errorReason,
        bool $reasonIsNull,
        ?int $httpStatus,
        bool $statusIsNull,
        string $note,
    ): int {
        $query = $this->failureQuery(
            $run->id,
            $errorReason,
            $reasonIsNull,
            $httpStatus,
            $statusIsNull,
        );
        $matches = (clone $query)->count();
        if ($matches === 0) {
            return 0;
        }

        $values = [
            'lifecycle_state' => 'acknowledged',
            'acknowledged_at' => Date::now('UTC'),
        ];
        if ($note !== '') {
            $values['acknowledged_note'] = $note;
        }
        $query->update($values);

        return $matches;
    }

    /** @param array<string, mixed>|null $payload */
    private function transition(
        ScrapeRun $run,
        string $status,
        string $event,
        ?array $payload,
    ): void {
        $runId = $run->id;
        $this->connection()->transaction(function () use ($runId, $status, $event, $payload): void {
            ScrapeRun::whereKey($runId)->update(['status' => $status]);
            $this->failsafe->recordEvent($runId, $event, $payload, RunEvent::ACTOR_OPERATOR);
        });
    }

    private function failureQuery(
        int $runId,
        string $errorReason,
        bool $reasonIsNull,
        ?int $httpStatus,
        bool $statusIsNull,
    ): Builder {
        $query = $this->connection()->table('scrape_failures')->where('run_id', $runId);
        if ($reasonIsNull) {
            $query->whereNull('error_reason');
        } elseif ($errorReason !== '') {
            $query->where('error_reason', $errorReason);
        }
        if ($statusIsNull) {
            $query->whereNull('http_status');
        } elseif ($httpStatus !== null) {
            $query->where('http_status', $httpStatus);
        }

        return $query;
    }

    private function connection(): ConnectionInterface
    {
        return $this->database->connection();
    }
}
