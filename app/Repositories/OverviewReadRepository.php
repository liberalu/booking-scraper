<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ScrapeRun;
use App\Models\Shop;
use App\Support\RunPresenter;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final class OverviewReadRepository
{
    public function __construct(
        private readonly DashboardStatisticsRepository $statistics = new DashboardStatisticsRepository,
    ) {}

    /** @return array<string, mixed> */
    public function __invoke(): array
    {
        $stats = $this->statistics->overviewStats();
        $clusters = $this->statistics->validationSummary('open');
        $recentRuns = $this->statistics->recentRuns(10);

        $runIds = array_map(static fn (ScrapeRun $run): int => $run->id, $recentRuns);
        $terminal = $this->statistics->runTerminalCounts($runIds);
        $rescrape = $this->statistics->rescrapeFlags($runIds);

        $shopCards = Shop::orderBy('name')->get()->map(function (Shop $shop): array {
            $stats = $this->statistics->shopStats($shop->id);
            $last = DatabaseRow::nullable(DB::table('scrape_runs')
                ->where('shop_id', $shop->id)
                ->orderByDesc('started_at')
                ->first());
            $startedAt = $last?->nullableString('started_at');

            return [
                'name' => $shop->name,
                'books' => $stats['shop_books'],
                'active' => $stats['active'],

                'issues' => 0,
                'last_run_ago' => RunPresenter::relative(
                    $startedAt === null ? null : Carbon::parse($startedAt),
                ),
                'last_run_status' => $last?->nullableString('status') ?? '—',
            ];
        })->all();

        return [
            'stats' => [
                ...$stats,
                'open_issues' => array_sum(array_column($clusters, 'count')),
            ],
            'completeness' => array_map(
                static fn (array $c): array => ['field' => $c['field'], 'pct' => $c['pct']],
                $this->statistics->dataCompleteness()
            ),
            'recent_runs' => array_map(
                static fn (ScrapeRun $run): array => RunPresenter::toArray(
                    $run,
                    terminalCount: $terminal[$run->id] ?? null,
                    rescrape: $rescrape[$run->id] ?? false,
                ),
                $recentRuns,
            ),
            'issue_clusters' => array_slice($clusters, 0, 6),
            'shops' => $shopCards,
            'activity' => $this->statistics->scrapeActivityByDay(14),
        ];
    }
}
