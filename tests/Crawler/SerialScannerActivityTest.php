<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Crawler\Persister;
use App\Crawler\SerialScanner;
use App\Crawler\Watchdog;
use App\Support\Config;
use PHPUnit\Framework\TestCase;

final class SerialScannerActivityTest extends TestCase
{
    private string $configDir = '';

    protected function setUp(): void
    {
        parent::setUp();

        $this->configDir = sys_get_temp_dir().'/serial-activity-'.getmypid();
        @mkdir($this->configDir.'/shops', 0777, true);
        file_put_contents($this->configDir.'/default.toml', <<<'TOML'
            [scraping]
            download_delay = 0.0
            concurrent_requests_per_domain = 1
            TOML);
        file_put_contents($this->configDir.'/shops/humanitas.toml', <<<'TOML'
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
            @unlink($this->configDir.$f);
        }
        @rmdir($this->configDir.'/shops');
        @rmdir($this->configDir);
        parent::tearDown();
    }

    public function test_a_failed_fetch_records_activity(): void
    {
        $marker = sys_get_temp_dir().'/serial-activity-marker-'.getmypid();
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
            new Persister,
            shopId: 1,
            runId: null,
            watchdog: $watchdog,
        ))->run(['https://www.humanitas.lt/produktas/a-book']);

        self::assertSame(1, $tally['failed'], 'the fetch was expected to fail');
        self::assertFileExists(
            $marker,
            'a failed fetch recorded no activity — two consecutive timeouts on a '
            .'serial shop will fail a healthy run'
        );

        @unlink($marker);
    }

    public function test_every_failed_url_keeps_the_marker_fresh(): void
    {

        $marker = sys_get_temp_dir().'/serial-activity-many-'.getmypid();
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
            new Persister,
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
