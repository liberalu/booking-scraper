<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ScrapeRun;
use App\Models\Shop;
use App\Support\RunPresenter;

final readonly class OverviewReadRepository
{
    public function __construct(
        private DashboardStatisticsRepository $statistics = new DashboardStatisticsRepository,
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

        $shopStats = $this->statistics->shopStatsByShop();
        $shopCards = Shop::query()->with('latestScrapeRun')->get()->sortBy('name')->map(function (Shop $shop) use ($shopStats): array {
            $stats = $shopStats[$shop->id] ?? [
                'shop_books' => 0, 'active' => 0, 'discovered_urls' => 0, 'prices' => 0,
                'issues' => 0,
            ];
            $last = $shop->latestScrapeRun;

            return [
                'name' => $shop->name,
                'books' => $stats['shop_books'],
                'active' => $stats['active'],

                'issues' => $stats['issues'],
                'last_run_ago' => RunPresenter::relative(
                    $last?->started_at,
                ),
                'last_run_status' => $last->status ?? '—',
            ];
        })->values()->all();

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
