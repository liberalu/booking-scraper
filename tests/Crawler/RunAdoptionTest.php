<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Crawler\RunLifecycle;
use App\Runs\ResumePolicy;
use App\Runs\RunEvent;
use App\Runs\RunFailsafe;
use App\Runs\RunReconciler;
use App\Support\Database;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

final class RunAdoptionTest extends TestCase
{
    private static bool $booted = false;

    private int $shopId;

    protected function setUp(): void
    {
        if (! self::$booted) {
            Database::boot($this->dsn());
            self::$booted = true;
        }
        DB::beginTransaction();

        $this->shopId = (int) (DB::table('shops')->where('name', 'adopt-test')->value('id')
            ?? DB::table('shops')->insertGetId(
                ['name' => 'adopt-test', 'base_url' => 'https://adopt.test'],
                'id'
            ));
    }

    protected function tearDown(): void
    {
        DB::rollBack();
    }

    private function dsn(): string
    {
        return getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test';
    }

    private function stalledRun(int $processed = 5): int
    {
        $runId = DB::table('scrape_runs')->insertGetId([
            'shop_id' => $this->shopId,
            'phase' => 'scan',
            'status' => 'failed',
            'started_at' => Date::now('UTC')->subMinutes(10),
            'finished_at' => Date::now('UTC')->subMinutes(1),
            'close_reason' => 'stall_timeout',
            'resumable_after_failure' => true,
            'urls_total' => 10,
            'urls_processed' => $processed,
            'items_added' => 0,
            'items_updated' => 0,
            'errors_4xx' => 0,
            'errors_5xx' => 0,
            'error_count' => 0,
        ], 'id');

        foreach (['done', 'pending', 'pending'] as $i => $status) {
            DB::table('scrape_url_items')->insert([
                'run_id' => $runId,
                'shop_id' => $this->shopId,
                'url' => "https://adopt.test/item-{$i}",
                'url_type' => 'product',
                'status' => $status,
                'created_at' => Date::now('UTC'),
            ]);
        }

        return $runId;
    }

    public function test_adopting_reopens_the_same_row(): void
    {
        $runId = $this->stalledRun();

        $lifecycle = RunLifecycle::adopt($runId);

        self::assertSame($runId, $lifecycle->id());
        $row = DB::table('scrape_runs')->where('id', $runId)->first();
        self::assertSame('running', $row->status);
        self::assertNull($row->finished_at);
        self::assertNotNull($row->last_heartbeat);
    }

    public function test_adopting_clears_the_resumable_flag(): void
    {

        $runId = $this->stalledRun();

        RunLifecycle::adopt($runId);

        self::assertFalse(
            (bool) DB::table('scrape_runs')->where('id', $runId)->value('resumable_after_failure')
        );
    }

    public function test_the_pending_queue_survives_adoption(): void
    {
        $runId = $this->stalledRun();

        RunLifecycle::adopt($runId);

        $counts = DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->selectRaw('status, count(*) as c')
            ->groupBy('status')
            ->pluck('c', 'status')
            ->all();

        self::assertSame(2, (int) $counts['pending'], 'pending work must be preserved');
        self::assertSame(1, (int) $counts['done'], 'completed work must not be redone');
    }

    public function test_restart_events_accumulate_on_the_one_row(): void
    {
        $runId = $this->stalledRun();

        foreach ([5, 12, 30] as $snapshot) {
            (new RunFailsafe)->recordEvent($runId, RunEvent::RESTARTED, [
                'reason' => 'stall_timeout',
                'urls_processed_snapshot' => $snapshot,
            ]);
            RunLifecycle::adopt($runId);
        }

        self::assertSame(3, (new ResumePolicy(0))->chainDepth($runId));
        self::assertFalse((new ResumePolicy(3))->evaluate($runId)['allowed']);
    }

