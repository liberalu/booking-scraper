<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ScrapeRun;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;

final class DashboardStatisticsRepository
{
    private const array COMPLETENESS_FIELDS = ['author', 'isbn', 'publisher', 'year', 'format'];

    /** @return array{total_shop_books: int, active_shop_books: int, with_isbn: int, total_prices: int} */
    public function overviewStats(): array
    {
        $row = DatabaseRow::from(DB::selectOne(
            'select
                (select count(*) from shop_books) as total_shop_books,
                (select count(*) from shop_books where is_active = true) as active_shop_books,
                (select count(*) from shop_books where isbn is not null) as with_isbn,
                (select count(*) from prices) as total_prices'
        ));

        return [
            'total_shop_books' => $row->int('total_shop_books'),
            'active_shop_books' => $row->int('active_shop_books'),
            'with_isbn' => $row->int('with_isbn'),
            'total_prices' => $row->int('total_prices'),
        ];
    }

    /** @return list<array{field: string, present: int, total: int, pct: float}> */
    public function dataCompleteness(): array
    {
        $row = DatabaseRow::from(DB::selectOne(
            'select count(*) as total, count(author) as author, count(isbn) as isbn,
                    count(publisher) as publisher, count(year) as year, count(format) as format
               from shop_books'
        ));
        $total = $row->int('total');
        if ($total === 0) {
            return [];
        }

        $out = [];
        foreach (self::COMPLETENESS_FIELDS as $field) {
            $present = $row->int($field);
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
        $cutoff = Date::now('UTC')->subDays($days);

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
            $day = Date::now('UTC')->subDays($days - 1 - $i)->toDateString();
            $out[] = $byDay[$day] ?? 0;
        }

        return $out;
    }

    /** @return array{shop_books: int, active: int, discovered_urls: int, prices: int} */
    public function shopStats(int $shopId): array
    {
        $stats = $this->shopStatsByShop()[$shopId] ?? [
            'shop_books' => 0,
            'active' => 0,
            'discovered_urls' => 0,
            'prices' => 0,
            'issues' => 0,
        ];

        return [
            'shop_books' => $stats['shop_books'],
            'active' => $stats['active'],
            'discovered_urls' => $stats['discovered_urls'],
            'prices' => $stats['prices'],
        ];
    }

    /** @return array<int, array{shop_books: int, active: int, discovered_urls: int, prices: int, issues: int}> */
    public function shopStatsByShop(): array
    {
        $bookStats = DB::table('shop_books')
            ->select('shop_id')
            ->selectRaw('count(*) as shop_books')
            ->selectRaw('count(*) filter (where is_active = true) as active')
            ->groupBy('shop_id');
        $urlStats = DB::table('discovered_urls')
            ->select('shop_id')->selectRaw('count(*) as discovered_urls')->groupBy('shop_id');
        $priceStats = DB::table('prices as p')
            ->join('shop_books as sb', 'sb.id', '=', 'p.shop_book_id')
            ->select('sb.shop_id')->selectRaw('count(*) as prices')->groupBy('sb.shop_id');
        $issueStats = DB::table('validation_issues')
            ->select('shop_id')->selectRaw('count(*) as issues')
            ->where('lifecycle_state', 'new')->groupBy('shop_id');

        $stats = [];
        foreach (DB::table('shops as s')
            ->leftJoinSub($bookStats, 'bs', 'bs.shop_id', '=', 's.id')
            ->leftJoinSub($urlStats, 'us', 'us.shop_id', '=', 's.id')
            ->leftJoinSub($priceStats, 'ps', 'ps.shop_id', '=', 's.id')
            ->leftJoinSub($issueStats, 'isx', 'isx.shop_id', '=', 's.id')
            ->get([
                's.id', 'bs.shop_books', 'bs.active', 'us.discovered_urls', 'ps.prices', 'isx.issues',
            ]) as $raw) {
            $row = DatabaseRow::from($raw);
            $stats[$row->int('id')] = [
                'shop_books' => $row->nullableInt('shop_books') ?? 0,
                'active' => $row->nullableInt('active') ?? 0,
                'discovered_urls' => $row->nullableInt('discovered_urls') ?? 0,
                'prices' => $row->nullableInt('prices') ?? 0,
                'issues' => $row->nullableInt('issues') ?? 0,
            ];
        }

        return $stats;
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
            ->latest('started_at')
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
