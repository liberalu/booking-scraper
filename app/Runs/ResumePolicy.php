<?php

declare(strict_types=1);

namespace App\Runs;

use App\DTO\ReadModel\ResumableRun;
use App\Repositories\ResumePolicyRepository;

final readonly class ResumePolicy
{
    private const int ZERO_PROGRESS_THRESHOLD = 2;

    public function __construct(
        private int $maxAttempts,
        private ResumePolicyRepository $repository = new ResumePolicyRepository,
    ) {}

    /** @return array{allowed: bool, attempt: int, reason: string} */
    public function evaluate(int $runId): array
    {
        if ($this->maxAttempts <= 0) {
            return ['allowed' => false, 'attempt' => 0, 'reason' => 'auto-resume disabled'];
        }

        $depth = $this->repository->chainDepth($runId);
        $zeroProgress = $this->repository->consecutiveZeroProgress($runId);

        if ($zeroProgress >= self::ZERO_PROGRESS_THRESHOLD) {
            return [
                'allowed' => false,
                'attempt' => $depth,
                'reason' => sprintf(
                    '%d consecutive zero-progress restarts (threshold %d) — the bug is '
                    .'structural, an operator must diagnose before continuing',
                    $zeroProgress,
                    self::ZERO_PROGRESS_THRESHOLD,
                ),
            ];
        }

        if ($depth >= $this->maxAttempts) {
            return [
                'allowed' => false,
                'attempt' => $depth,
                'reason' => sprintf(
                    'auto-resume cap reached (depth %d, max %d) — operator can Continue '
                    .'from the dashboard',
                    $depth,
                    $this->maxAttempts,
                ),
            ];
        }

        return [
            'allowed' => true,
            'attempt' => $depth + 1,
            'reason' => sprintf('attempt %d/%d', $depth + 1, $this->maxAttempts),
        ];
    }

    public function chainDepth(int $runId): int
    {
        return $this->repository->chainDepth($runId);
    }

    public function consecutiveZeroProgress(int $runId): int
    {
        return $this->repository->consecutiveZeroProgress($runId);
    }

    public function findResumable(int $shopId, string $phase): ?ResumableRun
    {
        return $this->repository->findResumable($shopId, $phase);
    }

    public function findResumableById(int $runId, int $shopId, string $phase): ?ResumableRun
    {
        return $this->repository->findResumableById($runId, $shopId, $phase);
    }
}
