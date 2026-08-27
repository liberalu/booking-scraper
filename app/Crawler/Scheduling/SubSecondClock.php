<?php

declare(strict_types=1);

namespace App\Crawler\Scheduling;

use DateTimeImmutable;
use RoachPHP\Scheduling\Timing\ClockInterface;

/**
 * Roach's SystemClock truncates to whole seconds: sleepUntil() calls
 * getTimestamp() and time_sleep_until() with an int, so any sub-second
 * target rounds away. Five of six shops in config/shops/ pace below 1s
 * (vaga 0.2, ibiblioteka 0.1, almalittera 0.3, humanitas/patogupirkti
 * 0.5), so truncation means choosing between hammering the shop at 0s and
 * running ~5x slower at 1s.
 *
 * time_sleep_until() itself accepts a float; only roach's plumbing was
 * integer. This clock keeps the microseconds.
 */
final class SubSecondClock implements ClockInterface
{
    public function now(): DateTimeImmutable
    {
        // 'now' with microsecond precision — the default constructor
        // already carries µs, but be explicit about relying on it.
        return new DateTimeImmutable('now');
    }

    public function sleep(int $seconds): void
    {
        if ($seconds > 0) {
            \sleep($seconds);
        }
    }

    public function sleepUntil(DateTimeImmutable $date): void
    {
        $target = (float) $date->format('U.u');
        $now = (float) $this->now()->format('U.u');

        if ($target <= $now) {
            return;
        }

        \time_sleep_until($target);
    }
}
