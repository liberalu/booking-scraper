<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Crawler\RunLifecycle;
use App\Runs\ScanLock;
use App\Support\Database;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

final class RunLifecycleTest extends TestCase
{
    private static bool $booted = false;

    private int $shopId;

    protected function setUp(): void
    {
        if (! self::$booted) {
            Database::boot(getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');
            self::$booted = true;
        }
        DB::beginTransaction();
        $this->shopId = DB::table('shops')->insertGetId(['name' => 'lifecycle-test', 'base_url' => 'https://lifecycle.test'], 'id');
    }

    protected function tearDown(): void
    {
        DB::rollBack();
        $lock = new ScanLock;
        $lock->release($this->shopId);
        $lock->release($this->shopId, postPhase: true);
    }

    public function test_the_cron_job_is_stamped_when_the_run_boots_not_when_it_ends(): void
    {
        $jobId = DB::table('cron_jobs')->insertGetId([
            'shop_id' => $this->shopId,
            'phase' => 'scan',
            'strategy' => null,
            'args' => '',
            'cron_expression' => '0 2 * * *',
            'enabled' => true,
            'created_at' => DB::raw('now()'),
        ], 'id');

        $lifecycle = new RunLifecycle($this->shopId, 'scan');
        $lifecycle->start(5);

        self::assertNotNull(
            DB::table('cron_jobs')->where('id', $jobId)->value('last_run_at'),
            'a run that dies before finishing must still count as fired, or the scheduler re-fires it every tick',
        );

        $lifecycle->finish();
    }

    public function test_a_validate_run_does_not_hold_the_crawl_lock(): void
    {
        $lifecycle = new RunLifecycle($this->shopId, 'validate');
        $lifecycle->start();

        $lock = new ScanLock;
        self::assertSame(0, $this->advisoryLocks($lock->key()), 'validate must not keep a scheduled scan from starting');
        self::assertSame(1, $this->advisoryLocks($lock->key(postPhase: true)), 'but two validates still serialise');

        $lifecycle->finish();
        self::assertSame(0, $this->advisoryLocks($lock->key(postPhase: true)));
    }

    public function test_a_scan_holds_the_crawl_lock_until_it_finishes(): void
    {
        $lifecycle = new RunLifecycle($this->shopId, 'scan');
        $lifecycle->start(1);

        self::assertSame(1, $this->advisoryLocks((new ScanLock)->key()));

        $lifecycle->finish();
        self::assertSame(0, $this->advisoryLocks((new ScanLock)->key()));
    }

    private function advisoryLocks(int $key): int
    {
        return (int) DB::table('pg_locks')
            ->where('locktype', 'advisory')
            ->where('classid', $this->shopId)
            ->where('objid', $key)
            ->where('pid', DB::raw('pg_backend_pid()'))
            ->count();
    }
}
