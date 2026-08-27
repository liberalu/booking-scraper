<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Support\Database;
use App\Runs\RunEvent;
use App\Runs\RunReconciler;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

/**
 * Boot reconciliation. A row still marked `running` after a restart has no
 * process behind it, and leaving it there makes a dead run look alive to
 * every dashboard query and to find-resumable.
 */
final class RunReconcilerTest extends TestCase
{
    private static bool $booted = false;

    private int $shopId;

    protected function setUp(): void
    {
        if (!self::$booted) {
            Database::boot(
                getenv('TEST_DATABASE_URL')
                    ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test'
            );
            self::$booted = true;
        }
        DB::beginTransaction();

        // markOrphansFailed() is global by design, so park any pre-existing
        // `running` row inside this transaction. Deleting is not an option:
        // shop_books.last_run_id references scrape_runs.
        DB::table('scrape_runs')->where('status', 'running')->update(['status' => 'completed']);

        $this->shopId = (int) (DB::table('shops')->where('name', 'reconcile-test')->value('id')
            ?? DB::table('shops')->insertGetId(
                ['name' => 'reconcile-test', 'base_url' => 'https://reconcile.test'],
                'id'
            ));
    }

    protected function tearDown(): void
    {
        DB::rollBack();
    }

    private function makeRun(string $status): int
    {
        return DB::table('scrape_runs')->insertGetId([
            'shop_id' => $this->shopId,
            'phase' => 'scan',
            'status' => $status,
            'started_at' => Carbon::now('UTC')->subHour(),
            'urls_processed' => 3,
            'items_added' => 0,
            'items_updated' => 0,
            'errors_4xx' => 0,
            'errors_5xx' => 0,
            'error_count' => 0,
        ], 'id');
    }

    public function test_a_running_orphan_is_failed_and_flagged_resumable(): void
    {
        $runId = $this->makeRun('running');

        $orphans = RunReconciler::markOrphansFailed();

        self::assertSame([['id' => $runId, 'shop' => 'reconcile-test', 'phase' => 'scan']], $orphans);

        $row = DB::table('scrape_runs')->where('id', $runId)->first();
        self::assertSame('failed', $row->status);
        self::assertSame('orphan_on_boot', $row->close_reason);
        self::assertTrue(
            (bool) $row->resumable_after_failure,
            'an orphan did real work — its pending queue must survive'
        );
        self::assertNotNull($row->finished_at);
    }

    public function test_the_transition_is_recorded_on_the_timeline(): void
    {
        // Otherwise a run just changes state with no auditable cause.
        $runId = $this->makeRun('running');

        RunReconciler::markOrphansFailed();

        $event = DB::table('scrape_run_events')
            ->where('run_id', $runId)
            ->where('event_type', RunEvent::FAILED)
            ->first();
        self::assertNotNull($event);
        self::assertStringContainsString('orphan_on_boot', (string) $event->payload);
    }

    public function test_terminal_and_paused_runs_are_untouched(): void
    {
        // A paused run is alive and deliberately parked; reaping it would
        // discard an operator's decision.
        $ids = [];
        foreach (['completed', 'failed', 'paused'] as $status) {
            $ids[$status] = $this->makeRun($status);
        }

        self::assertSame([], RunReconciler::markOrphansFailed());

        foreach ($ids as $status => $id) {
            self::assertSame(
                $status,
                DB::table('scrape_runs')->where('id', $id)->value('status')
            );
        }
    }

    public function test_reconciling_with_no_orphans_is_a_no_op(): void
    {
        self::assertSame([], RunReconciler::markOrphansFailed());
    }
}
