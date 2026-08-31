<?php

declare(strict_types=1);

namespace App\Runs;

use App\Repositories\RunFinisherRepository;

final class RunFinisher
{
    public function __construct(
        private readonly RunFinisherRepository $repository = new RunFinisherRepository,
    ) {}

    public function finish(
        int $runId,
        string $status,
        ?string $reason = null,
        bool $resumableAfterFailure = false,
    ): bool {
        return $this->repository->finish($runId, $status, $reason, $resumableAfterFailure);
    }

    public function abortProcessingItems(int $runId): int
    {
        return $this->repository->abortProcessingItems($runId);
    }
}
