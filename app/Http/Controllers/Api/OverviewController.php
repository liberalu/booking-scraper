<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\Queries;
use App\Support\RunPresenter;
use App\Models\Shop;

/**
 * GET /api/overview — the landing page payload.
 *
 * Shape must match the Python endpoint exactly: the React SPA is served
 * unchanged from book_scraper/dashboard/static/hifi and reads these keys.
 */
final class OverviewController
{
    public function __invoke(): array
    {
        $stats = Queries::overviewStats();
        $clusters = Queries::validationSummary('open');
        $recentRuns = Queries::recentRuns(10);

        $runIds = $recentRuns->pluck('id')->all();
        $terminal = Queries::runTerminalCounts($runIds);
        $rescrape = Queries::rescrapeFlags($runIds);

        $shopCards = Shop::orderBy('name')->get()->map(function (Shop $shop): array {
            $stats = Queries::shopStats($shop->id);
            $last = $shop->scrapeRuns()->orderByDesc('started_at')->first();

            return [
                'name' => $shop->name,
                'books' => $stats['shop_books'],
                'active' => $stats['active'],
                // Python hardcodes 0 here; per-shop issue counts are
                // fetched separately by the shop detail page.
                'issues' => 0,
                'last_run_ago' => RunPresenter::relative($last?->started_at),
                'last_run_status' => $last->status ?? '—',
            ];
        })->all();

        return [
            'stats' => [
                ...$stats,
                'open_issues' => array_sum(array_column($clusters, 'count')),
            ],
            'completeness' => array_map(
                static fn (array $c): array => ['field' => $c['field'], 'pct' => $c['pct']],
                Queries::dataCompleteness()
            ),
            'recent_runs' => $recentRuns->map(fn ($run): array => RunPresenter::toArray(
                $run,
                terminalCount: $terminal[$run->id] ?? null,
                rescrape: $rescrape[$run->id] ?? false,
            ))->all(),
            'issue_clusters' => array_slice($clusters, 0, 6),
            'shops' => $shopCards,
            'activity' => Queries::scrapeActivityByDay(14),
        ];
    }
}
