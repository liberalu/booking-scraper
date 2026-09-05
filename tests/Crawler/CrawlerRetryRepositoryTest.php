<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Repositories\CrawlerRetryRepository;
use App\Runs\RunEvent;
use App\Support\Database;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

final class CrawlerRetryRepositoryTest extends TestCase
{
    private static bool $booted = false;

    protected function setUp(): void
    {
        if (! self::$booted) {
            Database::boot(getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');
            self::$booted = true;
        }
        DB::beginTransaction();
    }

    protected function tearDown(): void
    {
        DB::rollBack();
    }

    public function test_a_transport_retry_updates_the_queue_and_timeline(): void
    {
        $shopId = DB::table('shops')->insertGetId([
            'name' => 'retry-observability-test',
            'base_url' => 'https://retry.test',
        ], 'id');
        $runId = DB::table('scrape_runs')->insertGetId([
            'shop_id' => $shopId,
            'phase' => 'scan',
            'status' => 'running',
            'started_at' => Date::now('UTC'),
            'urls_processed' => 0,
            'items_added' => 0,
            'items_updated' => 0,
            'errors_4xx' => 0,
            'errors_5xx' => 0,
            'error_count' => 0,
        ], 'id');
        $url = 'https://retry.test/book';
        $itemId = DB::table('scrape_url_items')->insertGetId([
            'run_id' => $runId,
            'shop_id' => $shopId,
            'url' => $url,
            'status' => 'pending',
            'created_at' => Date::now('UTC'),
        ], 'id');

        (new CrawlerRetryRepository)->record($runId, $url, 1, 503, null);

        self::assertSame(
            1,
            DB::table('scrape_url_items')->where('id', $itemId)->value('retry_count'),
        );
        $event = DB::table('scrape_run_events')
            ->where('run_id', $runId)
            ->where('event_type', RunEvent::REQUEST_RETRIED)
            ->first();
        self::assertNotNull($event);
        self::assertSame(503, json_decode((string) $event->payload, true)['http_status']);
    }
}
