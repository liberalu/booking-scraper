<?php

declare(strict_types=1);

namespace App\Support;

use App\Models\DiscoveredUrl;
use App\Models\Price;
use App\Models\ScrapeRun;
use App\Models\ShopBook;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * Port of the aggregate queries in book_scraper/dashboard/queries.py.
 *
 * Counts here are deliberately over ALL shop_books, not just active ones —
 * that is what the Python does, and the overview numbers are compared
 * against it field by field.
 */
final class Queries
{
    private const COMPLETENESS_FIELDS = ['author', 'isbn', 'publisher', 'year', 'format'];

    /**
     * Page count, floored at 1 — `max(1, (total + per_page - 1) // per_page)`,
     * which is what all seven paginated handlers in
     * book_scraper/dashboard/routes/api.py do.
     *
     * The `/api/books` list is the lone exception: it comes from
     * queries.py::list_books, which has no floor and reports ZERO pages for an
     * empty result. BooksController therefore computes its own rather than
     * calling this. Do not "unify" the two — the difference is observable in
     * the API and the SPA consumes both as they are.
     */
    public static function pageCount(int $total, int $perPage): int
    {
        return $total ? max(1, intdiv($total + $perPage - 1, $perPage)) : 1;
    }

    /** @return array<string, int> */
    public static function overviewStats(): array
    {
        return [
            'total_shop_books' => ShopBook::count(),
            'active_shop_books' => ShopBook::where('is_active', true)->count(),
            'with_isbn' => ShopBook::whereNotNull('isbn')->count(),
            'total_prices' => Price::count(),
        ];
    }

    /** @return list<array{field: string, present: int, total: int, pct: float}> */
    public static function dataCompleteness(): array
    {
        $total = ShopBook::count();
        if ($total === 0) {
            return [];
        }

        $out = [];
        foreach (self::COMPLETENESS_FIELDS as $field) {
            $present = ShopBook::whereNotNull($field)->count();
            $out[] = [
                'field' => $field,
                'present' => $present,
                'total' => $total,
                'pct' => round($present / $total * 100, 1),
            ];
        }

        return $out;
    }

    /** Items scraped per day for the last N days, oldest first, zeros filled. */
    public static function scrapeActivityByDay(int $days = 14): array
    {
        $cutoff = Carbon::now('UTC')->subDays($days);

        $rows = DB::select(
            "select date(started_at at time zone 'UTC') as day,
                    sum(items_added + items_updated) as items
             from scrape_runs
             where started_at >= ? and status = 'completed'
             group by day
             order by day",
            [$cutoff]
        );

        $byDay = [];
        foreach ($rows as $row) {
            $byDay[(string) $row->day] = (int) $row->items;
        }

        $out = [];
        for ($i = 0; $i < $days; $i++) {
            $day = Carbon::now('UTC')->subDays($days - 1 - $i)->toDateString();
            $out[] = $byDay[$day] ?? 0;
        }

        return $out;
    }

    /** @return array<string, int> */
    public static function shopStats(int $shopId): array
    {
        return [
            'shop_books' => ShopBook::where('shop_id', $shopId)->count(),
            'active' => ShopBook::where('shop_id', $shopId)->where('is_active', true)->count(),
            'discovered_urls' => DiscoveredUrl::where('shop_id', $shopId)->count(),
            'prices' => Price::whereIn(
                'shop_book_id',
                ShopBook::select('id')->where('shop_id', $shopId)
            )->count(),
        ];
    }

    /**
     * `state = 'open'` maps to lifecycle_state 'new', matching Python.
     *
     * @return list<array{issue_type: string, count: int}>
     */
    public static function validationSummary(?string $state = null): array
    {
        $query = DB::table('validation_issues')
            ->select('issue', DB::raw('count(id) as count'))
            ->groupBy('issue')
            ->orderByDesc(DB::raw('count(id)'));

        if (in_array($state, ['new', 'acknowledged', 'snoozed', 'resolved'], true)) {
            $query->where('lifecycle_state', $state);
        } elseif ($state === 'open') {
            $query->where('lifecycle_state', 'new');
        }

        return $query->get()
            ->map(fn ($row): array => [
                'issue_type' => (string) $row->issue,
                'count' => (int) $row->count,
            ])
            ->all();
    }

    /** Bulk done+failed counts, keyed by run id. @return array<int, int> */
    public static function runTerminalCounts(array $runIds): array
    {
        if ($runIds === []) {
            return [];
        }

        return DB::table('scrape_url_items')
            ->select('run_id', DB::raw('count(id) as c'))
            ->whereIn('run_id', $runIds)
            ->whereIn('status', ['done', 'failed'])
            ->groupBy('run_id')
            ->pluck('c', 'run_id')
            ->map(fn ($v): int => (int) $v)
            ->all();
    }

    /** Scan runs whose STARTED event carries rescrape=true. @return array<int, bool> */
    public static function rescrapeFlags(array $runIds): array
    {
        if ($runIds === []) {
            return [];
        }

        $rows = DB::select(
            "select run_id, (payload->>'rescrape')::boolean as flag
             from scrape_run_events
             where event_type = 'started' and run_id = any(?)",
            ['{' . implode(',', array_map('intval', $runIds)) . '}']
        );

        $out = [];
        foreach ($rows as $row) {
            if ($row->flag) {
                $out[(int) $row->run_id] = true;
            }
        }

        return $out;
    }

    /** @return \Illuminate\Database\Eloquent\Collection<int, ScrapeRun> */
    public static function recentRuns(int $limit = 20)
    {
        return ScrapeRun::with('shop')->orderByDesc('started_at')->limit($limit)->get();
    }
}
