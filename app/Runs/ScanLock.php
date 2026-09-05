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

    public function tryAcquireForSession(int $shopId): bool
    {
        return $this->repository->tryAcquireForSession($shopId);
    }

    public function release(int $shopId): bool
    {
        return $this->repository->release($shopId);
    }

    public function key(): int
    {
        return $this->repository->key();
    }
}
