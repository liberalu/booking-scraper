<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Support\Config;
use App\Crawler\Persister;
use App\Crawler\SerialScanner;
use App\Crawler\Watchdog;
use PHPUnit\Framework\TestCase;

/**
 * A fetch that fails still counts as activity.
 *
 * The FlareSolverr path is concurrency 1 by construction, and humanitas allows
 * a 240s request timeout against a 480s stall timeout — so two consecutive
 * timeouts were 480 seconds of total silence and the watchdog failed a run that
 * was working exactly as designed. Elsewhere concurrent requests cover for each
 * other; here there is nothing else to hear.
 *
 * The code said so in a comment already; the `continue` in the catch branch
 * skipped the call.
 *
 * No network and no mocks: the config points at a port nothing listens on, so
 * the client throws for real, and the watchdog's activity marker is a file
 * whose mtime this can read. The watchdog is never started, so nothing forks.
 */
final class SerialScannerActivityTest extends TestCase
{
    private string $configDir = '';

    protected function setUp(): void
    {
        parent::setUp();

        // humanitas, because SerialScanner resolves the shop's parser before
        // the loop and only a registered shop resolves — and humanitas is the
        // FlareSolverr shop this guards anyway. Its endpoint here refuses
        // connections: port 1 is privileged and unbound, so the failure is
        // immediate rather than a timeout the test would wait out. The parser
        // is never reached, since nothing is fetched.
        $this->configDir = sys_get_temp_dir() . '/serial-activity-' . getmypid();
        @mkdir($this->configDir . '/shops', 0777, true);
        file_put_contents($this->configDir . '/default.toml', <<<'TOML'
            [scraping]
            download_delay = 0.0
            concurrent_requests_per_domain = 1
            TOML);
        file_put_contents($this->configDir . '/shops/humanitas.toml', <<<'TOML'
            base_url = "https://www.humanitas.lt"

            [flaresolverr]
            endpoint = "http://127.0.0.1:1/v1"
            max_timeout_ms = 1000
            session_ttl_minutes = 1
            TOML);
    }

    protected function tearDown(): void
    {
        foreach (['/shops/humanitas.toml', '/default.toml'] as $f) {
            @unlink($this->configDir . $f);
        }
        @rmdir($this->configDir . '/shops');
        @rmdir($this->configDir);
        parent::tearDown();
    }

    public function test_a_failed_fetch_records_activity(): void
    {
        $marker = sys_get_temp_dir() . '/serial-activity-marker-' . getmypid();
        @unlink($marker);

        $watchdog = new Watchdog(
            runId: 1,
            shop: 'humanitas',
            phase: 'scan',
            stallTimeout: 480.0,
            markerPath: $marker,
        );

        self::assertFileDoesNotExist($marker, 'marker exists before the run');

        $tally = (new SerialScanner(
            'humanitas',
            Config::forShop('humanitas', $this->configDir),
            new Persister(),
            shopId: 1,
            runId: null,
            watchdog: $watchdog,
        ))->run(['https://www.humanitas.lt/produktas/a-book']);

        self::assertSame(1, $tally['failed'], 'the fetch was expected to fail');
        self::assertFileExists(
            $marker,
            'a failed fetch recorded no activity — two consecutive timeouts on a '
            . 'serial shop will fail a healthy run'
        );

        @unlink($marker);
    }

    public function test_every_failed_url_keeps_the_marker_fresh(): void
    {
        // One touch is not enough: the watchdog compares the marker's mtime
        // against now, so activity has to be recorded per URL, not once.
        $marker = sys_get_temp_dir() . '/serial-activity-many-' . getmypid();
        @unlink($marker);

        $watchdog = new Watchdog(
            runId: 2,
            shop: 'humanitas',
            phase: 'scan',
            stallTimeout: 480.0,
            markerPath: $marker,
        );

        $tally = (new SerialScanner(
            'humanitas',
            Config::forShop('humanitas', $this->configDir),
            new Persister(),
            shopId: 1,
            runId: null,
            watchdog: $watchdog,
        ))->run([
            'https://www.humanitas.lt/produktas/one',
            'https://www.humanitas.lt/produktas/two',
            'https://www.humanitas.lt/produktas/three',
        ]);

        self::assertSame(3, $tally['failed']);
        self::assertFileExists($marker);

        @unlink($marker);
    }
}
