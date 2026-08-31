<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Models\Shop;
use App\Runs\ResumePolicy;
use App\Runs\RunEvent;
use App\Runs\RunFailsafe;
use App\Support\Database;
use Illuminate\Database\Capsule\Manager as Capsule;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

final class ResumePolicyTest extends TestCase
{
    private static ?Capsule $capsule = null;

    private int $shopId;

    protected function setUp(): void
    {
        self::$capsule ??= Database::boot(self::dsn());
        DB::beginTransaction();

        $this->shopId = Shop::firstOrCreate(
            ['name' => 'resume-test'],
            ['base_url' => 'https://resume.test']
        )->id;
    }

    protected function tearDown(): void
    {
        DB::rollBack();
    }

    private static function dsn(): string
    {
        return getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test';
    }

    private function makeRun(string $status = 'running', int $processed = 0, bool $resumable = false): int
    {
        return DB::table('scrape_runs')->insertGetId([
            'shop_id' => $this->shopId,
            'phase' => 'scan',
            'status' => $status,
            'started_at' => Carbon::now('UTC'),
            'urls_processed' => $processed,
            'items_added' => 0,
            'items_updated' => 0,
            'errors_4xx' => 0,
            'errors_5xx' => 0,
            'error_count' => 0,
            'resumable_after_failure' => $resumable,
        ], 'id');
    }

    private function restart(int $runId, ?int $snapshot): void
    {
        DB::table('scrape_run_events')->insert([
            'run_id' => $runId,
            'event_type' => RunEvent::RESTARTED,
            'created_at' => Carbon::now('UTC'),
            'actor' => RunEvent::ACTOR_SYSTEM,
            'payload' => json_encode(
                $snapshot === null ? [] : ['urls_processed_snapshot' => $snapshot]
            ),
        ]);
    }

    public function test_a_fresh_run_may_restart(): void
    {
        $verdict = (new ResumePolicy(3))->evaluate($this->makeRun());

        self::assertTrue($verdict['allowed']);
        self::assertSame(1, $verdict['attempt']);
    }

    public function test_restarting_is_capped_by_depth(): void
    {
        $runId = $this->makeRun();

        foreach ([10, 20, 30] as $snapshot) {
            $this->restart($runId, $snapshot);
        }

        $verdict = (new ResumePolicy(3))->evaluate($runId);

        self::assertFalse($verdict['allowed']);
        self::assertStringContainsString('cap reached', $verdict['reason']);
    }

    public function test_progress_between_restarts_keeps_the_chain_alive(): void
    {
        $runId = $this->makeRun();
        $this->restart($runId, 100);
        $this->restart($runId, 250);

        $verdict = (new ResumePolicy(10))->evaluate($runId);

        self::assertTrue($verdict['allowed']);
        self::assertSame(3, $verdict['attempt']);
    }

    public function test_disabled_when_max_attempts_is_zero(): void
    {
        self::assertFalse((new ResumePolicy(0))->evaluate($this->makeRun())['allowed']);
    }

    public function test_two_zero_progress_restarts_break_the_circuit(): void
    {
        $runId = $this->makeRun();

        $this->restart($runId, 0);
        $this->restart($runId, 0);
        $this->restart($runId, 0);

        $verdict = (new ResumePolicy(10))->evaluate($runId);

        self::assertFalse($verdict['allowed'], 'a structural bug must not burn the budget');
        self::assertStringContainsString('structural', $verdict['reason']);
    }

    public function test_the_circuit_breaker_fires_before_the_depth_cap(): void
    {

        $runId = $this->makeRun();
        $this->restart($runId, 5);
        $this->restart($runId, 5);
        $this->restart($runId, 5);

        $verdict = (new ResumePolicy(10))->evaluate($runId);

        self::assertFalse($verdict['allowed']);
        self::assertStringNotContainsString('cap reached', $verdict['reason']);
    }

    public function test_one_zero_progress_restart_is_tolerated(): void
    {
        $runId = $this->makeRun();
        $this->restart($runId, 7);
        $this->restart($runId, 7);

        self::assertSame(1, (new ResumePolicy(0))->consecutiveZeroProgress($runId));
        self::assertTrue((new ResumePolicy(10))->evaluate($runId)['allowed']);
    }

    public function test_a_missing_snapshot_does_not_count_as_zero_progress(): void
    {

        $runId = $this->makeRun();
        $this->restart($runId, null);
        $this->restart($runId, null);

        self::assertSame(0, (new ResumePolicy(0))->consecutiveZeroProgress($runId));
    }

