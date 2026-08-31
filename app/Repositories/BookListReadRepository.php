<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\ReadModel\BookPage;
use App\DTO\Request\BookQueryInput;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Facades\DB;

/** @phpstan-import-type BookListRow from BookPage */
final class BookListReadRepository
{
    private const CONFLICT_HAVING = 'count(distinct lower(title)) > 1'
        .' or count(distinct lower(author)) > 1'
        .' or count(distinct year) > 1'
        .' or count(distinct lower(publisher)) > 1';

    public function index(BookQueryInput $input): BookPage
    {
        $query = DB::table('books');

        if ($input->dataSource !== null) {
            $query->where('data_source', $input->dataSource);
        }
        if ($input->year !== null) {
            $query->where('year', $input->year);
        }
        if ($input->hasIsbn !== null) {
            $withIsbn = DB::table('book_isbns')->select('book_id')->distinct();
            if ($input->hasIsbn) {
                $query->whereIn('id', $withIsbn);
            } else {
                $query->whereNotIn('id', $withIsbn);
            }
        }
        if ($input->hasShops !== null) {
            $linked = DB::table('shop_books')->select('book_id')->whereNotNull('book_id')->distinct();
            if ($input->hasShops) {
                $query->whereIn('id', $linked);
            } else {
                $query->whereNotIn('id', $linked);
            }
        }
        if ($input->hasConflicts !== null) {
            $conflicting = DB::table('shop_books')
                ->select('book_id')
                ->whereNotNull('book_id')
                ->groupBy('book_id')
                ->havingRaw(self::CONFLICT_HAVING);
            if ($input->hasConflicts) {
                $query->whereIn('id', $conflicting);
            } else {
                $query->whereNotIn('id', $conflicting);
            }
        }

        if ($input->shopCountMin !== null || $input->shopCountMax !== null) {
            $counts = DB::table('shop_books')
                ->select('book_id')
                ->whereNotNull('book_id')
                ->groupBy('book_id');
            if ($input->shopCountMin !== null) {
                $counts->havingRaw('count(id) >= ?', [$input->shopCountMin]);
            }
            if ($input->shopCountMax !== null) {
                $counts->havingRaw('count(id) <= ?', [$input->shopCountMax]);
            }
            $query->whereIn('id', $counts);
        }

        if ($input->search !== '') {
            $isbn = $this->asIsbn($input->search);
            if ($isbn !== null) {
                $query->whereIn(
                    'id',
                    DB::table('book_isbns')->select('book_id')->where('isbn', $isbn),
                );
            } else {
                $like = "%{$input->search}%";
                $query->where(function (Builder $nested) use ($like): void {
                    $nested->where('title', 'ilike', $like)
                        ->orWhereIn(
                            'id',
                            DB::table('book_authors')
                                ->join('authors', 'authors.id', '=', 'book_authors.author_id')
                                ->select('book_authors.book_id')
                                ->where('authors.name', 'ilike', $like),
                        );
                });
            }
        }

        $total = (clone $query)->count();
        $rawBooks = $query->orderByDesc('created_at')
            ->orderByDesc('id')
            ->offset(($input->page - 1) * $input->perPage)
            ->limit($input->perPage)
            ->get();
        $books = [];
        foreach ($rawBooks as $raw) {
            $books[] = DatabaseRow::from($raw);
        }

        return new BookPage(
            $this->decorate($books),
            $total,
            $input->page,
            $input->perPage,
        );
    }

    /**
     * @param  list<DatabaseRow>  $books
     * @return list<BookListRow>
     */
    private function decorate(array $books): array
    {
        if ($books === []) {
            return [];
        }

        $ids = array_map(static fn (DatabaseRow $book): int => $book->int('id'), $books);
        $isbnRows = DB::table('book_isbns')
            ->select('book_id', 'isbn')
            ->whereIn('book_id', $ids)
            ->get();
        $isbns = [];
        foreach ($isbnRows as $raw) {
            $row = DatabaseRow::from($raw);
            $isbns[$row->int('book_id')][] = $row->string('isbn');
        }
        $authorRows = DB::table('book_authors')
            ->join('authors', 'authors.id', '=', 'book_authors.author_id')
            ->select('book_authors.book_id', 'authors.name')
            ->whereIn('book_authors.book_id', $ids)
            ->where('book_authors.role', 'author')
            ->orderBy('book_authors.position')
            ->get();
        $authors = [];
        foreach ($authorRows as $raw) {
            $row = DatabaseRow::from($raw);
            $authors[$row->int('book_id')][] = $row->string('name');
        }
        $shopStatRows = DB::table('shop_books')
            ->select('book_id')
            ->selectRaw('count(id) as shop_count, min(price) as price_min, max(price) as price_max')
            ->whereIn('book_id', $ids)
            ->groupBy('book_id')
            ->get();
        $shopStats = [];
        foreach ($shopStatRows as $raw) {
            $row = DatabaseRow::from($raw);
            $shopStats[$row->int('book_id')] = $row;
        }
        $conflictingValues = DB::table('shop_books')
            ->select('book_id')
            ->whereIn('book_id', $ids)
            ->groupBy('book_id')
            ->havingRaw(self::CONFLICT_HAVING)
            ->pluck('book_id')
            ->all();
        $conflicting = [];
        foreach ($conflictingValues as $value) {
            $conflicting[DatabaseRow::from(['id' => $value])->int('id')] = true;
        }
        $publisherRows = DB::table('publishers')->get(['id', 'name']);
        $publishers = [];
        foreach ($publisherRows as $raw) {
            $row = DatabaseRow::from($raw);
            $publishers[$row->int('id')] = $row->string('name');
        }

        return array_map(
            static function (DatabaseRow $book) use (
                $isbns,
                $authors,
                $shopStats,
                $conflicting,
                $publishers,
            ): array {
                $id = $book->int('id');
                $stats = $shopStats[$id] ?? null;
                $publisherId = $book->nullableInt('publisher_id');

                return [
                    'id' => $id,
                    'title' => $book->string('title'),
                    'year' => $book->nullableInt('year'),
                    'data_source' => $book->string('data_source'),
                    'libis_code' => $book->nullableString('libis_code'),
                    'publisher' => $publisherId !== null
                        ? ($publishers[$publisherId] ?? null)
                        : null,
                    'primary_isbn' => $isbns[$id][0] ?? null,
                    'authors' => $authors[$id] ?? [],
                    'shop_count' => $stats?->nullableInt('shop_count') ?? 0,
                    'price_min' => $stats?->nullableFloat('price_min'),
                    'price_max' => $stats?->nullableFloat('price_max'),
                    'has_conflicts' => isset($conflicting[$id]),
                ];
            },
            $books,
        );
    }

    private function asIsbn(string $value): ?string
    {
        $normalized = strtoupper(str_replace(['-', ' '], '', $value));

        return preg_match('/^(?:\d{9}[\dX]|\d{13})$/', $normalized) === 1
            ? $normalized
            : null;
    }
}
