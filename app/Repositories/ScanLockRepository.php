<?php

declare(strict_types=1);

namespace App\Repositories;

use Illuminate\Support\Facades\DB;

final class ScanLockRepository
{
    private const int SHOP_CRAWL_KEY = 739_102_411;

    private const int SHOP_POST_PHASE_KEY = 739_102_412;

    public function tryAcquire(int $shopId): bool
    {
        return DatabaseRow::from(DB::selectOne(
            'select pg_try_advisory_xact_lock(?, ?) as locked',
            [$shopId, $this->key()]
        ))->bool('locked');
    }

    public function tryAcquireForSession(int $shopId, bool $postPhase = false): bool
    {
        return DatabaseRow::from(DB::selectOne(
            'select pg_try_advisory_lock(?, ?) as locked',
            [$shopId, $this->key($postPhase)]
        ))->bool('locked');
    }

    public function release(int $shopId, bool $postPhase = false): bool
    {
        return DatabaseRow::from(DB::selectOne(
            'select pg_advisory_unlock(?, ?) as released',
            [$shopId, $this->key($postPhase)]
        ))->bool('released');
    }

    public function key(bool $postPhase = false): int
    {
        return $postPhase ? self::SHOP_POST_PHASE_KEY : self::SHOP_CRAWL_KEY;
    }
}
