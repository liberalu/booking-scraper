<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ScrapeRun;
use App\Models\Shop;
use App\Support\Config;
use App\Support\RunPresenter;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;
use stdClass;
use Throwable;

final class ShopReadRepository
{
    public function __construct(
        private readonly DashboardStatisticsRepository $statistics = new DashboardStatisticsRepository,
    ) {}

    private const array STRATEGY_ORDER = [
        'sitemap', 'categories', 'graphql', 'lupasearch', 'ibiblioteka_api', 'full_crawl',
    ];

    /** @return array<string, mixed> */
    public function index(): array
    {
        $shops = Shop::with('latestScrapeRun')->get()->sortBy('name')->map(function (Shop $shop): array {
            $stats = $this->statistics->shopStats($shop->id);
            $last = $shop->latestScrapeRun;

            return [
                'id' => $shop->id,
                'name' => $shop->name,
                'base_url' => $shop->base_url,
                'books' => $stats['shop_books'],
                'active' => $stats['active'],
                'discovered_urls' => $stats['discovered_urls'],
                'prices' => $stats['prices'],
                'last_run_ago' => RunPresenter::relative($last?->started_at),
                'last_run_status' => $last->status ?? '—',
                'discover_strategies' => $this->strategies($shop->name),
            ];
        })->all();

        return ['shops' => $shops];
    }

    /** @return list<string> */
    private function strategies(string $shopName): array
    {
        try {
            $config = Config::forShop($shopName);
        } catch (Throwable) {

            return [];
        }

        return array_values(array_filter(
            self::STRATEGY_ORDER,
            $config->hasStrategy(...)
        ));
    }

    /** @return array<string, mixed> */
    public function show(Shop $shop): array
    {
        $stats = $this->statistics->shopStats($shop->id);
        $runIds = array_values(DB::table('scrape_runs')
            ->where('shop_id', $shop->id)
            ->orderByDesc('started_at')
            ->limit(20)
            ->pluck('id')
            ->map(static fn (mixed $id): int => DatabaseRow::from(['id' => $id])->int('id'))
            ->all());
        $runsById = ScrapeRun::whereIn('id', $runIds)->with('shop')->get()->keyBy('id');
        $runs = Collection::make($runIds)
            ->map(static fn (int $id): ?ScrapeRun => $runsById->get($id))
            ->filter(static fn (?ScrapeRun $run): bool => $run !== null)
            ->values();
        $last = $runs->first();

        $terminal = $this->statistics->runTerminalCounts($runIds);
        $rescrape = $this->statistics->rescrapeFlags($runIds);

        $rateSettings = DB::table('shop_settings')
            ->where('shop_id', $shop->id)
            ->pluck('value', 'key')
            ->all();

        return [
            'id' => $shop->id,
            'name' => $shop->name,
            'base_url' => $shop->base_url,
            ...$stats,

            'books' => $stats['shop_books'],
            'last_run_ago' => RunPresenter::relative($last?->started_at),
            'last_run_status' => $last->status ?? '—',
            'field_stats' => $this->fieldStats($shop->id),
            'recent_runs' => $runs->map(fn (ScrapeRun $run): array => RunPresenter::toArray(
                $run,
                terminalCount: $terminal[$run->id] ?? null,
                rescrape: $rescrape[$run->id] ?? false,
            ))->all(),

            'rate_settings' => $rateSettings === [] ? new stdClass : $rateSettings,
            'discover_strategies' => $this->strategies($shop->name),
        ];
    }

    /** @return array{total: int, fields: array<string, array{missing: int, present: int}>} */
    private function fieldStats(int $shopId): array
    {
        $row = DatabaseRow::from(DB::table('shop_books')
            ->where('shop_id', $shopId)
            ->selectRaw('count(*) as total')
            ->selectRaw('count(*) filter (where author is null) as author_missing')
            ->selectRaw('count(*) filter (where isbn is null) as isbn_missing')
            ->selectRaw('count(*) filter (where year is null) as year_missing')
            ->selectRaw('count(*) filter (where publisher is null) as publisher_missing')
            ->selectRaw('count(*) filter (where format is null) as format_missing')
            ->selectRaw('count(*) filter (where description is null) as description_missing')
            ->selectRaw('count(*) filter (where image_url is null) as image_url_missing')
            ->first());
        $total = $row->int('total');
        $fields = [];
        foreach (['author', 'isbn', 'year', 'publisher', 'format', 'description', 'image_url'] as $field) {
            $missing = $row->int("{$field}_missing");
            $fields[$field] = ['missing' => $missing, 'present' => $total - $missing];
        }

        return ['total' => $total, 'fields' => $fields];
    }
}