    public function test_a_stalled_run_is_discoverable_for_adoption(): void
    {
        $runId = $this->stalledRun();

        self::assertSame($runId, (new ResumePolicy(0))->findResumable($this->shopId, 'scan')?->id);
    }

    public function test_an_operator_can_resolve_the_exact_run_selected(): void
    {
        $older = $this->stalledRun();
        $newer = $this->stalledRun();

        self::assertSame(
            $older,
            (new ResumePolicy(0))->findResumableById($older, $this->shopId, 'scan')?->id,
        );
        self::assertSame(
            $newer,
            (new ResumePolicy(0))->findResumableById($newer, $this->shopId, 'scan')?->id,
        );
        self::assertNull((new ResumePolicy(0))->findResumableById($older, $this->shopId, 'validate'));
    }

    public function test_an_adopted_run_is_no_longer_offered_for_adoption(): void
    {

        $runId = $this->stalledRun();
        RunLifecycle::adopt($runId);

        $found = (new ResumePolicy(0))->findResumable($this->shopId, 'scan');
        self::assertSame($runId, $found?->id);
        self::assertSame('running', $found?->status);
        self::assertFalse($found?->resumableAfterFailure);
    }

    public function test_adoption_releases_items_stuck_in_processing(): void
    {

        $runId = $this->stalledRun();
        DB::table('scrape_url_items')->insert([
            'run_id' => $runId,
            'shop_id' => $this->shopId,
            'url' => 'https://adopt.test/in-flight',
            'url_type' => 'product',
            'status' => 'processing',
            'created_at' => Date::now('UTC'),
            'claimed_at' => Date::now('UTC')->subMinutes(5),
        ]);

        RunLifecycle::adopt($runId);

        $row = DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('url', 'https://adopt.test/in-flight')
            ->first();
        self::assertSame('pending', $row->status);
        self::assertNull($row->claimed_at);
    }

    public function test_adoption_retries_transient_failures(): void
    {
        $runId = $this->stalledRun();
        $itemId = $this->failedItem($runId, 'run_aborted', attempts: 1);

        RunLifecycle::adopt($runId);

        self::assertSame(
            'pending',
            DB::table('scrape_url_items')->where('id', $itemId)->value('status')
        );
    }

    public function test_adoption_leaves_a_permanent_failure_alone(): void
    {
        $runId = $this->stalledRun();
        $itemId = $this->failedItem($runId, 'http_404', attempts: 1);

        RunLifecycle::adopt($runId);

        self::assertSame(
            'failed',
            DB::table('scrape_url_items')->where('id', $itemId)->value('status'),
            'a 404 is not transient — retrying it forever starves the backlog'
        );
    }

    public function test_a_failure_at_the_retry_cap_stays_failed(): void
    {

        $runId = $this->stalledRun();
        $itemId = $this->failedItem($runId, 'run_aborted', attempts: RunReconciler::RETRY_CAP);

        RunLifecycle::adopt($runId);

        self::assertSame(
            'failed',
            DB::table('scrape_url_items')->where('id', $itemId)->value('status')
        );
    }

    private function failedItem(int $runId, string $reason, int $attempts): int
    {
        $itemId = DB::table('scrape_url_items')->insertGetId([
            'run_id' => $runId,
            'shop_id' => $this->shopId,
            'url' => "https://adopt.test/failed-{$reason}-{$attempts}",
            'url_type' => 'product',
            'status' => 'failed',
            'attempts' => $attempts,
            'created_at' => Date::now('UTC'),
            'done_at' => Date::now('UTC'),
        ], 'id');

        DB::table('scrape_failures')->insert([
            'run_id' => $runId,
            'shop_id' => $this->shopId,
            'scrape_url_item_id' => $itemId,
            'url' => "https://adopt.test/failed-{$reason}-{$attempts}",
            'error_reason' => $reason,
            'occurred_at' => Date::now('UTC'),
            'lifecycle_state' => 'new',
        ]);

        return $itemId;
    }
}
