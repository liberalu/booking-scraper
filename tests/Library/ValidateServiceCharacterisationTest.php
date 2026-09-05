<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Repositories\ValidationIssueRepository;
use App\Repositories\ValidationRepository;
use App\Services\ValidateService;
use App\Support\Database;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;
use Tests\Support\SyntheticShop;

final class ValidateServiceCharacterisationTest extends TestCase
{
    private const string GOLDEN = __DIR__.'/../golden/validate_findings.json';

    #[Group('db')]
    public function test_the_synthetic_shop_yields_the_findings_python_produced(): void
    {
        $expected = json_decode((string) file_get_contents(self::GOLDEN), true);
        self::assertIsArray($expected, 'golden is missing — run `make validate-diff FREEZE=1`');

        Database::boot(getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');

        DB::beginTransaction();
        try {
            $built = SyntheticShop::build(DB::connection());
            $shopId = $built['shop_id'];

            DB::table('validation_issues')->where('shop_id', $shopId)->delete();

            $runId = (int) DB::table('scrape_runs')
                ->where('shop_id', $shopId)
                ->orderByDesc('id')
                ->value('id');

            $database = Database::manager();
            (new ValidateService(new ValidationRepository(
                new ValidationIssueRepository($database),
                $database,
            )))
                ->run($shopId, $runId);

            self::assertSame($expected, $this->findings($shopId));
        } finally {
            DB::rollBack();
        }
    }

    private function findings(int $shopId): array
    {
        $rows = DB::select(
            'select vi.issue, vi.field, vi.url, vi.raw_value, sb.url as shop_book_url, '
            .'vi.lifecycle_state, vi.run_count, '
            .'vi.acknowledged_at is not null as acked '
            .'from validation_issues vi '
            .'left join shop_books sb on sb.id = vi.shop_book_id '
            .'where vi.shop_id = ? '
            .'order by vi.issue, vi.field, sb.url, vi.url',
            [$shopId]
        );

        $issues = [];
        $counts = [];
        foreach ($rows as $row) {

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
