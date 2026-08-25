<?php

declare(strict_types=1);

namespace BookScraper\Crawler\Tests;

use BookScraper\Crawler\Scheduling\SubSecondClock;
use BookScraper\Crawler\Scheduling\SubSecondRequestScheduler;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;
use RoachPHP\Http\Request;
use RoachPHP\Http\Response;
use RoachPHP\Scheduling\ArrayRequestScheduler;
use RoachPHP\Scheduling\Timing\SystemClock;

/**
 * Guards the reason this scheduler exists: the shop configs pace below one
 * second and roach's own scheduler cannot express that.
 */
final class SubSecondSchedulerTest extends TestCase
{
    /** @return list<array{0: float, 1: int}> */
    public static function delays(): array
    {
        return [
            'vaga 0.2s' => [0.2, 4],
            'ibiblioteka 0.1s' => [0.1, 4],
            'almalittera 0.3s' => [0.3, 2],
        ];
    }

    #[DataProvider('delays')]
    public function test_paces_in_fractional_seconds(float $delay, int $waits): void
    {
        $scheduler = new SubSecondRequestScheduler(new SubSecondClock());
        $scheduler->setDelaySeconds($delay);
        for ($i = 0; $i <= $waits; $i++) {
            $scheduler->schedule(self::request("https://example.test/{$i}"));
        }

        $started = microtime(true);
        // The first batch is ready immediately; each later batch waits.
        for ($i = 0; $i <= $waits; $i++) {
            $scheduler->nextRequests(1);
        }
        $elapsed = microtime(true) - $started;

        $expected = $delay * $waits;
        self::assertGreaterThanOrEqual($expected * 0.85, $elapsed);
        // Generous upper bound: this asserts pacing happened, not that the
        // host scheduler is realtime.
        self::assertLessThan($expected + 0.5, $elapsed);
    }

    public function test_roach_scheduler_truncates_sub_second_delay_to_zero(): void
    {
        // Documents the ceiling being worked around. If a roach upgrade
        // ever makes this fail, SubSecondRequestScheduler can be deleted.
        $scheduler = new ArrayRequestScheduler(new SystemClock());
        $scheduler->setDelay((int) 0.2);

        for ($i = 0; $i < 5; $i++) {
            $scheduler->schedule(self::request("https://example.test/{$i}"));
        }

        $started = microtime(true);
        for ($i = 0; $i < 5; $i++) {
            $scheduler->nextRequests(1);
        }

        self::assertLessThan(0.05, microtime(true) - $started);
    }

    public function test_spider_int_does_not_clobber_configured_float(): void
    {
        $scheduler = new SubSecondRequestScheduler(new SubSecondClock());
        $scheduler->setDelaySeconds(0.2);

        // Roach's Engine calls setDelay() with the spider's int property.
        $scheduler->setDelay(1);

        self::assertSame(0.2, $scheduler->delaySeconds());
    }

    public function test_falls_back_to_int_delay_when_no_float_configured(): void
    {
        $scheduler = new SubSecondRequestScheduler(new SubSecondClock());
        $scheduler->setDelay(2);

        self::assertSame(2.0, $scheduler->delaySeconds());
    }

    private static function request(string $url): Request
    {
        return new Request('GET', $url, static fn (Response $r): \Generator => yield from []);
    }
}
