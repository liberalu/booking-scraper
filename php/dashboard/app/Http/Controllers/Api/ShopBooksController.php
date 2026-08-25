<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\BookPresenter;
use App\Support\IssueMetadata;
use App\Support\Queries;
use App\Support\RunPresenter;
use BookScraper\Models\Shop;
use BookScraper\Models\ScrapeRun;
use BookScraper\Models\ShopBook;
use Illuminate\Support\Carbon;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

/**
 * GET /api/shop-books — the catalogue table, with the same filter surface
 * as the Python endpoint (get_shop_books_page).
 */
final class ShopBooksController
{
    private const SORT_COLUMNS = [
        'id', 'title', 'author', 'isbn', 'type', 'price', 'year',
        'is_active', 'inactive_since', 'last_seen_at',
    ];

    private const MISSING_ANY_FIELDS = ['author', 'isbn', 'year', 'publisher', 'format'];

    public function index(Request $request): array
    {
        $page = max(1, (int) $request->query('page', 1));
        $perPage = max(1, min((int) $request->query('per_page', 30), 200));

        $query = ShopBook::query()->with('shop');
        $this->applyFilters($query, $request);

        $total = (clone $query)->count();

        $sortBy = (string) $request->query('sort_by', '');
        $column = in_array($sortBy, self::SORT_COLUMNS, true) ? $sortBy : 'last_seen_at';
        $direction = $request->query('sort_order') === 'asc' ? 'asc' : 'desc';
        // Python uses nulls_last() in both directions, plus an id tiebreaker
        // in the same direction — the sort columns are not unique.
        $query->orderByRaw(sprintf('%s %s nulls last', $column, $direction));
        $query->orderBy('shop_books.id', $direction);

        $books = $query->offset(($page - 1) * $perPage)->limit($perPage)->get();

        return [
            'books' => $books->map(fn (ShopBook $b): array => BookPresenter::toArray($b))->all(),
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($total, $perPage),
            // KPIs are catalogue-wide, deliberately unaffected by the filters.
            'kpis' => [
                'total' => ShopBook::count(),
                'active' => ShopBook::where('is_active', true)->count(),
                'missing_isbn' => ShopBook::whereNull('isbn')->count(),
                'missing_price' => ShopBook::whereNull('price')->count(),
                'unreachable' => ShopBook::whereIn(
                    'id',
                    DB::table('discovered_urls')
                        ->select('shop_book_id')
                        ->whereNotNull('shop_book_id')
                        ->where('url_type', 'unreachable')
                )->count(),
            ],
        ];
    }

