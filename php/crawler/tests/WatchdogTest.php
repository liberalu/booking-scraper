<?php

declare(strict_types=1);

namespace BookScraper\Crawler\Tests;

use BookScraper\Crawler\Watchdog;
use BookScraper\Database;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

/**
 * Exercises the watchdog by actually forking it — a mocked timer would
 * prove nothing about the part that matters, which is that a SEPARATE
 * process keeps the heartbeat alive while the parent is blocked.
 *
 * Intervals are compressed to keep the suite quick; the logic is unchanged.
 */
final class WatchdogTest extends TestCase
{
    private static bool $booted = false;

    private int $shopId;

    protected function setUp(): void
    {
        if (!function_exists('pcntl_fork')) {
            self::markTestSkipped('pcntl unavailable');
        }
        if (!self::$booted) {
            Database::boot(self::dsn());
            self::$booted = true;
        }

        // No wrapping transaction here: the watchdog runs in another process
        // with its own connection and could not see uncommitted rows.
        $this->shopId = (int) (DB::table('shops')->where('name', 'watchdog-test')->value('id')
            ?? DB::table('shops')->insertGetId(
                ['name' => 'watchdog-test', 'base_url' => 'https://watchdog.test'],
                'id'
            ));
    }

    protected function tearDown(): void
    {
        $runIds = DB::table('scrape_runs')->where('shop_id', $this->shopId)->pluck('id');
        DB::table('scrape_run_events')->whereIn('run_id', $runIds)->delete();
        DB::table('scrape_runs')->where('shop_id', $this->shopId)->delete();
    }

    private static function dsn(): string
    {
        return getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test';
    }

    private function makeRun(string $status = 'running'): int
    {
        return DB::table('scrape_runs')->insertGetId([
            'shop_id' => $this->shopId,
            'phase' => 'scan',
            'status' => $status,
            'started_at' => Carbon::now('UTC'),
            // Deliberately stale so a tick is observable as a change.
            'last_heartbeat' => Carbon::now('UTC')->subHour(),
            'urls_processed' => 0,
            'items_added' => 0,
            'items_updated' => 0,
            'errors_4xx' => 0,
            'errors_5xx' => 0,
            'error_count' => 0,
        ], 'id');
    }

    private function heartbeat(int $runId): ?string
    {
        return DB::table('scrape_runs')->where('id', $runId)->value('last_heartbeat');
    }

    public function test_the_heartbeat_ticks_while_the_parent_is_blocked(): void
    {
        $runId = $this->makeRun();
        $before = $this->heartbeat($runId);

        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'scan',
            stallTimeout: 3600,       // no stall during this test
            heartbeatInterval: 0.5,
        );
        self::assertTrue($watchdog->start());

        // Block the parent exactly as a long synchronous fetch would. The
        // in-process Python design needed a worker thread to survive this;
        // a forked child is unaffected.
        usleep(1_500_000);

        $watchdog->stop();

        self::assertNotSame($before, $this->heartbeat($runId), 'heartbeat never advanced');
    }

    public function test_a_stall_fails_the_run_and_marks_it_resumable(): void
    {
        $runId = $this->makeRun();

        // The watchdog SIGTERMs its parent to stop a wedged crawl — here the
        // parent is PHPUnit, so install a handler and observe the signal
        // instead of being killed by it. This asserts the real behaviour.
        $signalled = false;
        pcntl_signal(SIGTERM, static function () use (&$signalled): void {
            $signalled = true;
        });

        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'scan',
            stallTimeout: 1,          // no activity for 1s counts as stalled
            heartbeatInterval: 0.4,
            maxResumeAttempts: 0,     // don't spawn a replacement in a test
        );
        self::assertTrue($watchdog->start());

        // Never call recordActivity(), so the marker goes stale.
        for ($i = 0; $i < 25; $i++) {
            usleep(100_000);
            pcntl_signal_dispatch();
        }
        $watchdog->stop();
        pcntl_signal(SIGTERM, SIG_DFL);

        self::assertTrue($signalled, 'the watchdog must signal the parent to stop crawling');

        $row = DB::table('scrape_runs')->where('id', $runId)->first();
        self::assertSame('failed', $row->status);
        self::assertSame('stall_timeout', $row->close_reason);
        self::assertTrue(
            (bool) $row->resumable_after_failure,
            'the queue still holds valid work — the next run must adopt it'
        );
    }

    public function test_ongoing_activity_prevents_a_stall(): void
    {
        $runId = $this->makeRun();

        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'scan',
            stallTimeout: 1,
            heartbeatInterval: 0.3,
            maxResumeAttempts: 0,
        );
        self::assertTrue($watchdog->start());

        // A crawl that is slow but progressing must not be killed.
        for ($i = 0; $i < 8; $i++) {
            $watchdog->recordActivity();
            usleep(300_000);
        }
        $watchdog->stop();

        self::assertSame(
            'running',
            DB::table('scrape_runs')->where('id', $runId)->value('status'),
            'a progressing crawl was killed'
        );
    }

    public function test_the_watchdog_stops_ticking_once_the_run_is_terminal(): void
    {
        // A tick landing after the reaper finalised the row would make a dead
        // run look alive on the next reaper pass.
        $runId = $this->makeRun('failed');

        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'scan',
            stallTimeout: 3600,
            heartbeatInterval: 0.3,
        );
        $watchdog->start();
        usleep(900_000);
        $before = $this->heartbeat($runId);
        usleep(900_000);
        $watchdog->stop();

        self::assertSame($before, $this->heartbeat($runId), 'kept ticking a terminal run');
    }

    public function test_the_marker_file_is_cleaned_up(): void
    {
        $runId = $this->makeRun();
        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'scan',
            stallTimeout: 3600,
            heartbeatInterval: 0.5,
        );
        $watchdog->start();
        $watchdog->recordActivity();
        self::assertFileExists($watchdog->markerPath());

        $watchdog->stop();

        self::assertFileDoesNotExist($watchdog->markerPath());
    }
}