    public function test_a_failed_resumable_run_with_pending_work_is_adopted(): void
    {
        $runId = $this->makeRun('failed', resumable: true);
        $this->queueItem($runId, 'pending');

        $found = (new ResumePolicy(0))->findResumable($this->shopId, 'scan');

        self::assertNotNull($found);
        self::assertSame($runId, $found->id);
    }

    public function test_a_failed_run_not_marked_resumable_is_left_alone(): void
    {
        $runId = $this->makeRun('failed', resumable: false);
        $this->queueItem($runId, 'pending');

        self::assertNull((new ResumePolicy(0))->findResumable($this->shopId, 'scan'));
    }

    public function test_a_heartbeat_timeout_requires_operator_resume(): void
    {
        $runId = $this->makeRun('failed', resumable: true);
        DB::table('scrape_runs')->where('id', $runId)->update([
            'close_reason' => 'heartbeat_timeout',
        ]);
        $this->queueItem($runId, 'pending');

        self::assertNull((new ResumePolicy(0))->findResumable($this->shopId, 'scan'));
    }

    public function test_a_run_with_no_pending_work_is_not_resumable(): void
    {
        $runId = $this->makeRun('failed', resumable: true);
        $this->queueItem($runId, 'done');

        self::assertNull((new ResumePolicy(0))->findResumable($this->shopId, 'scan'));
    }

    public function test_a_running_run_owns_its_queue(): void
    {
        $runId = $this->makeRun('running');
        $this->queueItem($runId, 'pending');

        self::assertSame($runId, (new ResumePolicy(0))->findResumable($this->shopId, 'scan')?->id);
    }

    private function queueItem(int $runId, string $status): void
    {
        DB::table('scrape_url_items')->insert([
            'run_id' => $runId,
            'shop_id' => $this->shopId,
            'url' => "https://resume.test/{$runId}-{$status}",
            'url_type' => 'product',
            'status' => $status,
            'created_at' => Carbon::now('UTC'),
        ]);
    }

    public function test_the_failsafe_never_clobbers_a_completed_run(): void
    {

        DB::commit();
        $runId = $this->makeRun('completed');

        try {
            $written = (new RunFailsafe)->finalize($runId, 'failed', 'stall_timeout', true, self::dsn());

            self::assertFalse($written);
            self::assertSame(
                'completed',
                DB::table('scrape_runs')->where('id', $runId)->value('status')
            );
        } finally {
            $this->cleanUpCommitted($runId);
        }
    }

    public function test_the_failsafe_marks_a_running_run_failed_and_resumable(): void
    {

        DB::commit();
        $runId = $this->makeRun('running');

        try {
            $written = (new RunFailsafe)->finalize($runId, 'failed', 'stall_timeout', true, self::dsn());

            $row = DB::table('scrape_runs')->where('id', $runId)->first();
            self::assertTrue($written);
            self::assertSame('failed', $row->status);
            self::assertSame('stall_timeout', $row->close_reason);
            self::assertTrue((bool) $row->resumable_after_failure);
            self::assertNotNull($row->finished_at);
        } finally {
            $this->cleanUpCommitted($runId);
        }
    }

    public function test_the_failsafe_records_a_reason_when_the_run_is_not_resumable(): void
    {

        DB::commit();
        $runId = $this->makeRun('running');

        try {
            $written = (new RunFailsafe)->finalize(
                $runId,
                'failed',
                'SQLSTATE[08006] connection refused',
                false,
                self::dsn()
            );

            $row = DB::table('scrape_runs')->where('id', $runId)->first();
            self::assertTrue($written, 'finalize reported failure');
            self::assertSame('failed', $row->status);
            self::assertSame('SQLSTATE[08006] connection refused', $row->close_reason);
            self::assertFalse((bool) $row->resumable_after_failure);
            self::assertNotNull($row->finished_at);
        } finally {
            $this->cleanUpCommitted($runId);
        }
    }

    private function cleanUpCommitted(int $runId): void
    {
        DB::table('scrape_run_events')->where('run_id', $runId)->delete();

        DB::table('scrape_url_items')->where('shop_id', $this->shopId)->delete();
        DB::table('scrape_runs')->where('shop_id', $this->shopId)->delete();
        DB::table('shops')->where('id', $this->shopId)->delete();
        DB::beginTransaction();
    }
}
