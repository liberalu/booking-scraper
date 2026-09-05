<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\DiscoveredUrl;
use App\Models\ShopBook;
use App\Support\UrlUtils;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;

final class DiscoveredUrlRepository
{
    public function upsert(
        int $shopId,
        string $url,
        string $source,
        ?int $runId = null,
        ?int $shopBookId = null,
    ): DiscoveredUrl {
        $normalized = UrlUtils::normalize($url);
        $now = Date::now('UTC');
        $initialType = $shopBookId !== null ? 'product' : 'unknown';

        $sets = ['last_seen_at = ?'];
        $bindings = [$now];

        if ($runId !== null) {
            $sets[] = 'last_seen_run_id = ?';
            $bindings[] = $runId;
        }
        if ($shopBookId !== null) {
            $sets[] = 'shop_book_id = ?';
            $bindings[] = $shopBookId;

            $sets[] = 'url_type = coalesce('
                ."case when discovered_urls.url_type = 'unknown' then 'product' "
                ."else discovered_urls.url_type end, 'product')";
        }

        $sql = sprintf(
            'insert into discovered_urls
                 (shop_id, url, normalized_url, source, url_type, fail_count,
                  first_seen_at, last_seen_at, last_seen_run_id, shop_book_id)
             values (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
             on conflict (shop_id, normalized_url) do update set %s
             returning id',
            implode(', ', $sets)
        );

        $row = DB::selectOne($sql, [
            $shopId, $url, $normalized, $source, $initialType,
            $now, $now, $runId, $shopBookId,
            ...$bindings,
        ]);

        return DiscoveredUrl::findOrFail(DatabaseRow::from($row)->int('id'));
    }

    public function linkToShopBook(
        int $shopId,
        string $url,
        int $shopBookId,
        ?int $runId = null,
        bool $isPartial = false,
    ): DiscoveredUrl {
        $targetType = $isPartial ? 'product_partial' : 'product';
        $normalized = UrlUtils::normalize($url);
        $now = Date::now('UTC');

        $existing = DiscoveredUrl::where('shop_id', $shopId)
            ->where('normalized_url', $normalized)
            ->first();

        if ($existing !== null) {
            if ($existing->shop_book_id !== $shopBookId) {
                $existing->shop_book_id = $shopBookId;
            }
            if ($existing->url_type === 'unknown') {
                $existing->url_type = $targetType;
            } elseif ($existing->url_type === 'product_partial' && ! $isPartial) {
                $existing->url_type = 'product';
            }
            $existing->last_seen_at = $now;
            if ($runId !== null) {
                $existing->last_seen_run_id = $runId;
            }
            $existing->save();

            return $existing;
        }

        $record = new DiscoveredUrl;
        $record->shop_id = $shopId;
        $record->url = $url;
        $record->normalized_url = $normalized;

        $record->source = 'category';
        $record->url_type = $targetType;
        $record->first_seen_at = $now;
        $record->last_seen_at = $now;
        $record->last_seen_run_id = $runId;
        $record->shop_book_id = $shopBookId;
        $record->save();

        return $record;
    }

    /** @param list<array{key: string, points: int}> $reasons */
    public function markNonProduct(
        int $shopId,
        string $url,
        ?int $runId = null,
        int $bookScore = 0,
        array $reasons = [],
    ): ?DiscoveredUrl {
        $normalized = UrlUtils::normalize($url);
        $now = Date::now('UTC');

        $row = DiscoveredUrl::where('shop_id', $shopId)
            ->where('normalized_url', $normalized)
            ->first();
        if ($row === null) {
            return null;
        }

        if ($row->url_type !== 'product') {
            $row->url_type = 'non_product';
        }
        $row->last_checked_at = $now;
        $row->last_seen_at = $now;
        $row->last_http_status = 200;
        if ($runId !== null) {
            $row->last_seen_run_id = $runId;
        }
        $row->save();

        DB::table('url_classifications')->updateOrInsert(
            ['discovered_url_id' => $row->id],
            [
                'book_score' => $bookScore,
                'is_book_product' => false,
                'reasons' => json_encode($reasons),
                'classified_at' => $now,
            ]
        );

        return $row;
    }

    /** @param array<string, true> $activeUrls */
    public function deactivateMissing(int $shopId, array $activeUrls): int
    {
        $now = Date::now('UTC');
        $deactivated = 0;

        ShopBook::select(['id', 'url'])
            ->where('shop_id', $shopId)
            ->where('is_active', true)
            ->chunkById(1000, function ($books) use ($activeUrls, $now, &$deactivated): void {
                $stale = $books
                    ->reject(fn ($book): bool => isset($activeUrls[$book->url]))
                    ->pluck('id')
                    ->all();
                if ($stale !== []) {
                    ShopBook::whereIn('id', $stale)
                        ->update(['is_active' => false, 'inactive_since' => $now]);
                    $deactivated += count($stale);
                }
            });

        return $deactivated;
    }
}
