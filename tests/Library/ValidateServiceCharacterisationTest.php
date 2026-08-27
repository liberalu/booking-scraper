<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Support\Database;
use App\Services\ValidateService;
use App\Testing\SyntheticShop;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

/**
 * Every validator check, pinned to the findings Python agreed with.
 *
 * `make validate-diff` runs both validators over identical data and diffs
 * every finding — which needs Python. `validate_diff --freeze` writes the
 * golden only once both stacks matched, so this replays Python's findings, not
 * PHP's output.
 *
 * Frozen over the SYNTHETIC shop, and only over it. The comparison also ran on
 * copies of real shops (vaga: 13,339 findings, patogupirkti: 62,523, both
 * identical) and those runs are worth more as evidence — but they are not
 * freezable: the copy comes from the live catalogue, which moves with every
 * crawl, so the counts would drift and this test would fail for reasons that
 * are not regressions. The synthetic shop is built from nothing by
 * SyntheticShop, and 26 rows produce the same 33 findings every time across
 * all 20 issue types, including the suppression cases.
 *
 * Findings identify their book by URL rather than by id: ids are serials that
 * change every time the fixture is rebuilt.
 *
 * Everything happens inside a transaction that is rolled back, because the
 * validator MUTATES data — the non_product auto-heal deactivates a book — and
 * a tool that leaves its fixtures behind breaks the next one. That has already
 * happened three times in this port.
 */
final class ValidateServiceCharacterisationTest extends TestCase
{
    private const GOLDEN = __DIR__ . '/golden/validate_findings.json';

    #[Group('db')]
    public function testTheSyntheticShopYieldsTheFindingsPythonProduced(): void
    {
        $expected = json_decode((string) file_get_contents(self::GOLDEN), true);
        self::assertIsArray($expected, 'golden is missing — run `make validate-diff FREEZE=1`');

        Database::boot(getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');

        DB::beginTransaction();
        try {
            $built = SyntheticShop::build(DB::connection());
            $shopId = $built['shop_id'];

            // The fixture plants one issue so the dashboard's issue-detail
            // route has something to show. This test measures what the
            // VALIDATOR finds, so it goes first — otherwise the planted row
            // would be counted as a finding, and resolveGone() would decide
            // what to do with it.
            DB::table('validation_issues')->where('shop_id', $shopId)->delete();

            $runId = (int) DB::table('scrape_runs')
                ->where('shop_id', $shopId)
                ->orderByDesc('id')
                ->value('id');

            (new ValidateService())->run($shopId, $runId);

            self::assertSame($expected, $this->findings($shopId));
        } finally {
            DB::rollBack();
        }
    }

    /**
     * Everything the validator produced, ordered deterministically.
     *
     * Mirrors findings() in php/tools/validate_diff.py — the same columns in
     * the same order, so the golden one writes is the structure this reads.
     *
     * @return array{counts: array<string, int>, deactivated_count: int, issues: list<array<string, mixed>>}
     */
    private function findings(int $shopId): array
    {
        $rows = DB::select(
            'select vi.issue, vi.field, vi.url, vi.raw_value, sb.url as shop_book_url, '
            . 'vi.lifecycle_state, vi.run_count, '
            . 'vi.acknowledged_at is not null as acked '
            . 'from validation_issues vi '
            . 'left join shop_books sb on sb.id = vi.shop_book_id '
            . 'where vi.shop_id = ? '
            . 'order by vi.issue, vi.field, sb.url, vi.url',
            [$shopId]
        );

        $issues = [];
        $counts = [];
        foreach ($rows as $row) {
            // Key order matches the golden's, which was written sorted.
            $issues[] = [
                'acked' => (bool) $row->acked,
                'field' => $row->field,
                'issue' => $row->issue,
                'lifecycle_state' => $row->lifecycle_state,
                'raw_value' => $row->raw_value,
                'run_count' => (int) $row->run_count,
                'shop_book_url' => $row->shop_book_url,
                'url' => $row->url,
            ];
            $counts[$row->issue] = ($counts[$row->issue] ?? 0) + 1;
        }
        ksort($counts);

        $deactivated = DB::table('shop_books')
            ->where('shop_id', $shopId)
            ->where('is_active', false)
            ->count();

        return [
            'counts' => $counts,
            'deactivated_count' => $deactivated,
            'issues' => $issues,
        ];
    }
}
