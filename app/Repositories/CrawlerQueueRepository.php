<?php

declare(strict_types=1);

namespace App\Repositories;

use Generator;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Facades\Date;
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
        return $this->strings(DB::table('discovered_urls')
            ->where('shop_id', $shopId)
            ->whereIn('url_type', ['product', 'non_product', 'unreachable'])
            ->where('last_checked_at', '>=', Date::now('UTC')->subDays(7))
            ->pluck('normalized_url')
            ->all());
    }

    /** @param iterable<string> $urls */
    public function enqueue(int $runId, int $shopId, iterable $urls): int
    {
        $inserted = 0;
        foreach ($this->batches($this->asRows($urls), 500) as $chunk) {
            $known = [];
            foreach (DB::table('discovered_urls')
                ->where('shop_id', $shopId)
                ->whereIn('url', $chunk)
                ->get(['id', 'url', 'url_type']) as $raw) {
                $row = DatabaseRow::from($raw);
                $known[$row->string('url')] = [
                    'id' => $row->int('id'),
                    'url_type' => $row->nullableString('url_type') ?? 'product',
                ];
            }

            $now = Date::now('UTC');
            $rows = [];
            foreach ($chunk as $url) {
                $rows[] = [
                    'run_id' => $runId,
                    'shop_id' => $shopId,
                    'discovered_url_id' => $known[$url]['id'] ?? null,
                    'url' => $url,
                    'url_type' => $known[$url]['url_type'] ?? 'product',
                    'status' => 'pending',
                    'created_at' => $now,
                ];
            }
            $inserted += DB::table('scrape_url_items')->insertOrIgnore($rows);
        }

        return $inserted;
    }

    /** @param list<string> $urls */
    public function claim(int $runId, array $urls): int
    {
        $claimed = 0;
        foreach (array_chunk($urls, 500) as $chunk) {
            $claimed += DB::table('scrape_url_items')
                ->where('run_id', $runId)
                ->whereIn('url', $chunk)
                ->where('status', 'pending')
                ->update([
                    'status' => 'processing',
                    'claimed_at' => Date::now('UTC'),
                    'attempts' => DB::raw('attempts + 1'),
                ]);
        }

        return $claimed;
    }

    public function markDone(int $runId, string $url, ?int $httpStatus = null, ?int $responseBytes = null): bool
    {
        $fields = ['status' => 'done', 'done_at' => Date::now('UTC')];
        if ($httpStatus !== null) {
            $fields['http_status'] = $httpStatus;
        }
        if ($responseBytes !== null) {
            $fields['response_bytes'] = $responseBytes;
        }

        return DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('url', $url)
            ->whereIn('status', ['pending', 'processing'])
            ->update($fields) > 0;
    }

    public function markFailed(
        int $runId,
        string $url,
        string $reason,
        ?int $httpStatus = null,
        ?string $detail = null,
    ): bool {
        return DB::transaction(function () use ($runId, $url, $reason, $httpStatus, $detail): bool {
            $item = DB::table('scrape_url_items')
                ->where('run_id', $runId)
                ->where('url', $url)
                ->whereIn('status', ['pending', 'processing', 'done'])
                ->lockForUpdate()
                ->first(['id', 'shop_id', 'discovered_url_id']);
            if ($item === null) {
                return false;
            }

            $row = DatabaseRow::from($item);
            $now = Date::now('UTC');
            $fields = ['status' => 'failed', 'done_at' => $now];
            if ($httpStatus !== null) {
                $fields['http_status'] = $httpStatus;
            }
            DB::table('scrape_url_items')->where('id', $row->int('id'))->update($fields);

            DB::table('scrape_failures')->insert([
                'scrape_url_item_id' => $row->int('id'),
                'run_id' => $runId,
                'shop_id' => $row->int('shop_id'),
                'url' => $url,
                'discovered_url_id' => $row->nullableInt('discovered_url_id'),
                'occurred_at' => $now,
                'error_reason' => $reason,
                'http_status' => $httpStatus,
                'error_detail' => $detail === null ? null : mb_substr($detail, 0, 500),
                'lifecycle_state' => 'new',
            ]);

            return true;
        });
    }

    /** @return list<string> */
    public function pendingRunUrls(int $runId): array
    {
        return $this->strings(DB::table('scrape_url_items')
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
        return $this->strings($this->scanQuery($shopId, $mode)
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
                    ->orWhere('last_checked_at', '<', Date::now('UTC')->subDays(7))
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
     * @param  iterable<string>  $urls
     * @return Generator<int, array{url: string}, mixed, void>
     */
    private function asRows(iterable $urls): Generator
    {
        foreach ($urls as $url) {
            yield ['url' => $url];
        }
    }

    /**
     * @param  array<mixed>  $values
     * @return list<string>
     */
    private function strings(array $values): array
    {
        return array_values(array_filter($values, is_string(...)));
    }
}
