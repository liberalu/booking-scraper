<?php

declare(strict_types=1);

namespace App\Repositories;

use Illuminate\Support\Facades\DB;

final readonly class RunReconcilerRepository
{
    private const array RETRYABLE_REASONS = ['run_aborted', 'stuck_in_processing', 'subdivision_5xx'];

    public const int RETRY_CAP = 3;

    public function __construct(
        private RunFinisherRepository $finisher = new RunFinisherRepository,
    ) {}

    /** @return list<array{id: int, shop: string, phase: string}> */
    public function markOrphansFailed(): array
    {
        $orphans = DB::table('scrape_runs')
            ->join('shops', 'shops.id', '=', 'scrape_runs.shop_id')
            ->where('scrape_runs.status', 'running')
            ->select('scrape_runs.id', 'shops.name as shop', 'scrape_runs.phase')
            ->get();

        if ($orphans->isEmpty()) {
            return [];
        }

        $result = [];
        foreach ($orphans as $orphan) {
            $row = DatabaseRow::from($orphan);
            $this->finisher->finish(
                $row->int('id'),
                'failed',
                'orphan_on_boot',
                resumableAfterFailure: true,
            );
            $result[] = [
                'id' => $row->int('id'),
                'shop' => $row->string('shop'),
                'phase' => $row->string('phase'),
            ];
        }

        return $result;
    }

    public function resetRetryableFailures(int $runId, int $cap = self::RETRY_CAP): int
    {
        $ids = DB::table('scrape_url_items')
            ->join(
                'scrape_failures',
                'scrape_failures.scrape_url_item_id',
                '=',
                'scrape_url_items.id'
            )
            ->where('scrape_url_items.run_id', $runId)
            ->where('scrape_url_items.status', 'failed')
            ->where('scrape_url_items.attempts', '<', $cap)
            ->where('scrape_failures.run_id', $runId)
            ->whereIn('scrape_failures.error_reason', self::RETRYABLE_REASONS)
            ->distinct()
            ->pluck('scrape_url_items.id')
            ->all();

        if ($ids === []) {
            return 0;
        }

        return DB::table('scrape_url_items')
            ->whereIn('id', $ids)
            ->update(['status' => 'pending', 'done_at' => null]);
    }

    public function releaseStuckProcessing(int $runId): int
    {
        return DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'processing')
            ->update(['status' => 'pending', 'claimed_at' => null]);
    }
}
