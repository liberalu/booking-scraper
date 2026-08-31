<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\UrlQueryInput;
use App\Models\DiscoveredUrl;
use App\Support\Queries;
use App\Support\RunPresenter;
use Illuminate\Database\Query\Builder;
use Illuminate\Database\Query\JoinClause;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;

final class UrlReadRepository
{
    private const int FAILING_THRESHOLD = 3;

    /** @return array<string, mixed> */
    public function index(UrlQueryInput $input): array
    {
        $page = $input->page;
        $perPage = $input->perPage;
        $sortBy = $input->sortBy;
        $hasBook = $input->hasBook;

        $query = DB::table('discovered_urls')
            ->select('discovered_urls.id')
            ->leftJoin(
                'url_classifications',
                'url_classifications.discovered_url_id',
                '=',
                'discovered_urls.id'
            );

        if ($sortBy === 'book' || $hasBook) {
            $query->leftJoin('shop_books', 'shop_books.id', '=', 'discovered_urls.shop_book_id');
        }

        $shop = $input->shop;
        $shopId = null;
        if ($shop !== '' && $shop !== 'all') {
            $shopId = DatabaseRow::nullable(
                DB::table('shops')->select('id')->where('name', $shop)->first(),
            )?->int('id') ?? -1;
            $query->where('discovered_urls.shop_id', $shopId);
        }

        $urlType = $input->urlType;
        if ($urlType !== '' && $urlType !== 'all') {
            $query->where('discovered_urls.url_type', $urlType);
        }

        $search = $input->search;
        if ($search !== '') {
            $query->where('discovered_urls.url', 'ilike', "%{$search}%");
        }

        $isBook = $input->isBook;
        if ($isBook === 'book') {

            $query->where(fn (Builder $nested): Builder => $nested
                ->where('url_classifications.is_book_product', true)
                ->orWhereNotNull('discovered_urls.shop_book_id'));
        } elseif ($isBook === 'not_book') {
            $query->where('url_classifications.is_book_product', false);
        }

        if ($input->failing) {
            $query->where('discovered_urls.fail_count', '>=', self::FAILING_THRESHOLD);
        }
        if ($hasBook) {
            $query->whereNotNull('discovered_urls.shop_book_id');
        }

        $total = (clone $query)->count();

        $direction = $input->sortOrder === 'asc' ? 'asc' : 'desc';
        $query->orderByRaw($this->orderExpression($sortBy, $direction));
        $query->orderBy('discovered_urls.id', $direction);

        $urlIds = array_values($query
            ->offset(($page - 1) * $perPage)
            ->limit($perPage)
            ->pluck('discovered_urls.id')
            ->map(static fn (mixed $id): int => DatabaseRow::from(['id' => $id])->int('id'))
            ->all());
        $urlsById = DiscoveredUrl::whereIn('id', $urlIds)
            ->with(['shop', 'shopBook', 'classification'])
            ->get()
            ->keyBy('id');
        $urls = Collection::make($urlIds)
            ->map(static fn (int $id): ?DiscoveredUrl => $urlsById->get($id))
            ->filter(static fn (?DiscoveredUrl $url): bool => $url !== null)
            ->values();

        return [
            'urls' => array_values($urls->map(fn (DiscoveredUrl $u): array => $this->present($u))->all()),
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($total, $perPage),
            'stats' => $this->stats($shopId),
        ];
    }

    /** @return array<string, mixed> */
    private function present(DiscoveredUrl $u): array
    {
        $classification = $u->classification;
        $book = $u->shopBook;

        return [
            'id' => $u->id,
            'url' => $u->url,
            'shop' => $u->shop->name ?? '—',
            'url_type' => $u->url_type !== '' ? $u->url_type : 'unknown',
            'source' => $u->source !== null && $u->source !== '' ? $u->source : '—',
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

    /** @return array{total: int, in_shop_books: int, not_in_shop_books: int, failed: int} */
    private function stats(?int $shopId): array
    {
        $base = static fn (): Builder => DB::table('discovered_urls')
            ->when(
                $shopId !== null,
                static fn (Builder $query): Builder => $query->where('discovered_urls.shop_id', $shopId),
            );

        $total = $base()->count();

        $inShopBooks = $base()
            ->join('shop_books', function (JoinClause $join): void {
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

    /** @return literal-string */
    private function orderExpression(string $sortBy, string $direction): string
    {
        if ($direction === 'asc') {
            return match ($sortBy) {
                'url' => 'discovered_urls.url asc nulls last',
                'fails' => 'discovered_urls.fail_count asc nulls last',
                'score' => 'url_classifications.book_score asc nulls last',
                'book' => 'shop_books.title asc nulls last',
                default => 'discovered_urls.first_seen_at asc nulls last',
            };
        }

        return match ($sortBy) {
            'url' => 'discovered_urls.url desc nulls last',
            'fails' => 'discovered_urls.fail_count desc nulls last',
            'score' => 'url_classifications.book_score desc nulls last',
            'book' => 'shop_books.title desc nulls last',
            default => 'discovered_urls.first_seen_at desc nulls last',
        };
    }
}
