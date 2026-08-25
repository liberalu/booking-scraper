<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\RunPresenter;
use BookScraper\Models\DiscoveredUrl;
use BookScraper\Models\Shop;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

/**
 * GET /api/urls — the discovered-URL ledger.
 *
 * url_classifications is outer-joined unconditionally because two filters
 * and one sort column live on it (book_score, is_book_product).
 */
final class UrlsController
{
    /** sort_by value => orderable SQL expression. */
    private const SORT_COLUMNS = [
        'url' => 'discovered_urls.url',
        'fails' => 'discovered_urls.fail_count',
        'discovered' => 'discovered_urls.first_seen_at',
        'score' => 'url_classifications.book_score',
        'book' => 'shop_books.title',
    ];

    /** fail_count at which a URL is considered failing. */
    private const FAILING_THRESHOLD = 3;

    public function index(Request $request): array
    {
        $page = max(1, (int) $request->query('page', 1));
        $perPage = max(1, min((int) $request->query('per_page', 30), 200));
        $sortBy = (string) $request->query('sort_by', 'discovered');
        $hasBook = $request->boolean('has_book');

        $query = DiscoveredUrl::query()
            ->with(['shop', 'shopBook', 'classification'])
            ->select('discovered_urls.*')
            ->leftJoin(
                'url_classifications',
                'url_classifications.discovered_url_id',
                '=',
                'discovered_urls.id'
            );

        // Only joined when needed for the sort or filter, matching Python.
        if ($sortBy === 'book' || $hasBook) {
            $query->leftJoin('shop_books', 'shop_books.id', '=', 'discovered_urls.shop_book_id');
        }

        $shop = (string) $request->query('shop', '');
        $shopId = null;
        if ($shop !== '' && $shop !== 'all') {
            $shopId = Shop::where('name', $shop)->value('id') ?? -1;
            $query->where('discovered_urls.shop_id', $shopId);
        }

        $urlType = (string) $request->query('url_type', '');
        if ($urlType !== '' && $urlType !== 'all') {
            $query->where('discovered_urls.url_type', $urlType);
        }

        $search = (string) $request->query('search', '');
        if ($search !== '') {
            $query->where('discovered_urls.url', 'ilike', "%{$search}%");
        }

        $isBook = (string) $request->query('is_book', '');
        if ($isBook === 'book') {
            // Classified as a book OR already linked to a shop_book.
            $query->where(fn ($q) => $q
                ->where('url_classifications.is_book_product', true)
                ->orWhereNotNull('discovered_urls.shop_book_id'));
        } elseif ($isBook === 'not_book') {
            $query->where('url_classifications.is_book_product', false);
        }

        if ($request->boolean('failing')) {
            $query->where('discovered_urls.fail_count', '>=', self::FAILING_THRESHOLD);
        }
        if ($hasBook) {
            $query->whereNotNull('discovered_urls.shop_book_id');
        }

        $total = (clone $query)->count();

        $column = self::SORT_COLUMNS[$sortBy] ?? self::SORT_COLUMNS['discovered'];
        $direction = $request->query('sort_order') === 'asc' ? 'asc' : 'desc';
        $query->orderByRaw("{$column} {$direction} nulls last");
        $query->orderBy('discovered_urls.id', $direction);

        $urls = $query->offset(($page - 1) * $perPage)->limit($perPage)->get();

        return [
            'urls' => $urls->map(fn (DiscoveredUrl $u): array => self::present($u))->all(),
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => $total > 0 ? max(1, (int) ceil($total / $perPage)) : 1,
            'stats' => self::stats($shopId),
        ];
    }

    /** @return array<string, mixed> */
    private static function present(DiscoveredUrl $u): array
    {
        $classification = $u->classification;
        $book = $u->shopBook;

        return [
            'id' => $u->id,
            'url' => $u->url,
            'shop' => $u->shop->name ?? '—',
            'url_type' => $u->url_type ?: 'unknown',
            'source' => $u->source ?: '—',
            'fail_count' => $u->fail_count,
            'status' => $u->fail_count >= self::FAILING_THRESHOLD ? 'error' : 'ok',
            'first_seen_at' => RunPresenter::iso($u->first_seen_at),
            'last_seen_ago' => RunPresenter::relative($u->last_seen_at),
            'last_scraped_ago' => RunPresenter::relative($u->last_seen_at),
            'discovered_ago' => RunPresenter::relative($u->first_seen_at),
            'book_title' => $book->title ?? '—',
            'book_id' => $book->id ?? null,
            'book_score' => $classification->book_score ?? null,
            'is_book' => $classification->is_book_product ?? null,
        ];
    }

    /** @return array<string, int> */
    private static function stats(?int $shopId): array
    {
        // Qualified: shop_books also has shop_id, and the in_shop_books
        // query below joins it — an unqualified column is ambiguous there.
        $base = fn () => DiscoveredUrl::query()
            ->when($shopId !== null, fn ($q) => $q->where('discovered_urls.shop_id', $shopId));

        $total = $base()->count();

        // Matched on (shop_id, url) rather than the FK: this counts URLs the
        // scan actually turned into a shop_book row, which is what Python does.
        $inShopBooks = $base()
            ->join('shop_books', function ($join): void {
                $join->on('shop_books.shop_id', '=', 'discovered_urls.shop_id')
                    ->on('shop_books.url', '=', 'discovered_urls.url');
            })
            ->count();

        return [
            'total' => $total,
            'in_shop_books' => $inShopBooks,
            'not_in_shop_books' => $total - $inShopBooks,
            'failed' => $base()->where('fail_count', '>=', self::FAILING_THRESHOLD)->count(),
        ];
    }
}
