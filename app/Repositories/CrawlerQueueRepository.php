<?php

declare(strict_types=1);

namespace App\Repositories;

use Generator;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final class CrawlerQueueRepository
{
    public function discoveredUrlCount(int $shopId): int
    {
        return DB::table('discovered_urls')->where('shop_id', $shopId)->count();
    }

    /** @return list<string> */
    public function stableUrls(int $shopId): array
    {
        return self::strings(DB::table('discovered_urls')
            ->where('shop_id', $shopId)
            ->whereIn('url_type', ['product', 'non_product', 'unreachable'])
            ->where('last_checked_at', '>=', Carbon::now('UTC')->subDays(7))
            ->pluck('normalized_url')
            ->all());
    }

    /** @return list<string> */
    public function pendingRunUrls(int $runId): array
    {
        return self::strings(DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'pending')
            ->orderBy('id')
            ->pluck('url')
            ->all());
    }

    public function pendingRunUrlCount(int $runId, int $limit): int
    {
        return min(
            $limit,
            DB::table('scrape_url_items')
                ->where('run_id', $runId)
                ->where('status', 'pending')
                ->count(),
        );
    }

    /** @return Generator<int, list<string>, mixed, void> */
    public function pendingRunUrlBatches(int $runId, int $limit, int $batchSize = 500): Generator
    {
        $query = DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'pending')
            ->orderBy('id')
            ->limit($limit);

        yield from $this->batches($query->cursor(), $batchSize);
    }

    /** @return list<string> */
    public function scanUrls(int $shopId, string $mode, int $limit): array
    {
        return self::strings($this->scanQuery($shopId, $mode)
            ->orderByRaw('last_checked_at asc nulls first')
            ->limit($limit)
            ->pluck('url')
            ->all());
    }

    public function scanUrlCount(int $shopId, string $mode, int $limit): int
    {
        return min($limit, $this->scanQuery($shopId, $mode)->count());
    }

    /** @return Generator<int, list<string>, mixed, void> */
    public function scanUrlBatches(
        int $shopId,
        string $mode,
        int $limit,
        int $batchSize = 500,
    ): Generator {
        $query = $this->scanQuery($shopId, $mode)
            ->orderByRaw('last_checked_at asc nulls first')
            ->orderBy('id')
            ->limit($limit);

        yield from $this->batches($query->cursor(), $batchSize);
    }

    private function scanQuery(int $shopId, string $mode): Builder
    {
        $query = DB::table('discovered_urls')
            ->where('shop_id', $shopId)
            ->where('url_type', '!=', 'non_product')
            ->where(static function (Builder $query): void {
                $query->where('fail_count', '<', 3)
                    ->orWhere('last_checked_at', '<', Carbon::now('UTC')->subDays(7))
                    ->orWhereNull('last_checked_at');
            });

        if ($mode === 'delta') {
            $query->where('url_type', '!=', 'product');
        }

        return $query;
    }

    /**
     * @param  iterable<mixed>  $rows
     * @return Generator<int, list<string>, mixed, void>
     */
    private function batches(iterable $rows, int $batchSize): Generator
    {
        $batch = [];
        foreach ($rows as $row) {
            $url = DatabaseRow::from($row)->nullableString('url');
            if ($url === null) {
                continue;
            }
            $batch[] = $url;
            if (count($batch) === $batchSize) {
                yield $batch;
                $batch = [];
            }
        }
        if ($batch !== []) {
            yield $batch;
        }
    }

    /**
     * @param  array<mixed>  $values
     * @return list<string>
     */
    private static function strings(array $values): array
    {
        return array_values(array_filter($values, is_string(...)));
    }
}
