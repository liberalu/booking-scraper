<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Crawler\Watchdog;
use App\Runs\RunEvent;
use App\Support\Database;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Sleep;
use PHPUnit\Framework\TestCase;
use Tests\Support\RecordingLauncher;

final class WatchdogTest extends TestCase
{
    private static bool $booted = false;

    private int $shopId;

    protected function setUp(): void
    {
        if (! function_exists('pcntl_fork')) {
            self::markTestSkipped('pcntl unavailable');
        }
        if (! self::$booted) {
            Database::boot($this->dsn());
            self::$booted = true;
        }

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

    private function dsn(): string
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
            'started_at' => Date::now('UTC'),

            'last_heartbeat' => Date::now('UTC')->subHour(),
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
            stallTimeout: 3600,
            heartbeatInterval: 0.5,
        );
        self::assertTrue($watchdog->start());

        Sleep::usleep(1_500_000);

        $watchdog->stop();

        self::assertNotSame($before, $this->heartbeat($runId), 'heartbeat never advanced');
    }

    public function test_a_stall_fails_the_run_and_marks_it_resumable(): void
    {
        $runId = $this->makeRun();

        $signalled = false;
        pcntl_signal(SIGTERM, static function () use (&$signalled): void {
            $signalled = true;
        });

        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'scan',
            stallTimeout: 1,
            heartbeatInterval: 0.4,
            maxResumeAttempts: 0,
        );
        self::assertTrue($watchdog->start());

        for ($i = 0; $i < 25; $i++) {
            Sleep::usleep(100_000);
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

        for ($i = 0; $i < 8; $i++) {
            $watchdog->recordActivity();
            Sleep::usleep(300_000);
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

        $runId = $this->makeRun('failed');

        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'scan',
            stallTimeout: 3600,
            heartbeatInterval: 0.3,
        );
        $watchdog->start();
        Sleep::usleep(900_000);
        $before = $this->heartbeat($runId);
        Sleep::usleep(900_000);
        $watchdog->stop();

        self::assertSame($before, $this->heartbeat($runId), 'kept ticking a terminal run');
    }

    public function test_the_child_leaves_the_parent_connection_and_lock_intact(): void
    {
        $runId = $this->makeRun();
        $backendBefore = DB::selectOne('select pg_backend_pid() as pid')->pid;
        self::assertTrue((bool) DB::selectOne('select pg_try_advisory_lock(424242, 1) as locked')->locked);

        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'scan',
            stallTimeout: 3600,
            heartbeatInterval: 0.3,
        );
        self::assertTrue($watchdog->start());
        Sleep::usleep(700_000);
        $watchdog->stop();

        self::assertSame(
            $backendBefore,
            DB::selectOne('select pg_backend_pid() as pid')->pid,
            'the child closed the connection it shared with the parent',
        );
        self::assertTrue(
            (bool) DB::selectOne('select pg_advisory_unlock(424242, 1) as released')->released,
            'the session lock was lost with the connection',
        );
    }

    public function test_a_stalled_scan_is_restarted_by_adopting_its_own_queue(): void
    {
        $runId = $this->makeRun();
        $record = tempnam(sys_get_temp_dir(), 'watchdog-spawn-');
        self::assertIsString($record);
        pcntl_signal(SIGTERM, static function (): void {});

        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'scan',
            stallTimeout: 1,
            heartbeatInterval: 0.4,
            maxResumeAttempts: 3,
            launcher: new RecordingLauncher($record),
        );
        self::assertTrue($watchdog->start());
        for ($i = 0; $i < 25; $i++) {
            Sleep::usleep(100_000);
            pcntl_signal_dispatch();
        }
        $watchdog->stop();
        pcntl_signal(SIGTERM, SIG_DFL);

        $spawned = json_decode((string) file_get_contents($record), true);
        @unlink($record);
        self::assertSame([
            'phase' => 'scan',
            'shop' => 'watchdog-test',
            'strategy' => '',
            'role' => 'stall-resume',
            'adoptRunId' => $runId,
        ], $spawned);
        self::assertSame(
            1,
            DB::table('scrape_run_events')->where('run_id', $runId)->where('event_type', RunEvent::RESTARTED)->count(),
        );
    }

    public function test_a_stalled_discover_is_restarted_with_its_strategy(): void
    {
        $runId = $this->makeRun();
        $record = tempnam(sys_get_temp_dir(), 'watchdog-spawn-');
        self::assertIsString($record);
        pcntl_signal(SIGTERM, static function (): void {});

        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'discover',
            stallTimeout: 1,
            heartbeatInterval: 0.4,
            maxResumeAttempts: 3,
            strategy: 'categories',
            launcher: new RecordingLauncher($record),
        );
        self::assertTrue($watchdog->start());
        for ($i = 0; $i < 25; $i++) {
            Sleep::usleep(100_000);
            pcntl_signal_dispatch();
        }
        $watchdog->stop();
        pcntl_signal(SIGTERM, SIG_DFL);

        $spawned = json_decode((string) file_get_contents($record), true);
        @unlink($record);
        self::assertSame('discover', $spawned['phase'] ?? null);
        self::assertSame('categories', $spawned['strategy'] ?? null);
        self::assertNull($spawned['adoptRunId'] ?? null);
    }

    public function test_a_child_that_cannot_connect_is_reported_not_assumed(): void
    {
        $runId = $this->makeRun();
        $watchdog = new Watchdog(
            runId: $runId,
            shop: 'watchdog-test',
            phase: 'scan',
            stallTimeout: 3600,
            heartbeatInterval: 0.3,
            dsn: 'postgresql://postgres:postgres@127.0.0.1:1/nowhere',
        );

        self::assertFalse($watchdog->start(), 'a child without a database cannot heartbeat, so the run is unsupervised');

        $watchdog->stop();
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
