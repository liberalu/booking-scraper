<?php

declare(strict_types=1);

namespace BookScraper\Runs;

use Illuminate\Support\Facades\DB;

/**
 * Advisory lock on (shop_id, phase), held across run creation so two
 * processes cannot both open a run for the same shop and phase.
 *
 * Ported from try_acquire_scan_lock() in book_scraper/db/repo.py.
 *
 * The key is crc32, not the `abs(hash(phase))` Python originally used: CPython
 * randomises string hashing per process unless PYTHONHASHSEED is set, which
 * this project does not set, so two processes computed DIFFERENT keys for the
 * same phase and both acquired "the lock" (verified: keys 975101118 vs
 * 136925746 for phase 'scan' in two processes seconds apart). Python now uses
 * `zlib.crc32` too, which is byte-identical to PHP's `crc32()`, so the two
 * stacks share one lock namespace and can be run side by side.
 */
final class ScanLock
{
    /**
     * Try to take the lock. Transaction-scoped: it releases on commit or
     * rollback, so the caller must hold its transaction open across run
     * creation for the lock to mean anything.
     */
    public static function tryAcquire(int $shopId, string $phase): bool
    {
        return (bool) DB::selectOne(
            'select pg_try_advisory_xact_lock(?, ?) as locked',
            [$shopId, self::key($phase)]
        )->locked;
    }

    /**
     * Session-scoped variant for callers that cannot hold one transaction
     * for the whole run — release() must then be explicit.
     */
    public static function tryAcquireForSession(int $shopId, string $phase): bool
    {
        return (bool) DB::selectOne(
            'select pg_try_advisory_lock(?, ?) as locked',
            [$shopId, self::key($phase)]
        )->locked;
    }

    public static function release(int $shopId, string $phase): bool
    {
        return (bool) DB::selectOne(
            'select pg_advisory_unlock(?, ?) as released',
            [$shopId, self::key($phase)]
        )->released;
    }

    /** Stable 31-bit key, identical to Python's `zlib.crc32(phase) & 0x7FFFFFFF`. */
    public static function key(string $phase): int
    {
        return crc32($phase) & 0x7FFFFFFF;
    }
}
