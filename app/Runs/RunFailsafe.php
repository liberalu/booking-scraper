<?php

declare(strict_types=1);

namespace App\Runs;

use App\Repositories\RunFailsafeRepository;

final readonly class RunFailsafe
{
    public function __construct(
        private RunFailsafeRepository $repository = new RunFailsafeRepository,
    ) {}

    public function finalize(
        int $runId,
        string $status,
        string $reason,
        bool $resumableAfterFailure = false,
        ?string $dsn = null,
    ): bool {
        return $this->repository->finalize(
            $runId,
            $status,
            $reason,
            $resumableAfterFailure,
            $dsn,
        );
    }

    /** @param array<string, mixed>|null $payload */
    public function recordEvent(
        int $runId,
        string $eventType,
        ?array $payload = null,
        string $actor = RunEvent::ACTOR_SYSTEM,
    ): void {
        $this->repository->recordEvent($runId, $eventType, $payload, $actor);
    }
}
