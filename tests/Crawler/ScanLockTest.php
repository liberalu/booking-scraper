<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Runs\ScanLock;
use App\Support\Database;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

final class ScanLockTest extends TestCase
{
    private static bool $booted = false;

    protected function setUp(): void
    {
        if (! self::$booted) {
            Database::boot(
                getenv('TEST_DATABASE_URL')
                    ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test'
            );
            self::$booted = true;
        }
    }

    protected function tearDown(): void
    {

        while (DB::selectOne('select pg_advisory_unlock(?, ?) as r', [4242, (new ScanLock)->key()])->r) {
        }
    }

    public function test_the_key_is_stable_for_a_phase(): void
    {

        self::assertGreaterThan(0, (new ScanLock)->key());
        self::assertSame((new ScanLock)->key(), (new ScanLock)->key());
    }

    public function test_all_crawl_phases_share_one_shop_lock_key(): void
    {

        self::assertSame((new ScanLock)->key(), (new ScanLock)->key());
    }

    public function test_the_key_stays_inside_postgres_int4(): void
    {

        $key = (new ScanLock)->key();
        self::assertGreaterThanOrEqual(0, $key);
        self::assertLessThanOrEqual(0x7FFFFFFF, $key);
    }

    public function test_acquire_then_release_round_trips(): void
    {
        self::assertTrue((new ScanLock)->tryAcquireForSession(4242));
        self::assertTrue((new ScanLock)->release(4242));
    }

    public function test_releasing_a_lock_we_never_held_reports_false(): void
    {
        self::assertFalse((new ScanLock)->release(4242));
    }

    public function test_a_second_process_is_refused(): void
    {

        self::assertTrue((new ScanLock)->tryAcquireForSession(4242));

        $script = sprintf(
            '<?php require %s; App\\Support\\Database::boot(%s); '
            .'var_export((new App\\Runs\\ScanLock)->tryAcquireForSession(4242));',
            var_export(dirname(__DIR__, 2).'/vendor/autoload.php', true),
            var_export(
                getenv('TEST_DATABASE_URL')
                    ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test',
                true
            )
        );
        $file = tempnam(sys_get_temp_dir(), 'locktest').'.php';
        file_put_contents($file, $script);
        $output = (string) shell_exec(escapeshellarg(PHP_BINARY).' '.escapeshellarg($file));
        @unlink($file);

        self::assertStringContainsString('false', $output, 'a second process acquired the lock');

        (new ScanLock)->release(4242);
    }
}
