<?php

declare(strict_types=1);

namespace App\Crawler\Scheduling;

use DateTimeImmutable;
use RoachPHP\Scheduling\Timing\ClockInterface;

final class SubSecondClock implements ClockInterface
{
    public function now(): DateTimeImmutable
    {

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
