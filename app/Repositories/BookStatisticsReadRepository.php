<?php

declare(strict_types=1);

namespace App\Repositories;

use Illuminate\Support\Facades\DB;

final class BookStatisticsReadRepository
{
    private const CONFLICT_HAVING = 'count(distinct lower(title)) > 1'
        .' or count(distinct lower(author)) > 1'
        .' or count(distinct year) > 1'
        .' or count(distinct lower(publisher)) > 1';

    /** @return array<string, int|float> */
    public function stats(): array
    {
        $total = DB::table('books')->count();
        $enriched = DB::table('books')->where('data_source', '!=', 'shop_inferred')->count();
        $counts = DB::table('shop_books')
            ->select('book_id')
            ->selectRaw('count(id) as n')
            ->whereNotNull('book_id')
            ->groupBy('book_id')
            ->pluck('n')
            ->all();
        $countValues = [];
        foreach ($counts as $count) {
            $countValues[] = DatabaseRow::from(['count' => $count])->int('count');
        }
        $multiShop = count(array_filter($countValues, static fn (int $count): bool => $count >= 2));
        $singleShop = count(array_filter($countValues, static fn (int $count): bool => $count === 1));
        $listings = array_sum($countValues);
        $conflictQuery = DB::table('shop_books')
            ->select('book_id')
            ->whereNotNull('book_id')
            ->groupBy('book_id')
            ->havingRaw(self::CONFLICT_HAVING);
        $conflicts = DB::query()->fromSub($conflictQuery, 'c')->count();

        return [
            'total' => $total,
            'enriched' => $enriched,
            'enriched_pct' => $total > 0 ? round($enriched / $total * 100, 1) : 0,
            'multi_shop' => $multiShop,
            'single_shop' => $singleShop,
            'avg_shops' => $countValues !== [] ? round($listings / count($countValues), 1) : 0,
            'conflicts' => $conflicts,
        ];
    }

    /** @return list<int> */
    public function years(): array
    {
        $values = DB::table('books')
            ->whereNotNull('year')
            ->distinct()
            ->orderByDesc('year')
            ->pluck('year')
            ->all();

        $years = [];
        foreach ($values as $year) {
            $years[] = DatabaseRow::from(['year' => $year])->int('year');
        }

        return $years;
    }
}
