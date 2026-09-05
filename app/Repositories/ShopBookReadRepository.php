<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\ShopBookQueryInput;
use App\Models\ScrapeRun;
use App\Models\ShopBook;
use App\Support\BookPresenter;
use App\Support\IssueMetadata;
use App\Support\Queries;
use App\Support\RunPresenter;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;

final readonly class ShopBookReadRepository
{
    public function __construct(
        private DashboardStatisticsRepository $statistics = new DashboardStatisticsRepository,
    ) {}

    private const array SORT_COLUMNS = [
        'id', 'title', 'author', 'isbn', 'type', 'price', 'year',
        'is_active', 'inactive_since', 'last_seen_at',
    ];

    private const array MISSING_ANY_FIELDS = ['author', 'isbn', 'year', 'publisher', 'format'];

    /** @return array<string, mixed> */
    public function index(ShopBookQueryInput $input): array
    {
        $page = $input->page;
        $perPage = $input->perPage;

        $query = DB::table('shop_books');
        $this->applyFilters($query, $input);

        $total = (clone $query)->count();

        $sortBy = $input->sortBy;
        $column = in_array($sortBy, self::SORT_COLUMNS, true) ? $sortBy : 'last_seen_at';
        $direction = $input->sortOrder === 'asc' ? 'asc' : 'desc';

        $query->orderBy($column, $direction);
        $query->orderBy('shop_books.id', $direction);

        $rawIds = $query->offset(($page - 1) * $perPage)->limit($perPage)->pluck('id')->all();
        $ids = [];
        foreach ($rawIds as $rawId) {
            $ids[] = DatabaseRow::from(['id' => $rawId])->int('id');
        }
        $models = ShopBook::whereIn('id', $ids)->with('shop')->get()->keyBy('id');
        $books = [];
        foreach ($ids as $id) {
            $book = $models->get($id);
            if ($book instanceof ShopBook) {
                $books[] = BookPresenter::toArray($book);
            }
        }

        return [
            'books' => $books,
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($total, $perPage),

            'kpis' => [
                'total' => DB::table('shop_books')->count(),
                'active' => DB::table('shop_books')->where('is_active', true)->count(),
                'missing_isbn' => DB::table('shop_books')->whereNull('isbn')->count(),
                'missing_price' => DB::table('shop_books')->whereNull('price')->count(),
                'unreachable' => DB::table('shop_books')->whereIn(
                    'id',
                    DB::table('discovered_urls')
                        ->select('shop_book_id')
                        ->whereNotNull('shop_book_id')
                        ->where('url_type', 'unreachable')
                )->count(),
            ],
        ];
    }

    private function applyFilters(Builder $query, ShopBookQueryInput $input): void
    {
        $shop = $input->shop;
        if ($shop !== '' && $shop !== 'all') {

            $query->where('shop_id', DB::table('shops')->where('name', $shop)->value('id') ?? -1);
        }

        $search = $input->search;
        if ($search !== '') {
            $like = "%{$search}%";
            $query->where(fn (Builder $q): Builder => $q
                ->where('title', 'ilike', $like)
                ->orWhere('author', 'ilike', $like)
                ->orWhere('isbn', 'ilike', $like));
        }

        $category = $input->category;
        if ($category !== '') {

            $query->whereRaw('? = any(categories)', [$category]);
        }

        $type = $input->type;
        if ($type !== '' && $type !== 'all') {
            $query->where('type', $type);
        }

        $format = $input->format;
        if ($format !== '' && $format !== 'all') {
            if ($format === 'none') {
                $query->whereNull('format');
            } else {
                $query->where('format', $format);
            }
        }

        $missing = $input->missingField;
        if ($missing !== '' && $missing !== 'any') {
            if (in_array($missing, self::MISSING_ANY_FIELDS, true)) {
                $query->whereNull($missing);
            }
        } elseif ($input->missingField === 'any') {
            $query->where(function (Builder $q): void {
                foreach (self::MISSING_ANY_FIELDS as $field) {
                    $q->orWhereNull($field);
                }
            });
        }

        $active = $input->active;
        if ($active === 'true') {
            $query->where('is_active', true);
        } elseif ($active === 'false') {
            $query->where('is_active', false);
        }

        if ($input->hasIsbn) {
            $query->whereNotNull('isbn');
        }

        $linked = $input->linked;
        if ($linked === 'linked') {
            $query->whereNotNull('book_id');
        } elseif ($linked === 'not_linked') {
            $query->whereNull('book_id');
        }

        if ($input->urlUnreachable) {
            $query->whereIn(
                'id',
                DB::table('discovered_urls')
                    ->select('shop_book_id')
                    ->whereNotNull('shop_book_id')
                    ->where('url_type', 'unreachable')
            );
        }
    }

    /** @return array<string, mixed> */
    public function show(ShopBook $book): array
    {
        $book->load('shop');
        $bookId = $book->id;

        $issueRows = DB::table('validation_issues')
            ->where('shop_book_id', $bookId)
            ->orderBy('lifecycle_state')
            ->orderByDesc('id')
            ->get();
        $issues = [];
        foreach ($issueRows as $raw) {
            $row = DatabaseRow::from($raw);
            $issue = $row->string('issue');
            $issues[] = [
                'id' => $row->int('id'),
                'issue' => $issue,
                'field' => $row->string('field'),
                'raw_value' => $row->nullableString('raw_value'),
                'lifecycle_state' => $row->string('lifecycle_state'),
                'scrape_run_id' => $row->int('last_seen_run_id'),
                'severity' => IssueMetadata::severity($issue),
            ];
        }

        $changes = DB::table('shop_book_changes')
            ->where('shop_book_id', $bookId)
            ->latest('changed_at')
            ->limit(20)
            ->get();

        $runIdSet = [];
        foreach ($changes as $raw) {
            $runId = DatabaseRow::from($raw)->nullableInt('scrape_run_id');
            if ($runId !== null) {
                $runIdSet[$runId] = true;
            }
        }
        if ($book->last_run_id !== null) {
            $runIdSet[$book->last_run_id] = true;
        }
        $uniqueRunIds = array_keys($runIdSet);

        $recentRuns = [];
        if ($uniqueRunIds !== []) {
            $orderedIds = [];
            foreach (DB::table('scrape_runs')->whereIn('id', $uniqueRunIds)
                ->latest('started_at')
                ->limit(20)
                ->pluck('id')->all() as $rawId) {
                $orderedIds[] = DatabaseRow::from(['id' => $rawId])->int('id');
            }
            $runs = ScrapeRun::whereIn('id', $orderedIds)->with('shop')->get()->keyBy('id');
            $terminal = $this->statistics->runTerminalCounts($orderedIds);
            $rescrape = $this->statistics->rescrapeFlags($orderedIds);
            foreach ($orderedIds as $id) {
                $run = $runs->get($id);
                if (! $run instanceof ScrapeRun) {
                    continue;
                }
                $recentRuns[] = RunPresenter::toArray(
                    $run,
                    terminalCount: $terminal[$run->id] ?? null,
                    rescrape: $rescrape[$run->id] ?? false,
                );
            }
        }

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
        $priceRows = DB::table('prices')
            ->where('shop_book_id', $bookId)
            ->oldest('scraped_at')
            ->get();
        $priceHistory = [];
        foreach ($priceRows as $raw) {
            $row = DatabaseRow::from($raw);
            $priceHistory[] = [
                'scraped_at' => $this->iso($row->nullableString('scraped_at')),
                'price' => $row->nullableFloat('price'),
                'in_stock' => $row->bool('in_stock'),
            ];
        }
        $detail['price_history'] = $priceHistory;
        $changeList = [];
        foreach ($changes as $raw) {
            $row = DatabaseRow::from($raw);
            $changeList[] = [
                'field' => $row->string('field'),
                'old_value' => $row->nullableString('old_value'),
                'new_value' => $row->nullableString('new_value'),
                'changed_at' => $this->iso($row->nullableString('changed_at')),
            ];
        }
        $detail['changes'] = $changeList;
        $detail['description'] = $book->description;
        $detail['image_url'] = $book->image_url;
        $detail['categories'] = $book->categories;

        $attributeRows = DB::table('shop_book_attributes')
            ->where('shop_book_id', $bookId)
            ->orderBy('key')
            ->get(['key', 'value']);
        $attributes = [];
        foreach ($attributeRows as $raw) {
            $row = DatabaseRow::from($raw);
            $attributes[$row->string('key')] = $row->nullableString('value');
        }
        $detail['attributes'] = $attributes === [] ? (object) [] : $attributes;
        $detail['url_count'] = DB::table('discovered_urls')->where('shop_book_id', $bookId)->count();
        $detail['run_count'] = count($uniqueRunIds);
        $detail['runs'] = $recentRuns;
        $detail['book_id'] = $book->book_id;
        $linked = DatabaseRow::nullable($linkedUrl);
        $detail['discovery_url'] = $linked?->nullableString('url');
        $detail['url_status'] = $linked?->nullableString('url_type');
        $detail['url_fail_count'] = $linked?->nullableInt('fail_count') ?? 0;
        $detail['classification'] = ($linked instanceof DatabaseRow && $linked->nullableInt('book_score') !== null)
            ? [
                'book_score' => $linked->int('book_score'),
                'is_book_product' => $linked->bool('is_book_product'),
                'reasons' => $linked->nullableString('reasons') !== null
                    ? json_decode($linked->string('reasons'), true)
                    : [],
                'classified_at' => $this->iso($linked->nullableString('classified_at')),
                'classified_ago' => RunPresenter::relative(
                    $linked->nullableString('classified_at') !== null
                        ? Date::parse($linked->string('classified_at'))
                        : null
                ),
            ]
            : null;

        return $detail;
    }

    private function iso(?string $timestamp): ?string
    {
        if ($timestamp === null) {
            return null;
        }
        $dt = Date::parse($timestamp)->utc();

        return $dt->micro === 0
            ? $dt->format('Y-m-d\TH:i:sP')
            : $dt->format('Y-m-d\TH:i:s.uP');
    }
}
