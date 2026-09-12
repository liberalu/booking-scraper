<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Repositories\CrawlerQueueRepository;
use App\Runs\ResumePolicy;
use App\Support\Database;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

final class ScanQueueTest extends TestCase
{
    private static bool $booted = false;

    private int $shopId;

    private int $runId;

    private CrawlerQueueRepository $queue;

    protected function setUp(): void
    {
        if (! self::$booted) {
            Database::boot(getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');
            self::$booted = true;
        }
        DB::beginTransaction();

        $this->queue = new CrawlerQueueRepository;
        $this->shopId = DB::table('shops')->insertGetId([
            'name' => 'queue-test',
            'base_url' => 'https://queue.test',
        ], 'id');
        $this->runId = DB::table('scrape_runs')->insertGetId([
            'shop_id' => $this->shopId,
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
        DB::table('discovered_urls')->insert([
            'shop_id' => $this->shopId,
            'url' => 'https://queue.test/known',
            'normalized_url' => 'https://queue.test/known',
            'url_type' => 'unknown',
            'source' => 'sitemap',
            'fail_count' => 0,
            'first_seen_at' => Date::now('UTC'),
            'last_seen_at' => Date::now('UTC'),
        ]);
    }

    protected function tearDown(): void
    {
        DB::rollBack();
    }

    public function test_enqueue_creates_pending_rows_linked_to_discovered_urls_once(): void
    {
        $urls = ['https://queue.test/known', 'https://queue.test/explicit'];

        self::assertSame(2, $this->queue->enqueue($this->runId, $this->shopId, $urls));
        self::assertSame(0, $this->queue->enqueue($this->runId, $this->shopId, $urls), 'idempotent on (run, url)');

        $rows = DB::table('scrape_url_items')->where('run_id', $this->runId)->orderBy('id')->get();
        self::assertCount(2, $rows);
        self::assertSame('pending', $rows[0]->status);
        self::assertSame('unknown', $rows[0]->url_type);
        self::assertNotNull($rows[0]->discovered_url_id, 'a discovered URL is linked to its queue row');
        self::assertNull($rows[1]->discovered_url_id, 'an explicit URL has no discovered row to link');
        self::assertSame('product', $rows[1]->url_type);
        self::assertSame($urls, $this->queue->pendingRunUrls($this->runId));
    }

    public function test_claiming_marks_rows_processing_and_counts_the_attempt(): void
    {
        $this->queue->enqueue($this->runId, $this->shopId, ['https://queue.test/a', 'https://queue.test/b']);

        self::assertSame(1, $this->queue->claim($this->runId, ['https://queue.test/a']));

        $row = DB::table('scrape_url_items')->where('url', 'https://queue.test/a')->first();
        self::assertSame('processing', $row->status);
        self::assertSame(1, $row->attempts);
        self::assertNotNull($row->claimed_at);
        self::assertSame(['https://queue.test/b'], $this->queue->pendingRunUrls($this->runId));
    }

    public function test_a_fetched_url_is_done_and_cannot_be_reopened(): void
    {
        $this->queue->enqueue($this->runId, $this->shopId, ['https://queue.test/a']);
        $this->queue->claim($this->runId, ['https://queue.test/a']);

        self::assertTrue($this->queue->markDone($this->runId, 'https://queue.test/a', 200, 4096));
        self::assertFalse($this->queue->markDone($this->runId, 'https://queue.test/a', 200, 4096));

        $row = DB::table('scrape_url_items')->where('url', 'https://queue.test/a')->first();
        self::assertSame('done', $row->status);
        self::assertSame(200, $row->http_status);
        self::assertSame(4096, $row->response_bytes);
        self::assertNotNull($row->done_at);
    }

    public function test_a_failed_url_records_a_scrape_failure_event(): void
    {
        $this->queue->enqueue($this->runId, $this->shopId, ['https://queue.test/known']);
        $this->queue->claim($this->runId, ['https://queue.test/known']);

        self::assertTrue($this->queue->markFailed($this->runId, 'https://queue.test/known', 'http_404', 404, 'HTTP 404'));

        $row = DB::table('scrape_url_items')->where('url', 'https://queue.test/known')->first();
        self::assertSame('failed', $row->status);
        self::assertSame(404, $row->http_status);

        $failure = DB::table('scrape_failures')->where('run_id', $this->runId)->first();
        self::assertNotNull($failure);
        self::assertSame($row->id, $failure->scrape_url_item_id);
        self::assertSame($row->discovered_url_id, $failure->discovered_url_id);
        self::assertSame('http_404', $failure->error_reason);
        self::assertSame(404, $failure->http_status);
        self::assertSame('new', $failure->lifecycle_state);
    }

    public function test_a_persist_error_after_a_successful_fetch_still_fails_the_row(): void
    {
        $this->queue->enqueue($this->runId, $this->shopId, ['https://queue.test/a']);
        $this->queue->markDone($this->runId, 'https://queue.test/a', 200, 10);

        self::assertTrue($this->queue->markFailed($this->runId, 'https://queue.test/a', 'persist_error', null, 'boom'));
        self::assertSame('failed', DB::table('scrape_url_items')->where('url', 'https://queue.test/a')->value('status'));
    }

    public function test_an_aborted_row_is_not_resurrected_by_a_late_response(): void
    {
        $this->queue->enqueue($this->runId, $this->shopId, ['https://queue.test/a']);
        DB::table('scrape_url_items')->where('run_id', $this->runId)->update(['status' => 'failed']);

        self::assertFalse($this->queue->markDone($this->runId, 'https://queue.test/a', 200, 10));
        self::assertFalse($this->queue->markFailed($this->runId, 'https://queue.test/a', 'http_500', 500));
        self::assertSame(0, DB::table('scrape_failures')->where('run_id', $this->runId)->count());
    }

    public function test_a_stalled_run_with_pending_rows_is_what_the_watchdog_resumes(): void
    {
        $this->queue->enqueue($this->runId, $this->shopId, ['https://queue.test/a', 'https://queue.test/b']);
        $this->queue->markDone($this->runId, 'https://queue.test/a', 200, 10);
        DB::table('scrape_runs')->where('id', $this->runId)->update([
            'status' => 'failed',
            'close_reason' => 'stall_timeout',
            'resumable_after_failure' => true,
        ]);

        $policy = new ResumePolicy(3);
        self::assertSame($this->runId, $policy->findResumable($this->shopId, 'scan')?->id);
        self::assertSame($this->runId, $policy->findResumableById($this->runId, $this->shopId, 'scan')?->id);

        $this->queue->markDone($this->runId, 'https://queue.test/b', 200, 10);
        self::assertNull($policy->findResumable($this->shopId, 'scan'), 'nothing pending, nothing to resume');
    }
}
