<?php

declare(strict_types=1);

namespace App\Runs;

use App\Repositories\RunReconcilerRepository;

final readonly class RunReconciler
{
    public const int RETRY_CAP = RunReconcilerRepository::RETRY_CAP;

    public function __construct(
        private RunReconcilerRepository $repository = new RunReconcilerRepository,
    ) {}

    /** @return list<array{id: int, shop: string, phase: string}> */
    public function markOrphansFailed(): array
    {
        return $this->repository->markOrphansFailed();
    }

    public function resetRetryableFailures(
        int $runId,
        int $cap = self::RETRY_CAP,
    ): int {
        return $this->repository->resetRetryableFailures($runId, $cap);
    }

    public function releaseStuckProcessing(int $runId): int
    {
        return $this->repository->releaseStuckProcessing($runId);
    }
}
