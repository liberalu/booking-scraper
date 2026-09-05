<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Runs\Reaper;
use App\Support\Database;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

final class ReaperCharacterisationTest extends TestCase
{
    private const string SPEC = __DIR__.'/../golden/reaper_fixtures.json';

    private const string EXPECTED = __DIR__.'/../golden/reaper_expected.json';

    #[Group('db')]
    public function test_each_fixture_is_reaped_as_python_reaped_it(): void
    {
        $spec = $this->json(self::SPEC);
        $expected = $this->json(self::EXPECTED);
        $marker = $spec['marker'];

        Database::boot(getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');

        DB::beginTransaction();
        try {
            $shopId = (int) (DB::table('shops')->where('name', 'reaper-char')->value('id')
                ?? DB::table('shops')->insertGetId(
                    ['name' => 'reaper-char', 'base_url' => 'https://reaper.test'],
                    'id'
                ));

            $runIds = [];
            foreach ($spec['runs'] as $run) {
                $heartbeat = $this->interval($run['heartbeat']);
                $runIds[$run['fixture']] = (int) DB::selectOne(
                    "insert into scrape_runs (shop_id, phase, status, started_at,
                         urls_total, urls_processed, items_added, items_updated,
                         errors_4xx, errors_5xx, error_count, last_heartbeat,
                         close_reason, finished_at)
                     values (?, ?, ?, now() - interval '1 hour', 10, 5, 0, 0,
                         0, 0, 0, {$heartbeat}, ?,
                         case when ? in ('completed','failed') then now() end)
                     returning id",
                    [$shopId, $run['phase'], $run['status'], $marker, $run['status']]
                )->id;
            }

            foreach ($spec['items'] as $index => $item) {
                $claimed = $this->interval($item['claimed']);

                DB::insert(
                    "insert into scrape_url_items (run_id, shop_id, url, url_type,
                         status, created_at, claimed_at, attempts)
                     values (?, ?, ?, 'product', ?, now() - interval '1 hour',
                         {$claimed}, 0)",
                    [
                        $runIds[$item['run']],
                        $shopId,
                        "https://example.test/{$marker}/{$index}-{$item['run']}",
                        $item['status'],
                    ]
                );
            }

            (new Reaper)->sweep();

            $actual = $this->outcome($marker, $shopId);
            self::assertCount(count($expected), $actual);
            foreach ($expected as $i => $row) {
                self::assertSame(
                    $row,
                    $actual[$i],
                    "reaper behaviour changed for fixture: {$row['fixture']}"
                );
            }
        } finally {
            DB::rollBack();
        }
    }

    public function test_the_fixtures_still_cover_every_rule(): void
    {
        $expected = $this->json(self::EXPECTED);

        $reasons = array_filter(array_column($expected, 'failure_reasons'));
        self::assertContains('run_aborted', $reasons, 'no fixture covers run_aborted');
        self::assertContains(
            'stuck_in_processing',
            $reasons,
            'no fixture covers a hung worker on a live run'
        );

        $runStates = array_unique(array_column($expected, 'run_status'));
        foreach (['failed', 'paused', 'running', 'completed'] as $state) {
            self::assertContains($state, $runStates, "no fixture leaves a run {$state}");
        }

        $itemStates = array_column($expected, 'item_status');
        self::assertContains('processing', $itemStates);
        self::assertContains('pending', $itemStates);
        self::assertContains('failed', $itemStates);
    }

    #[Group('db')]
    public function test_old_failed_runs_stop_looking_actionable(): void
    {
        Database::boot(getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');
        DB::beginTransaction();
        try {
            $shopId = DB::table('shops')->insertGetId([
                'name' => 'resumable-retention-test',
                'base_url' => 'https://retention.test',
            ], 'id');
            $runId = DB::table('scrape_runs')->insertGetId([
                'shop_id' => $shopId,
                'phase' => 'scan',
                'status' => 'failed',
                'started_at' => Date::now('UTC')->subDays(9),
                'finished_at' => Date::now('UTC')->subDays(8),
                'resumable_after_failure' => true,
                'urls_processed' => 0,
                'items_added' => 0,
                'items_updated' => 0,
                'errors_4xx' => 0,
                'errors_5xx' => 0,
                'error_count' => 0,
            ], 'id');

            (new Reaper)->sweep();

            self::assertFalse((bool) DB::table('scrape_runs')
                ->where('id', $runId)
                ->value('resumable_after_failure'));
        } finally {
            DB::rollBack();
        }
    }

    private function outcome(string $marker, int $shopId): array
    {
        return array_map(
            static fn (object $r): array => [
                'fixture' => $r->fixture,
                'item_status' => $r->item_status,
                'item_done' => (bool) $r->item_done,
                'item_attempts' => (int) $r->item_attempts,
                'failure_reasons' => $r->failure_reasons,
                'run_status' => $r->run_status,
                'run_close_reason' => $r->run_close_reason,
                'run_resumable' => (bool) $r->run_resumable,
            ],
            DB::select(
                "select split_part(sui.url, '/', 5) as fixture,
                        sui.status as item_status,
                        sui.done_at is not null as item_done,
                        sui.attempts as item_attempts,
                        (select string_agg(distinct sf.error_reason, ','
                                 order by sf.error_reason)
                           from scrape_failures sf
                          where sf.scrape_url_item_id = sui.id) as failure_reasons,
                        sr.status as run_status,
                        sr.close_reason as run_close_reason,
                        sr.resumable_after_failure as run_resumable
                   from scrape_url_items sui
                   join scrape_runs sr on sr.id = sui.run_id
                  where sui.url like ? and sui.shop_id = ?
                  order by sui.url",
                ["%{$marker}%", $shopId]
            )
        );
    }

    private function interval(?string $age): string
    {
        return $age === null ? 'null' : "now() - interval '{$age}'";
    }

    private function json(string $path): array
    {
        self::assertFileExists($path, 'run `make reaper-diff FREEZE=1` first');

        return json_decode((string) file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    }
}
