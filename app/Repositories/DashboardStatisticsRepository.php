<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ScrapeRun;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final class DashboardStatisticsRepository
{
    private const COMPLETENESS_FIELDS = ['author', 'isbn', 'publisher', 'year', 'format'];

    /** @return array{total_shop_books: int, active_shop_books: int, with_isbn: int, total_prices: int} */
    public function overviewStats(): array
    {
        return [
            'total_shop_books' => DB::table('shop_books')->count(),
            'active_shop_books' => DB::table('shop_books')->where('is_active', true)->count(),
            'with_isbn' => DB::table('shop_books')->whereNotNull('isbn')->count(),
            'total_prices' => DB::table('prices')->count(),
        ];
    }

    /** @return list<array{field: string, present: int, total: int, pct: float}> */
    public function dataCompleteness(): array
    {
        $total = DB::table('shop_books')->count();
        if ($total === 0) {
            return [];
        }

        $out = [];
        foreach (self::COMPLETENESS_FIELDS as $field) {
            $present = DB::table('shop_books')->whereNotNull($field)->count();
            $out[] = [
                'field' => $field,
                'present' => $present,
                'total' => $total,
                'pct' => round($present / $total * 100, 1),
            ];
        }

        return $out;
    }

    /** @return list<int> */
    public function scrapeActivityByDay(int $days = 14): array
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
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $byDay[$row->string('day')] = $row->int('items');
        }

        $out = [];
        for ($i = 0; $i < $days; $i++) {
            $day = Carbon::now('UTC')->subDays($days - 1 - $i)->toDateString();
            $out[] = $byDay[$day] ?? 0;
        }

        return $out;
    }

    /** @return array{shop_books: int, active: int, discovered_urls: int, prices: int} */
    public function shopStats(int $shopId): array
    {
        $shopBookIds = DB::table('shop_books')->select('id')->where('shop_id', $shopId);

        return [
            'shop_books' => DB::table('shop_books')->where('shop_id', $shopId)->count(),
            'active' => DB::table('shop_books')->where('shop_id', $shopId)->where('is_active', true)->count(),
            'discovered_urls' => DB::table('discovered_urls')->where('shop_id', $shopId)->count(),
            'prices' => DB::table('prices')->whereIn('shop_book_id', $shopBookIds)->count(),
        ];
    }

    /** @return list<array{issue_type: string, count: int}> */
    public function validationSummary(?string $state = null): array
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

        $summary = [];
        foreach ($query->get() as $raw) {
            $row = DatabaseRow::from($raw);
            $summary[] = [
                'issue_type' => $row->string('issue'),
                'count' => $row->int('count'),
            ];
        }

        return $summary;
    }

    /**
     * @param  list<int>  $runIds
     * @return array<int, int>
     */
    public function runTerminalCounts(array $runIds): array
    {
        if ($runIds === []) {
            return [];
        }

        $rows = DB::table('scrape_url_items')
            ->select('run_id', DB::raw('count(id) as c'))
            ->whereIn('run_id', $runIds)
            ->whereIn('status', ['done', 'failed'])
            ->groupBy('run_id')
            ->get();
        $counts = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $counts[$row->int('run_id')] = $row->int('c');
        }

        return $counts;
    }

    /**
     * @param  list<int>  $runIds
     * @return array<int, true>
     */
    public function rescrapeFlags(array $runIds): array
    {
        if ($runIds === []) {
            return [];
        }

        $rows = DB::table('scrape_run_events')
            ->select('run_id')
            ->selectRaw("(payload->>'rescrape')::boolean as flag")
            ->where('event_type', 'started')
            ->whereIn('run_id', $runIds)
            ->get();

        $out = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            if ($row->nullableBool('flag') === true) {
                $out[$row->int('run_id')] = true;
            }
        }

        return $out;
    }

    /** @return list<ScrapeRun> */
    public function recentRuns(int $limit = 20): array
    {
        $rawIds = DB::table('scrape_runs')
            ->orderByDesc('started_at')
            ->limit($limit)
            ->pluck('id')
            ->all();
        $ids = [];
        foreach ($rawIds as $rawId) {
            $ids[] = DatabaseRow::from(['id' => $rawId])->int('id');
        }
        $models = ScrapeRun::whereIn('id', $ids)->with('shop')->get()->keyBy('id');
        $runs = [];
        foreach ($ids as $id) {
            $run = $models->get($id);
            if ($run instanceof ScrapeRun) {
                $runs[] = $run;
            }
        }

        return $runs;
    }
}
