<?php

declare(strict_types=1);

namespace App\DTO\ReadModel;

final readonly class RunStateSnapshot
{
    public function __construct(
        public string $status,
        public ?string $finishedAt,
        public ?string $closeReason,
        public ?string $lastHeartbeat,
        public ?int $pid,
    ) {}

    /** @return array{status: string, finished_at: ?string, close_reason: ?string, last_heartbeat: ?string, pid: ?int} */
    public function toDatabaseValues(): array
    {
        return [
            'status' => $this->status,
            'finished_at' => $this->finishedAt,
            'close_reason' => $this->closeReason,
            'last_heartbeat' => $this->lastHeartbeat,
            'pid' => $this->pid,
        ];
    }
}