    private function applyFilters(Builder $query, Request $request): void
    {
        $shop = (string) $request->query('shop', '');
        if ($shop !== '' && $shop !== 'all') {
            // Unknown shop matches nothing rather than silently ignoring
            // the filter and showing the whole catalogue.
            $query->where('shop_id', Shop::where('name', $shop)->value('id') ?? -1);
        }

        $search = (string) $request->query('search', '');
        if ($search !== '') {
            $like = "%{$search}%";
            $query->where(fn ($q) => $q
                ->where('title', 'ilike', $like)
                ->orWhere('author', 'ilike', $like)
                ->orWhere('isbn', 'ilike', $like));
        }

        $category = trim((string) $request->query('category', ''));
        if ($category !== '') {
            // Postgres array membership.
            $query->whereRaw('? = any(categories)', [$category]);
        }

        $type = (string) $request->query('type_filter', '');
        if ($type !== '' && $type !== 'all') {
            $query->where('type', $type);
        }

        $format = (string) $request->query('format_filter', '');
        if ($format !== '' && $format !== 'all') {
            $format === 'none'
                ? $query->whereNull('format')
                : $query->where('format', $format);
        }

        $missing = (string) $request->query('missing_field', '');
        if ($missing !== '' && $missing !== 'any') {
            if (in_array($missing, self::MISSING_ANY_FIELDS, true)) {
                $query->whereNull($missing);
            }
        } elseif ($request->query('missing_field') === 'any') {
            $query->where(function ($q): void {
                foreach (self::MISSING_ANY_FIELDS as $field) {
                    $q->orWhereNull($field);
                }
            });
        }

        $active = (string) $request->query('active', '');
        if ($active === 'true') {
            $query->where('is_active', true);
        } elseif ($active === 'false') {
            $query->where('is_active', false);
        }

        if ($request->boolean('has_isbn')) {
            $query->whereNotNull('isbn');
        }

        $linked = (string) $request->query('linked', '');
        if ($linked === 'linked') {
            $query->whereNotNull('book_id');
        } elseif ($linked === 'not_linked') {
            $query->whereNull('book_id');
        }

        if ($request->boolean('url_unreachable')) {
            $query->whereIn(
                'id',
                DB::table('discovered_urls')
                    ->select('shop_book_id')
                    ->whereNotNull('shop_book_id')
                    ->where('url_type', 'unreachable')
            );
        }
    }

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function show(int $bookId): mixed
    {
        $book = ShopBook::with('shop')->find($bookId);
        if ($book === null) {
            return response()->json(['detail' => 'Book not found'], 404);
        }

        $issues = DB::table('validation_issues')
            ->where('shop_book_id', $bookId)
            ->orderBy('lifecycle_state')
            ->orderByDesc('id')
            ->get()
            ->map(fn (object $r): array => [
                'id' => (int) $r->id,
                'issue' => $r->issue,
                'field' => $r->field,
                'raw_value' => $r->raw_value,
                'lifecycle_state' => $r->lifecycle_state,
                'scrape_run_id' => $r->last_seen_run_id,
                'severity' => IssueMetadata::severity((string) $r->issue),
            ])->all();

        $changes = DB::table('shop_book_changes')
            ->where('shop_book_id', $bookId)
            ->orderByDesc('changed_at')
            ->limit(20)
            ->get();

        // Every run that touched this book: the ones that changed it, plus
        // the last one that saw it even if nothing changed.
        $runIds = $changes->pluck('scrape_run_id')->filter()->values()->all();
        if ($book->last_run_id !== null && !in_array($book->last_run_id, $runIds, true)) {
            array_unshift($runIds, $book->last_run_id);
        }
        $uniqueRunIds = array_values(array_unique($runIds));

        $recentRuns = [];
        if ($uniqueRunIds !== []) {
            $runs = ScrapeRun::with('shop')
                ->whereIn('id', $uniqueRunIds)
                ->orderByDesc('started_at')
                ->limit(20)
                ->get();
            $terminal = Queries::runTerminalCounts($runs->pluck('id')->all());
            $rescrape = Queries::rescrapeFlags($runs->pluck('id')->all());
            $recentRuns = $runs->map(fn ($run): array => RunPresenter::toArray(
                $run,
                terminalCount: $terminal[$run->id] ?? null,
                rescrape: $rescrape[$run->id] ?? false,
            ))->all();
        }

        // Joined on the FK: the classification and reachability belong to the
        // URL row the scan actually resolved to this book.
        $linkedUrl = DB::table('discovered_urls')
            ->leftJoin('url_classifications as uc', 'uc.discovered_url_id', '=', 'discovered_urls.id')
            ->select(
                'discovered_urls.url',
                'discovered_urls.url_type',
                'discovered_urls.fail_count',
                'uc.book_score',
                'uc.is_book_product',
                'uc.reasons',
                'uc.classified_at',
            )
            ->where('discovered_urls.shop_book_id', $bookId)
            ->first();

        $detail = BookPresenter::toArray($book);
        $detail['issues'] = count($issues);
        $detail['issues_list'] = $issues;
        $detail['price_history'] = DB::table('prices')
            ->where('shop_book_id', $bookId)
            ->orderBy('scraped_at')
            ->get()
            ->map(fn (object $p): array => [
                'scraped_at' => self::iso($p->scraped_at),
                'price' => $p->price !== null ? (float) $p->price : null,
                'in_stock' => (bool) $p->in_stock,
            ])->all();
        $detail['changes'] = $changes->map(fn (object $c): array => [
            'field' => $c->field,
            'old_value' => $c->old_value,
            'new_value' => $c->new_value,
            'changed_at' => self::iso($c->changed_at),
        ])->all();
        $detail['description'] = $book->description;
        $detail['image_url'] = $book->image_url;
        $detail['categories'] = $book->categories ?: [];
        // Format-specific extras the parsers captured (translator, dimensions,
        // language, cover_type, …) that have no first-class column.
        // ?: new stdClass because json_encode renders an empty PHP array as
        // [], and Python's dict renders as {} — a key-value map must not
        // change JSON type just because it happens to be empty.
        $detail['attributes'] = DB::table('shop_book_attributes')
            ->where('shop_book_id', $bookId)
            ->orderBy('key')
            ->pluck('value', 'key')
            ->all() ?: new \stdClass();
        $detail['url_count'] = DB::table('discovered_urls')->where('shop_book_id', $bookId)->count();
        $detail['run_count'] = count($uniqueRunIds);
        $detail['runs'] = $recentRuns;
        $detail['book_id'] = $book->book_id;
        $detail['discovery_url'] = $linkedUrl->url ?? null;
        $detail['url_status'] = $linkedUrl->url_type ?? null;
        $detail['url_fail_count'] = $linkedUrl->fail_count ?? 0;
        $detail['classification'] = ($linkedUrl !== null && $linkedUrl->book_score !== null)
            ? [
                'book_score' => $linkedUrl->book_score,
                'is_book_product' => $linkedUrl->is_book_product,
                'reasons' => $linkedUrl->reasons !== null
                    ? json_decode((string) $linkedUrl->reasons, true)
                    : [],
                'classified_at' => self::iso($linkedUrl->classified_at),
                'classified_ago' => RunPresenter::relative(
                    $linkedUrl->classified_at !== null ? Carbon::parse($linkedUrl->classified_at) : null
                ),
            ]
            : null;

        return $detail;
    }

    private static function iso(mixed $timestamp): ?string
    {
        if ($timestamp === null) {
            return null;
        }
        $dt = Carbon::parse($timestamp)->utc();

        return $dt->micro === 0
            ? $dt->format('Y-m-d\TH:i:sP')
            : $dt->format('Y-m-d\TH:i:s.uP');
    }

    /**
     * POST /shop-books/{id}/unlink-canonical — clear shop_books.book_id.
     *
     * The operator fix for match_isbn_drift: match step 1 has a
     * `WHERE book_id IS NULL` guard, so an existing link is never
     * re-evaluated. Dropping the wrong link is what lets the next match
     * re-link by the corrected ISBN.
     *
     * @return array<string, mixed>|\Illuminate\Http\JsonResponse
     */
    public function unlinkCanonical(int $shopBookId): mixed
    {
        $book = ShopBook::find($shopBookId);
        if ($book === null) {
            return response()->json(['detail' => 'shop_book not found'], 404);
        }

        $previous = $book->book_id;
        if ($previous === null) {
            // Idempotent: already unlinked is a success, not an error.
            return [
                'shop_book_id' => $shopBookId,
                'previous_book_id' => null,
                'changed' => false,
            ];
        }

        ShopBook::whereKey($shopBookId)->update(['book_id' => null]);

        return [
            'shop_book_id' => $shopBookId,
            'previous_book_id' => $previous,
            'changed' => true,
        ];
    }
}
