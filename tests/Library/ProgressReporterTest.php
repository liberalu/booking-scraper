<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Runs\ProgressReporter;
use App\Support\Database;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

final class ProgressReporterTest extends TestCase
{
    private const string MARK = 'progress-reporter-test';

    private ProgressReporter $progress;

    protected function setUp(): void
    {
        parent::setUp();
        Database::boot(getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');
        $this->progress = new ProgressReporter;
    }

    protected function tearDown(): void
    {
        $this->progress->reset();
        parent::tearDown();
    }

    private function makeRun(): array
    {
        $shopId = (int) (DB::table('shops')->where('name', self::MARK)->value('id')
            ?? DB::table('shops')->insertGetId(
                ['name' => self::MARK, 'base_url' => 'https://progress.test'],
                'id'
            ));

        $runId = (int) DB::selectOne(
            "insert into scrape_runs (shop_id, phase, status, started_at, urls_total,
                 urls_processed, items_added, items_updated, errors_4xx, errors_5xx,
                 error_count)
             values (?, 'scan', 'running', now(), 100, 0, 0, 0, 0, 0, 0)
             returning id",
            [$shopId]
        )->id;

        return [$shopId, $runId];
    }

    private function processed(int $runId): int
    {
        return (int) DB::table('scrape_runs')->where('id', $runId)->value('urls_processed');
    }

    #[Group('db')]
    public function test_nothing_is_written_before_the_tenth_item(): void
    {
        DB::beginTransaction();
        try {
            [, $runId] = $this->makeRun();
            $this->progress->bind($runId, static fn (array $t): int => $t['added']);

            for ($i = 1; $i <= 9; $i++) {
                $this->progress->tick(['added' => $i]);
                self::assertSame(0, $this->processed($runId), "wrote on item {$i}");
            }
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_the_tenth_item_writes(): void
    {
        DB::beginTransaction();
        try {
            [, $runId] = $this->makeRun();
            $this->progress->bind($runId, static fn (array $t): int => $t['added']);

            for ($i = 1; $i <= 10; $i++) {
                $this->progress->tick(['added' => $i]);
            }

            self::assertSame(10, $this->processed($runId));
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_it_keeps_writing_every_tenth_item(): void
    {
        DB::beginTransaction();
        try {
            [, $runId] = $this->makeRun();
            $this->progress->bind($runId, static fn (array $t): int => $t['added']);

            for ($i = 1; $i <= 25; $i++) {
                $this->progress->tick(['added' => $i]);
            }

            self::assertSame(20, $this->processed($runId));
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_the_phase_formula_decides_what_processed_means(): void
    {

        DB::beginTransaction();
        try {
            [, $runId] = $this->makeRun();
            $tally = ['added' => 3, 'updated' => 4, 'non_product' => 5, 'canonical' => 1];

            $this->progress->bind(
                $runId,
                static fn (array $t): int => $t['added'] + $t['updated'] + $t['non_product']
                    + ($t['canonical'] ?? 0)
            );
            $this->progress->flush($tally);
            self::assertSame(13, $this->processed($runId), 'serial-scan formula');

            $this->progress->bind(
                $runId,
                static fn (array $t): int => $t['added'] + $t['updated'] + ($t['canonical'] ?? 0)
            );
            $this->progress->flush($tally);
            self::assertSame(8, $this->processed($runId), 'roach-scan formula');
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_it_also_writes_the_item_counters_and_a_heartbeat(): void
    {

        DB::beginTransaction();
        try {
            [, $runId] = $this->makeRun();
            DB::table('scrape_runs')->where('id', $runId)->update(['last_heartbeat' => null]);
            $this->progress->bind($runId, static fn (array $t): int => $t['added']);

            $this->progress->flush(['added' => 7, 'updated' => 2, 'failed' => 1]);

            $row = DB::table('scrape_runs')->where('id', $runId)->first();
            self::assertSame(7, (int) $row->items_added);
            self::assertSame(2, (int) $row->items_updated);
            self::assertSame(1, (int) $row->error_count);
            self::assertNotNull($row->last_heartbeat);
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_an_unbound_reporter_writes_nothing(): void
    {

        DB::beginTransaction();
        try {
            [, $runId] = $this->makeRun();
            $this->progress->reset();

            $this->progress->tick(['added' => 1]);
            $this->progress->flush(['added' => 99]);

            self::assertSame(0, $this->processed($runId));
        } finally {
            DB::rollBack();
        }
    }
}
