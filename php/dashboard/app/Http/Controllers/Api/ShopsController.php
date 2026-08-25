<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\Queries;
use Illuminate\Support\Facades\DB;
use App\Support\RunPresenter;
use BookScraper\Config;
use BookScraper\Models\Shop;
use BookScraper\Models\ShopBook;
use Throwable;

/**
 * GET /api/shops — one card per shop, including which discover strategies
 * are actually wired up in that shop's TOML (the run dialog renders only
 * the options that will work: pegasas has graphql+lupasearch but no
 * sitemap/categories).
 */
final class ShopsController
{
    /** Order matches the run dialog: cheap-and-fast first, slowest last. */
    private const STRATEGY_ORDER = [
        'sitemap', 'categories', 'graphql', 'lupasearch', 'ibiblioteka_api', 'full_crawl',
    ];

    public function index(): array
    {
        $shops = Shop::orderBy('name')->get()->map(function (Shop $shop): array {
            $stats = Queries::shopStats($shop->id);
            $last = $shop->scrapeRuns()->orderByDesc('started_at')->first();

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
                'discover_strategies' => self::strategies($shop->name),
            ];
        })->all();

        return ['shops' => $shops];
    }

    /** @return list<string> */
    private static function strategies(string $shopName): array
    {
        try {
            $config = Config::forShop($shopName);
        } catch (Throwable) {
            // A shop row with no TOML shouldn't break the shop list.
            return [];
        }

        return array_values(array_filter(
            self::STRATEGY_ORDER,
            static fn (string $name): bool => $config->hasStrategy($name)
        ));
    }

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function show(string $shopName): mixed
    {
        $shop = Shop::where('name', $shopName)->first();
        if ($shop === null) {
            return response()->json(['detail' => 'Shop not found'], 404);
        }

        $stats = Queries::shopStats($shop->id);
        $runs = $shop->scrapeRuns()->with('shop')->orderByDesc('started_at')->limit(20)->get();
        $last = $runs->first();

        $runIds = $runs->pluck('id')->all();
        $terminal = Queries::runTerminalCounts($runIds);
        $rescrape = Queries::rescrapeFlags($runIds);

        return [
            'id' => $shop->id,
            'name' => $shop->name,
            'base_url' => $shop->base_url,
            ...$stats,
            // Alias kept for the card header, which reads `books`.
            'books' => $stats['shop_books'],
            'last_run_ago' => RunPresenter::relative($last?->started_at),
            'last_run_status' => $last->status ?? '—',
            'field_stats' => self::fieldStats($shop->id),
            'recent_runs' => $runs->map(fn ($run): array => RunPresenter::toArray(
                $run,
                terminalCount: $terminal[$run->id] ?? null,
                rescrape: $rescrape[$run->id] ?? false,
            ))->all(),
            // Operator overrides applied without a redeploy; the middleware
            // reads these ahead of the TOML.
            // ?: new stdClass — see the note in ShopBooksController: an empty
            // key-value map must stay {} in JSON, not become [].
            'rate_settings' => DB::table('shop_settings')
                ->where('shop_id', $shop->id)
                ->pluck('value', 'key')
                ->all() ?: new \stdClass(),
            'discover_strategies' => self::strategies($shop->name),
        ];
    }

    /**
     * Per-field completeness. Counted over ALL of the shop's books, not just
     * the active ones, so the number does not move when a listing is
     * delisted.
     *
     * @return array{total: int, fields: array<string, array{missing: int, present: int}>}
     */
    private static function fieldStats(int $shopId): array
    {
        $total = ShopBook::where('shop_id', $shopId)->count();

        $fields = [];
        foreach (['author', 'isbn', 'year', 'publisher', 'format', 'description', 'image_url'] as $field) {
            $missing = ShopBook::where('shop_id', $shopId)->whereNull($field)->count();
            $fields[$field] = ['missing' => $missing, 'present' => $total - $missing];
        }

        return ['total' => $total, 'fields' => $fields];
    }
}
