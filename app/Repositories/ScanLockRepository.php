<?php

declare(strict_types=1);

namespace App\Repositories;

use Illuminate\Support\Facades\DB;

final class ScanLockRepository
{
    public function tryAcquire(int $shopId, string $phase): bool
    {
        return DatabaseRow::from(DB::selectOne(
            'select pg_try_advisory_xact_lock(?, ?) as locked',
            [$shopId, $this->key($phase)]
        ))->bool('locked');
    }

    public function tryAcquireForSession(int $shopId, string $phase): bool
    {
        return DatabaseRow::from(DB::selectOne(
            'select pg_try_advisory_lock(?, ?) as locked',
            [$shopId, $this->key($phase)]
        ))->bool('locked');
    }

    public function release(int $shopId, string $phase): bool
    {
        return DatabaseRow::from(DB::selectOne(
            'select pg_advisory_unlock(?, ?) as released',
            [$shopId, $this->key($phase)]
        ))->bool('released');
    }

    public function key(string $phase): int
    {
        return crc32($phase) & 0x7FFFFFFF;
    }
}
