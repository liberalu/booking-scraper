<?php

declare(strict_types=1);

namespace BookScraper\Tests;

use BookScraper\Database;
use BookScraper\Runs\Reaper;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

/**
 * The reaper, pinned to behaviour Python agreed with.
 *
 * `make reaper-diff` plants zombie runs in two database clones, runs each
 * stack's reaper, and diffs six tables — which needs Python. So the outcome per
 * fixture is frozen instead, and `--freeze` only writes once both reapers
 * agreed. What this asserts is Python's behaviour captured.
 *
 * The fixture shapes come from the same JSON the comparison tool plants from.
 * Two copies of them would drift, and a drifted fixture makes the comparison
 * assert nothing — which is the failure this whole phase exists to avoid.
 *
 * Frozen per fixture rather than as whole-table state: table dumps carry row
 * ids and whatever else the database already held, so they would need
 * rewriting on every unrelated change. The verdict per fixture is the part
 * that actually encodes the rules — and each row below is a different rule:
 * a silent run dies, a hung worker on a *live* run is failed without failing
 * the run, an in-flight item is left alone, a pending item is never touched,
 * and a `processing` row that was never legitimately claimed is never reaped
 * however old it is.
 */
final class ReaperCharacterisationTest extends TestCase
{
    private const SPEC = __DIR__ . '/golden/reaper_fixtures.json';

    private const EXPECTED = __DIR__ . '/golden/reaper_expected.json';

    #[Group('db')]
    public function testEachFixtureIsReapedAsPythonReapedIt(): void
    {
        $spec = self::json(self::SPEC);
        $expected = self::json(self::EXPECTED);
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
                $heartbeat = self::interval($run['heartbeat']);
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
                $claimed = self::interval($item['claimed']);
                // The index is in the URL because (run_id, url) is unique and
                // two fixtures share a run and a status.
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

            Reaper::sweep();

            // Scoped to this test's own shop: reaper_diff plants the same
            // marker into the base database before cloning, so matching on
            // the marker alone picks up its leftovers too.
            $actual = self::outcome($marker, $shopId);
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

    /** Each fixture must still exercise a distinct rule. */
    public function testTheFixturesStillCoverEveryRule(): void
    {
        $expected = self::json(self::EXPECTED);

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

        // A `processing` item that survives is the never-claimed rule; a
        // `pending` one is the never-touch-pending rule.
        $itemStates = array_column($expected, 'item_status');
        self::assertContains('processing', $itemStates);
        self::assertContains('pending', $itemStates);
        self::assertContains('failed', $itemStates);
    }

    /** @return list<array<string, mixed>> */
    private static function outcome(string $marker, int $shopId): array
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

    private static function interval(?string $age): string
    {
        return $age === null ? 'null' : "now() - interval '{$age}'";
    }

    /** @return array<string, mixed> */
    private static function json(string $path): array
    {
        self::assertFileExists($path, 'run `make reaper-diff FREEZE=1` first');

        return json_decode((string) file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    }
}
