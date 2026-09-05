<?php

declare(strict_types=1);

namespace App\Runs;

use App\Repositories\ReaperRepository;

final readonly class Reaper
{
    public const int DEAD_RUN_SECONDS = ReaperRepository::DEAD_RUN_SECONDS;

    public const int STUCK_ROW_THRESHOLD_S = ReaperRepository::STUCK_ROW_THRESHOLD_S;

    public const int PAUSED_RUN_SECONDS = ReaperRepository::PAUSED_RUN_SECONDS;

    public const int RESUMABLE_RETENTION_SECONDS = ReaperRepository::RESUMABLE_RETENTION_SECONDS;

    public function __construct(
        private ReaperRepository $repository = new ReaperRepository,
    ) {}

    /** @return list<array{run_id: int, shop: string, phase: string, close_reason: string}> */
    public function sweep(): array
    {
        return $this->repository->sweep();
    }

    public function sweepOrphanedProcessingItems(): int
    {
        return $this->repository->sweepOrphanedProcessingItems();
    }
}
