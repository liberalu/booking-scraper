<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\CrawlSpawner;
use BookScraper\Models\Shop;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Throwable;

/**
 * The form endpoints that predate the SPA.
 *
 * They live outside `/api`, answer with HTML or a 303 redirect rather than
 * JSON, and are still wired to the server-rendered pages. Ported because they
 * work in the stack this replaces — `rate-settings` in particular is the
 * operator's only UI for the `shop_settings` override, so dropping it would
 * take away the one control that needs no redeploy.
 */
final class LegacyFormsController
{
    /** Above this, a filtered rescrape is refused rather than run. */
    private const MAX_FILTERED_URLS = 5000;

    private const DELAY_MIN = 0.1;

    private const DELAY_MAX = 60.0;

    private const CONCURRENCY_MIN = 1;

    private const CONCURRENCY_MAX = 16;

    /** Per-shop rate limits, written to `shop_settings`. */
    public function rateSettings(Request $request, string $shopName): mixed
    {
        $shop = Shop::where('name', $shopName)->first();
        if ($shop === null) {
            return response('<p class="error">Shop not found</p>', 404)
                ->header('Content-Type', 'text/html; charset=utf-8');
        }

        $delay = (float) $request->input('download_delay');
        $concurrency = (int) $request->input('concurrent_requests_per_domain');

        if ($delay < self::DELAY_MIN || $delay > self::DELAY_MAX) {
            return response('<p class="error">download_delay must be 0.1–60 s</p>', 400)
                ->header('Content-Type', 'text/html; charset=utf-8');
        }
        if ($concurrency < self::CONCURRENCY_MIN || $concurrency > self::CONCURRENCY_MAX) {
            return response(
                '<p class="error">concurrent_requests_per_domain must be 1–16</p>',
                400
            )->header('Content-Type', 'text/html; charset=utf-8');
        }

        // Python renders the floats through str(), so 2.0 is stored as "2.0"
        // and the stored string round-trips to the same value.
        self::upsertSetting($shop->id, 'download_delay', self::pyFloat($delay), 'float');
        self::upsertSetting(
            $shop->id,
            'concurrent_requests_per_domain',
            (string) $concurrency,
            'int'
        );

        return response('<p class="success">Saved.</p>')
            ->header('Content-Type', 'text/html; charset=utf-8');
    }

    /** Re-scrape one discovered URL. */
    public function scrapeUrl(int $urlId): mixed
    {
        $row = DB::table('discovered_urls')->where('id', $urlId)->first(['url', 'shop_id']);
        if ($row === null) {
            return response()->json(['detail' => 'URL not found'], 404);
        }
        $shopName = Shop::whereKey($row->shop_id)->value('name');
        if ($shopName === null) {
            return response()->json(['detail' => 'Shop not found for URL'], 404);
        }

        try {
            CrawlSpawner::spawn('scan', (string) $shopName, urls: (string) $row->url);
        } catch (Throwable $e) {
            return response()->json(['detail' => $e->getMessage()], 503);
        }

        return redirect("/urls/{$urlId}?scraped=1", 303);
    }

    /** Re-scrape every URL still classified `unknown`. */
    public function scrapeUnknownUrls(Request $request): mixed
    {
        $shopName = (string) $request->query('shop', '');
        $shopId = $shopName === '' ? null : Shop::where('name', $shopName)->value('id');

        $query = DB::table('discovered_urls')->where('url_type', 'unknown');
        if ($shopId !== null) {
            $query->where('shop_id', $shopId);
        }
        $rows = $query->get(['url', 'shop_id']);

        if ($rows->isEmpty()) {
            return redirect(
                "/urls?shop={$shopName}&url_type=unknown&scrape_started=0",
                303
            );
        }

        $names = Shop::whereIn('id', $rows->pluck('shop_id')->unique()->all())
            ->pluck('name', 'id')
            ->all();

        $started = 0;
        foreach (self::groupByShop($rows, $names) as $shop => $urls) {
            try {
                CrawlSpawner::spawn('scan', $shop, urls: implode(',', $urls));
                $started += count($urls);
            } catch (Throwable $e) {
                return response()->json(['detail' => $e->getMessage()], 503);
            }
        }

        return redirect(
            "/urls?shop={$shopName}&url_type=unknown&scrape_started={$started}",
            303
        );
    }

