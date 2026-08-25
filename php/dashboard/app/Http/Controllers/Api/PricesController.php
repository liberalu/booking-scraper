<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\Queries;
use App\Support\RunPresenter;
use BookScraper\Models\Shop;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * GET /api/prices — price changes over a window, biggest move first.
 *
 * A "change" is a consecutive pair of `prices` rows for one shop_book with
 * different values, deduped so a price that flips back and forth reports
 * once per distinct transition.
 */
final class PricesController
{
    public function __invoke(Request $request): array
    {
        $days = max(1, (int) $request->query('days', 7));
        $page = max(1, (int) $request->query('page', 1));
        $perPage = max(1, min((int) $request->query('per_page', 30), 200));

        $shop = (string) $request->query('shop', '');
        $shopId = null;
        if ($shop !== '' && $shop !== 'all') {
            $shopId = Shop::where('name', $shop)->value('id') ?? -1;
        }

        $cutoff = Carbon::now('UTC')->subDays($days);
        $bindings = ['cutoff' => $cutoff];
        $shopFilter = '';
        if ($shopId !== null) {
            $shopFilter = 'and sb.shop_id = :shop_id';
            $bindings['shop_id'] = $shopId;
        }

        // LAG gives each row its predecessor's price; the row_number dedupes
        // a repeated transition so a price oscillating between two values
        // reports once rather than on every scrape.
        $cte = "
            with ranked as (
                select p.shop_book_id, p.price, p.scraped_at,
                       lag(p.price) over (
                           partition by p.shop_book_id order by p.scraped_at
                       ) as prev_price
                from prices p
                join shop_books sb on sb.id = p.shop_book_id
                where p.scraped_at >= :cutoff
                {$shopFilter}
            ),
            changes as (
                select r.shop_book_id, sb.title, r.prev_price,
                       r.price as new_price,
                       r.price - r.prev_price as change,
                       r.scraped_at,
                       row_number() over (
                           partition by r.shop_book_id, r.prev_price, r.price
                           order by r.scraped_at desc
                       ) as rn
                from ranked r
                join shop_books sb on sb.id = r.shop_book_id
                where r.prev_price is not null and r.price != r.prev_price
            )
        ";

        $total = (int) (DB::selectOne(
            $cte . ' select count(*) as c from changes where rn = 1',
            $bindings
        )->c ?? 0);

        $rows = DB::select(
            $cte . '
            select shop_book_id, title, prev_price, new_price, change, scraped_at
            from changes
            where rn = 1
            order by abs(change) desc, scraped_at desc
            offset :offset limit :limit',
            [...$bindings, 'offset' => ($page - 1) * $perPage, 'limit' => $perPage]
        );

        return [
            'changes' => array_map(static fn (object $row): array => [
                'shop_book_id' => (int) $row->shop_book_id,
                'title' => $row->title,
                'prev_price' => $row->prev_price !== null ? (float) $row->prev_price : null,
                'new_price' => $row->new_price !== null ? (float) $row->new_price : null,
                'change' => $row->change !== null ? (float) $row->change : null,
                'scraped_at' => RunPresenter::iso(
                    $row->scraped_at !== null ? Carbon::parse($row->scraped_at) : null
                ),
                'scraped_ago' => RunPresenter::relative(
                    $row->scraped_at !== null ? Carbon::parse($row->scraped_at) : null
                ),
            ], $rows),
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($total, $perPage),
            'days' => $days,
        ];
    }
}
