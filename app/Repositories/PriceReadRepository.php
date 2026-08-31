<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\PriceQueryInput;
use App\Models\Shop;
use App\Support\Queries;
use App\Support\RunPresenter;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final class PriceReadRepository
{
    /** @return array<string, mixed> */
    public function __invoke(PriceQueryInput $input): array
    {
        $days = $input->days;
        $page = $input->page;
        $perPage = $input->perPage;

        $shop = $input->shop;
        $shopId = null;
        if ($shop !== '' && $shop !== 'all') {
            $shopId = DatabaseRow::from([
                'id' => Shop::where('name', $shop)->value('id'),
            ])->nullableInt('id') ?? -1;
        }

        $cutoff = Carbon::now('UTC')->subDays($days);
        $bindings = ['cutoff' => $cutoff];
        $shopFilter = '';
        if ($shopId !== null) {
            $shopFilter = 'and sb.shop_id = :shop_id';
            $bindings['shop_id'] = $shopId;
        }

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

        $total = DatabaseRow::from(DB::selectOne(
            $cte.' select count(*) as c from changes where rn = 1',
            $bindings
        ))->int('c');

        $rows = DB::select(
            $cte.'
            select shop_book_id, title, prev_price, new_price, change, scraped_at
            from changes
            where rn = 1
            order by abs(change) desc, scraped_at desc
            offset :offset limit :limit',
            [...$bindings, 'offset' => ($page - 1) * $perPage, 'limit' => $perPage]
        );

        $changes = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $scrapedAt = $row->nullableString('scraped_at');
            $timestamp = $scrapedAt === null ? null : Carbon::parse($scrapedAt);
            $changes[] = [
                'shop_book_id' => $row->int('shop_book_id'),
                'title' => $row->string('title'),
                'prev_price' => $row->nullableFloat('prev_price'),
                'new_price' => $row->nullableFloat('new_price'),
                'change' => $row->nullableFloat('change'),
                'scraped_at' => RunPresenter::iso($timestamp),
                'scraped_ago' => RunPresenter::relative($timestamp),
            ];
        }

        return [
            'changes' => $changes,
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($total, $perPage),
            'days' => $days,
        ];
    }
}
