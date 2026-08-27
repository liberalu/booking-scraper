<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Support\Database;
use App\Runs\ScanLock;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

/**
 * The lock that stops two crawls fetching the same URLs.
 *
 * Python originally derived the key with `abs(hash(phase))`, which CPython
 * randomises per process unless PYTHONHASHSEED is set — so two processes
 * computed different keys and both "acquired" it. It now uses `zlib.crc32`,
 * identical to the key pinned here. These tests pin that key and the
 * exclusion it buys.
 */
final class ScanLockTest extends TestCase
{
    private static bool $booted = false;

    protected function setUp(): void
    {
        if (!self::$booted) {
            Database::boot(
                getenv('TEST_DATABASE_URL')
                    ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test'
            );
            self::$booted = true;
        }
    }

    protected function tearDown(): void
    {
        // Session locks outlive a transaction, so release explicitly.
        foreach (['scan', 'discover', 'validate'] as $phase) {
            while (DB::selectOne('select pg_advisory_unlock(?, ?) as r', [4242, ScanLock::key($phase)])->r) {
                // drain nested acquisitions
            }
        }
    }

    public function test_the_key_is_stable_for_a_phase(): void
    {
        // The whole point: another process must compute the same number.
        self::assertSame(crc32('scan') & 0x7FFFFFFF, ScanLock::key('scan'));
        self::assertSame(ScanLock::key('scan'), ScanLock::key('scan'));
    }

    public function test_different_phases_get_different_keys(): void
    {
        // discover and scan for one shop must be able to run together.
        self::assertNotSame(ScanLock::key('scan'), ScanLock::key('discover'));
    }

    public function test_the_key_stays_inside_postgres_int4(): void
    {
        // pg_advisory_lock takes int4; an out-of-range key would error.
        foreach (['scan', 'discover', 'validate', 'match', 'discover_lupasearch'] as $phase) {
            $key = ScanLock::key($phase);
            self::assertGreaterThanOrEqual(0, $key);
            self::assertLessThanOrEqual(0x7FFFFFFF, $key);
        }
    }

    public function test_acquire_then_release_round_trips(): void
    {
        self::assertTrue(ScanLock::tryAcquireForSession(4242, 'scan'));
        self::assertTrue(ScanLock::release(4242, 'scan'));
    }

    public function test_releasing_a_lock_we_never_held_reports_false(): void
    {
        self::assertFalse(ScanLock::release(4242, 'validate'));
    }

    public function test_a_second_process_is_refused(): void
    {
        // The behaviour Python's randomised key silently loses. Uses a real
        // second process, because within one session Postgres grants the
        // lock again to its existing holder.
        self::assertTrue(ScanLock::tryAcquireForSession(4242, 'discover'));

        $script = sprintf(
            '<?php require %s; App\\Support\\Database::boot(%s); '
            . 'var_export(App\\Runs\\ScanLock::tryAcquireForSession(4242, "discover"));',
            var_export(dirname(__DIR__, 2) . '/vendor/autoload.php', true),
            var_export(
                getenv('TEST_DATABASE_URL')
                    ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test',
                true
            )
        );
        $file = tempnam(sys_get_temp_dir(), 'locktest') . '.php';
        file_put_contents($file, $script);
        $output = (string) shell_exec(escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg($file));
        @unlink($file);

        self::assertStringContainsString('false', $output, 'a second process acquired the lock');

        ScanLock::release(4242, 'discover');
    }
}
