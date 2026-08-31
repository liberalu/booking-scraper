<?php

declare(strict_types=1);

namespace App\Runs;

use App\Repositories\ScanLockRepository;

final class ScanLock
{
    public function __construct(
        private readonly ScanLockRepository $repository = new ScanLockRepository,
    ) {}

    public function tryAcquire(int $shopId, string $phase): bool
    {
        return $this->repository->tryAcquire($shopId, $phase);
    }

    public function tryAcquireForSession(int $shopId, string $phase): bool
    {
        return $this->repository->tryAcquireForSession($shopId, $phase);
    }

    public function release(int $shopId, string $phase): bool
    {
        return $this->repository->release($shopId, $phase);
    }

    public function key(string $phase): int
    {
        return $this->repository->key($phase);
    }
}