    /**
     * Re-scrape whatever a shop-books filter matches.
     *
     * At least one filter is mandatory: without that this is a full-catalogue
     * rescrape behind a single POST.
     */
    public function scrapeFiltered(Request $request): mixed
    {
        $filters = [
            'shop' => (string) $request->query('shop', ''),
            'q' => (string) $request->query('q', ''),
            'author' => (string) $request->query('author', ''),
            'publisher' => (string) $request->query('publisher', ''),
            'category' => (string) $request->query('category', ''),
            'format' => (string) $request->query('format', ''),
            'missing' => (string) $request->query('missing', ''),
            'active' => (string) $request->query('active', ''),
        ];
        $hasIsbn = filter_var($request->query('has_isbn', false), FILTER_VALIDATE_BOOLEAN);

        if (!$hasIsbn && implode('', $filters) === '') {
            return response()->json([
                'detail' => 'At least one filter is required '
                    . '(shop/q/author/publisher/category/format/missing/active/'
                    . 'has_isbn/field filters)',
            ], 400);
        }

        $shopId = null;
        if ($filters['shop'] !== '') {
            $shopId = Shop::where('name', $filters['shop'])->value('id');
            if ($shopId === null) {
                return response()->json(
                    ['detail' => "Unknown shop: {$filters['shop']}"],
                    404
                );
            }
        }

        $pairs = $this->matchingShopBooks($filters, $hasIsbn, $shopId);
        if ($pairs === []) {
            return response()->json(['detail' => 'No shop_books matched the filters'], 404);
        }
        if (count($pairs) > self::MAX_FILTERED_URLS) {
            return response()->json([
                'detail' => sprintf(
                    'Filter matches %d+ shop_books — over the %d cap. Narrow the '
                    . 'filter, pick a shop, or run `scrapy crawl scan` for a full pass.',
                    count($pairs),
                    self::MAX_FILTERED_URLS
                ),
            ], 413);
        }

        $byShop = [];
        foreach ($pairs as [$shop, $url]) {
            $byShop[$shop][] = $url;
        }

        $jobs = [];
        foreach ($byShop as $shop => $urls) {
            try {
                $spawn = CrawlSpawner::spawn('scan', (string) $shop, urls: implode(',', $urls));
            } catch (Throwable $e) {
                return response()->json(['detail' => $e->getMessage()], 503);
            }
            $jobs[] = [
                'shop' => $shop,
                'urls_count' => count($urls),
                'pid' => $spawn['pid'],
                'command' => implode(' ', array_slice($spawn['cmd'], 0, 4))
                    . " --shop={$shop} --urls=<" . count($urls) . ' urls>',
            ];
        }

        if ($request->query('output') === 'json') {
            return response()->json(
                ['status' => 'started', 'urls_count' => count($pairs), 'jobs' => $jobs],
                202
            );
        }

        $back = array_filter($filters, static fn (string $v): bool => $v !== '');
        if ($hasIsbn) {
            $back['has_isbn'] = 'true';
        }
        $back['scrape_started'] = (string) count($pairs);

        return redirect('/shop-books?' . http_build_query($back), 303);
    }

    /**
     * @param  array<string, string>  $filters
     * @return list<array{0: string, 1: string}>  (shop name, url) pairs
     */
    private function matchingShopBooks(array $filters, bool $hasIsbn, ?int $shopId): array
    {
        $query = DB::table('shop_books as sb')
            ->join('shops as s', 's.id', '=', 'sb.shop_id');

        if ($shopId !== null) {
            $query->where('sb.shop_id', $shopId);
        }
        if ($filters['q'] !== '') {
            $term = '%' . $filters['q'] . '%';
            $query->where(function ($q) use ($term): void {
                $q->where('sb.title', 'ilike', $term)
                    ->orWhere('sb.author', 'ilike', $term);
            });
        }
        foreach (['author' => 'sb.author', 'publisher' => 'sb.publisher'] as $key => $column) {
            if ($filters[$key] !== '') {
                $query->where($column, 'ilike', '%' . $filters[$key] . '%');
            }
        }
        if ($filters['category'] !== '') {
            $query->whereRaw('? = any(sb.categories)', [$filters['category']]);
        }
        if ($filters['format'] !== '') {
            $query->where('sb.format', $filters['format']);
        }
        if ($filters['missing'] !== '' && preg_match('/^[a-z_]+$/', $filters['missing']) === 1) {
            $query->whereNull('sb.' . $filters['missing']);
        }
        if ($filters['active'] === 'true') {
            $query->where('sb.is_active', true);
        } elseif ($filters['active'] === 'false') {
            $query->where('sb.is_active', false);
        }
        if ($hasIsbn) {
            $query->whereNotNull('sb.isbn');
        }

        // One more than the cap: enough to know the cap was exceeded without
        // pulling the whole catalogue back.
        return $query
            ->orderBy('sb.id')
            ->limit(self::MAX_FILTERED_URLS + 1)
            ->get(['s.name as shop', 'sb.url'])
            ->map(static fn ($row): array => [(string) $row->shop, (string) $row->url])
            ->all();
    }

    /**
     * @param  \Illuminate\Support\Collection<int, object>  $rows
     * @param  array<int, string>  $names
     * @return array<string, list<string>>
     */
    private static function groupByShop($rows, array $names): array
    {
        $byShop = [];
        foreach ($rows as $row) {
            $name = $names[$row->shop_id] ?? '';
            if ($name !== '') {
                $byShop[$name][] = (string) $row->url;
            }
        }

        return $byShop;
    }

    private static function upsertSetting(int $shopId, string $key, string $value, string $type): void
    {
        DB::table('shop_settings')->updateOrInsert(
            ['shop_id' => $shopId, 'key' => $key],
            ['value' => $value, 'type' => $type],
        );
    }

    /** Python's `str(float)`: a whole value keeps its `.0`. */
    private static function pyFloat(float $value): string
    {
        $text = (string) json_encode($value);

        return str_contains($text, '.') || str_contains($text, 'e') ? $text : $text . '.0';
    }
}
