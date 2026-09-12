<?php

declare(strict_types=1);

namespace App\Runs;

use App\Repositories\ScanLockRepository;

final readonly class ScanLock
{
    public function __construct(
        private ScanLockRepository $repository = new ScanLockRepository,
    ) {}

    public function tryAcquire(int $shopId): bool
    {
        return $this->repository->tryAcquire($shopId);
    }

    public function tryAcquireForSession(int $shopId, bool $postPhase = false): bool
    {
        return $this->repository->tryAcquireForSession($shopId, $postPhase);
    }

    public function release(int $shopId, bool $postPhase = false): bool
    {
        return $this->repository->release($shopId, $postPhase);
    }

    public function key(bool $postPhase = false): int
    {
        return $this->repository->key($postPhase);
    }
}
