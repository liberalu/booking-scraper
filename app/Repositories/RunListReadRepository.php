<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\RunQueryInput;
use App\Models\ScrapeRun;
use App\Support\Queries;
use App\Support\RunPresenter;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final readonly class RunListReadRepository
{
    private const array WHEN_BOUNDS_HOURS = ['1h' => 1, '24h' => 24, '7d' => 168, '30d' => 720];

    private const array EXACT_PHASES = ['scan', 'discover_sitemap', 'discover_categories', 'discover_full_crawl'];

    public function __construct(
        private DashboardStatisticsRepository $statistics = new DashboardStatisticsRepository,
    ) {}

    /** @return array<string, mixed> */
    public function index(RunQueryInput $input): array
    {
        $shop = $input->shop ?? 'all';
        $phase = $input->phase ?? 'all';
        $status = $input->status ?? 'all';
        $when = $input->when ?? 'any';
        $search = $input->search;
        $perPage = max(1, min($input->perPage ?? 30, 200));
        $page = max(1, $input->page ?? 1);
        $query = DB::table('scrape_runs')
            ->join('shops', 'scrape_runs.shop_id', '=', 'shops.id')
            ->orderByDesc('scrape_runs.started_at');

        if ($shop !== '' && $shop !== 'all') {
            $query->where('shops.name', $shop);
        }
        if ($phase !== '' && $phase !== 'all') {
            if ($phase === 'discover') {
                $query->where('scrape_runs.phase', 'like', 'discover\_%');
            } elseif (in_array($phase, self::EXACT_PHASES, true)) {
                $query->where('scrape_runs.phase', $phase);
            } else {
                $query->whereRaw('false');
            }
        }
        if ($status !== '' && $status !== 'all') {
            $query->where('scrape_runs.status', $status);
        }
        if (isset(self::WHEN_BOUNDS_HOURS[$when])) {
            $query->where('scrape_runs.started_at', '>=', Carbon::now('UTC')->subHours(self::WHEN_BOUNDS_HOURS[$when]));
        }
        if ($search !== '') {
            $like = "%{$search}%";
            $query->where(function (Builder $nested) use ($like, $search): void {
                $nested->where('shops.name', 'ilike', $like)
                    ->orWhereRaw('scrape_runs.phase::text ilike ?', [$like]);
                if (ctype_digit($search)) {
                    $nested->orWhere('scrape_runs.id', (int) $search);
                }
            });
        }

        $total = (clone $query)->count('scrape_runs.id');
        $runIds = [];
        foreach ($query->offset(($page - 1) * $perPage)->limit($perPage)->pluck('scrape_runs.id') as $rawId) {
            $runIds[] = DatabaseRow::from(['id' => $rawId])->int('id');
        }
        $runsById = ScrapeRun::whereIn('id', $runIds)->with('shop')->get()->keyBy('id');
        $runs = [];
        foreach ($runIds as $runId) {
            $run = $runsById->get($runId);
            if ($run instanceof ScrapeRun) {
                $runs[] = $run;
            }
        }
        $terminal = $this->statistics->runTerminalCounts($runIds);
        $validationCounts = $this->validationIssueCounts($runIds);
        $itemCounts = $this->itemCounts($runIds);
        $rescrape = $this->statistics->rescrapeFlags($runIds);
        $todayCutoff = Carbon::now('UTC')->subHours(24);

        return [
            'runs' => array_map(
                static fn (ScrapeRun $run): array => RunPresenter::toArray(
                    $run,
                    terminalCount: DatabaseRow::from(['value' => $terminal[$run->id] ?? null])->nullableInt('value'),
                    validationIssues: $validationCounts[$run->id] ?? 0,
                    itemsAdded: $itemCounts[$run->id]['items_added'] ?? null,
                    itemsUpdated: $itemCounts[$run->id]['items_updated'] ?? null,
                    rescrape: self::boolean($rescrape[$run->id] ?? false),
                ),
                $runs,
            ),
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($total, $perPage),
            'kpis' => [
                'running_now' => DB::table('scrape_runs')->where('status', 'running')->count(),
                'today_total' => DB::table('scrape_runs')->where('started_at', '>=', $todayCutoff)->count(),
                'today_ok' => DB::table('scrape_runs')->where('started_at', '>=', $todayCutoff)->where('status', 'completed')->count(),
                'today_failed' => DB::table('scrape_runs')->where('started_at', '>=', $todayCutoff)->where('status', 'failed')->count(),
                'all_time' => DB::table('scrape_runs')->count(),
            ],
        ];
    }

    /**
     * @param  list<int>  $runIds
     * @return array<int, int>
     */
    private function validationIssueCounts(array $runIds): array
    {
        if ($runIds === []) {
            return [];
        }
        $counts = [];
        foreach (DB::table('validation_issues')
            ->select('last_seen_run_id', DB::raw('count(id) as c'))
            ->whereIn('last_seen_run_id', $runIds)
            ->groupBy('last_seen_run_id')
            ->get() as $raw) {
            $row = DatabaseRow::from($raw);
            $counts[$row->int('last_seen_run_id')] = $row->int('c');
        }

        return $counts;
    }

    /**
     * @param  list<int>  $runIds
     * @return array<int, array{items_added: int, items_updated: int}>
     */
    private function itemCounts(array $runIds): array
    {
        if ($runIds === []) {
            return [];
        }
        $added = [];
        foreach (DB::table('shop_books')->select('created_run_id', DB::raw('count(id) as c'))
            ->whereIn('created_run_id', $runIds)->groupBy('created_run_id')->get() as $raw) {
            $row = DatabaseRow::from($raw);
            $added[$row->int('created_run_id')] = $row->int('c');
        }
        $updated = [];
        foreach (DB::table('shop_book_changes')->select('scrape_run_id', DB::raw('count(distinct shop_book_id) as c'))
            ->whereIn('scrape_run_id', $runIds)->groupBy('scrape_run_id')->get() as $raw) {
            $row = DatabaseRow::from($raw);
            $updated[$row->int('scrape_run_id')] = $row->int('c');
        }
        $counts = [];
        foreach ($runIds as $runId) {
            $counts[$runId] = ['items_added' => $added[$runId] ?? 0, 'items_updated' => $updated[$runId] ?? 0];
        }

        return $counts;
    }

    private static function boolean(mixed $value): bool
    {
        return $value === true || $value === 1 || $value === '1' || $value === 't' || $value === 'true';
    }
}
