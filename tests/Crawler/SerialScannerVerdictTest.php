<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Crawler\FlareSolverr;
use App\Crawler\Persister;
use App\Crawler\SerialScanner;
use App\Support\Config;
use App\Support\Database;
use GuzzleHttp\Client;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Psr7\Response;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

final class SerialScannerVerdictTest extends TestCase
{
    private static bool $booted = false;

    private string $configDir = '';

    protected function setUp(): void
    {
        if (! self::$booted) {
            Database::boot(getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');
            self::$booted = true;
        }
        DB::beginTransaction();

        $this->configDir = sys_get_temp_dir().'/serial-verdict-'.getmypid();
        @mkdir($this->configDir.'/shops', 0777, true);
        file_put_contents($this->configDir.'/default.toml', "[scraping]\ndownload_delay = 0.0\n");
        file_put_contents($this->configDir.'/shops/humanitas.toml', <<<'TOML'
            [shop]
            base_url = "https://www.humanitas.lt"

            [flaresolverr]
            endpoint = "http://flaresolverr.test/v1"
            TOML);
    }

    protected function tearDown(): void
    {
        DB::rollBack();
        @unlink($this->configDir.'/shops/humanitas.toml');
        @unlink($this->configDir.'/default.toml');
        @rmdir($this->configDir.'/shops');
        @rmdir($this->configDir);
    }

    public function test_a_page_the_classifier_rejects_is_recorded_as_a_non_product(): void
    {
        $shopId = DB::table('shops')->insertGetId(['name' => 'serial-verdict', 'base_url' => 'https://www.humanitas.lt'], 'id');
        $url = 'https://www.humanitas.lt/produktas/nuodingieji-augalai';
        DB::table('discovered_urls')->insert([
            'shop_id' => $shopId,
            'url' => $url,
            'normalized_url' => $url,
            'url_type' => 'unknown',
            'source' => 'sitemap',
            'fail_count' => 0,
            'first_seen_at' => Date::now('UTC'),
            'last_seen_at' => Date::now('UTC'),
        ]);
        $body = (string) file_get_contents(__DIR__.'/../fixtures/humanitas/product_without_book_info.html');

        $tally = (new SerialScanner(
            'humanitas',
            Config::forShop('humanitas', $this->configDir),
            new Persister,
            $shopId,
            null,
            flareSolverr: $this->flareSolverrServing($body),
        ))->run([$url]);

        self::assertSame(1, $tally['non_product']);
        self::assertSame(0, $tally['failed']);

        $row = DB::table('discovered_urls')->where('shop_id', $shopId)->where('url', $url)->first();
        self::assertSame('non_product', $row->url_type, 'the URL keeps being refetched through FlareSolverr until it is classified');
        $classification = DB::table('url_classifications')->where('discovered_url_id', $row->id)->first();
        self::assertNotNull($classification);
        self::assertFalse((bool) $classification->is_book_product);
        self::assertStringContainsString('book_categories', (string) $classification->reasons);
    }

    public function test_a_blank_page_is_a_non_product_not_a_failed_fetch(): void
    {
        $shopId = DB::table('shops')->insertGetId(['name' => 'serial-verdict', 'base_url' => 'https://www.humanitas.lt'], 'id');

        $tally = (new SerialScanner(
            'humanitas',
            Config::forShop('humanitas', $this->configDir),
            new Persister,
            $shopId,
            null,
            flareSolverr: $this->flareSolverrServing('<html><body><div class="book-info"></div></body></html>'),
        ))->run(['https://www.humanitas.lt/produktas/untitled']);

        self::assertSame(1, $tally['non_product']);
        self::assertSame(0, $tally['failed'], 'a page that parsed but is not a book used to be counted as a failure');
    }

    private function flareSolverrServing(string $html): FlareSolverr
    {
        $mock = new MockHandler([
            new Response(200, [], json_encode(['status' => 'ok', 'session' => 'test-session'], JSON_THROW_ON_ERROR)),
            new Response(200, [], json_encode([
                'status' => 'ok',
                'solution' => ['status' => 200, 'response' => $html, 'url' => 'https://www.humanitas.lt/x', 'headers' => []],
            ], JSON_THROW_ON_ERROR)),
            new Response(200, [], json_encode(['status' => 'ok'], JSON_THROW_ON_ERROR)),
        ]);

        return new FlareSolverr(
            'http://flaresolverr.test/v1',
            1000,
            1,
            new Client(['handler' => HandlerStack::create($mock)]),
        );
    }
}
