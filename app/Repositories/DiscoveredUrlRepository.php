<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\DiscoveredUrl;
use App\Support\UrlUtils;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * Port of upsert_discovered_url() in book_scraper/db/repo.py.
 *
 * Written as a single atomic INSERT … ON CONFLICT DO UPDATE, not
 * SELECT-then-INSERT. Two items in one batch can carry the same URL (a
 * book listed under several categories in one page response); the
 * read-then-write version raised a unique violation, which then poisoned
 * the transaction for every later item in the batch — the spider went
 * quiet, stalled and died without finishing.
 */
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
        $now = Carbon::now('UTC');
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
            // Promote 'unknown' → 'product' once we know it's a real
            // product page, but never demote 'non_product' /
            // 'unreachable': those are operator decisions.
            $sets[] = "url_type = coalesce("
                . "case when discovered_urls.url_type = 'unknown' then 'product' "
                . "else discovered_urls.url_type end, 'product')";
        }

        // fail_count is spelled out because this is raw SQL: the model's
        // HasSqlAlchemyDefaults never runs, and the column is NOT NULL with
        // no server default (SQLAlchemy declares it Python-side).
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

        // Re-read rather than trusting a cached model: the same URL may
        // have been upserted earlier in this request, and callers read
        // last_seen_at / shop_book_id straight off the result.
        return DiscoveredUrl::findOrFail($row->id);
    }

    /**
     * Port of link_discovered_url_to_shop_book().
     *
     * Idempotently attaches a shop_book to its URL row, creating the row if
     * discovery never saw it. `$isPartial` means the persisted shop_book is
     * missing key metadata (no ISBN — common from lupasearch and some
     * category parsers), so the delta scan should still pick it up.
     *
     * Promotion ladder: unknown -> product_partial -> product. A complete
     * call advances product_partial to product; a partial call must NOT
     * demote an already-complete row. Full data is sticky.
     */
    public function linkToShopBook(
        int $shopId,
        string $url,
        int $shopBookId,
        ?int $runId = null,
        bool $isPartial = false,
    ): DiscoveredUrl {
        $targetType = $isPartial ? 'product_partial' : 'product';
        $normalized = UrlUtils::normalize($url);
        $now = Carbon::now('UTC');

        $existing = DiscoveredUrl::where('shop_id', $shopId)
            ->where('normalized_url', $normalized)
            ->first();

        if ($existing !== null) {
            if ($existing->shop_book_id !== $shopBookId) {
                $existing->shop_book_id = $shopBookId;
            }
            if ($existing->url_type === 'unknown') {
                $existing->url_type = $targetType;
            } elseif ($existing->url_type === 'product_partial' && !$isPartial) {
                $existing->url_type = 'product';
            }
            $existing->last_seen_at = $now;
            if ($runId !== null) {
                $existing->last_seen_run_id = $runId;
            }
            $existing->save();

            return $existing;
        }

        $record = new DiscoveredUrl();
        $record->shop_id = $shopId;
        $record->url = $url;
        $record->normalized_url = $normalized;
        // Python hardcodes 'category' on this path: the row only gets
        // created here when a shop_book was persisted without discovery
        // having seen the URL first.
        $record->source = 'category';
        $record->url_type = $targetType;
        $record->first_seen_at = $now;
        $record->last_seen_at = $now;
        $record->last_seen_run_id = $runId;
        $record->shop_book_id = $shopBookId;
        $record->save();

        return $record;
    }

    /**
     * Stamp a URL as `non_product` after a successful scrape decided it is
     * not a book, recording the classifier's score for the dashboard.
     *
     * Never demotes an established `product` row: a shop can serve a bad
     * page transiently, and losing a real product to one odd response would
     * take it out of the delta scan entirely.
     */
    public function markNonProduct(
        int $shopId,
        string $url,
        ?int $runId = null,
        int $bookScore = 0,
        array $reasons = [],
    ): ?DiscoveredUrl {
        $normalized = UrlUtils::normalize($url);
        $now = Carbon::now('UTC');

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

    /**
     * Mark every active shop_book for the shop whose URL is absent from
     * `$activeUrls` as inactive, stamping the transition time.
     *
     * Returns the number deactivated.
     */
    public function deactivateMissing(int $shopId, array $activeUrls): int
    {
        $now = Carbon::now('UTC');
        $deactivated = 0;

        // Chunked: a full shop can be 50k rows and the URL set is held in
        // memory by the caller already.
        \App\Models\ShopBook::where('shop_id', $shopId)
            ->where('is_active', true)
            ->select(['id', 'url'])
            ->chunkById(1000, function ($books) use ($activeUrls, $now, &$deactivated): void {
                $stale = $books
                    ->reject(fn ($book): bool => isset($activeUrls[$book->url]))
                    ->pluck('id')
                    ->all();
                if ($stale !== []) {
                    \App\Models\ShopBook::whereIn('id', $stale)
                        ->update(['is_active' => false, 'inactive_since' => $now]);
                    $deactivated += count($stale);
                }
            });

        return $deactivated;
    }
}
