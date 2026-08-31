<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\ReadModel\BookPage;
use App\DTO\Request\BookQueryInput;
use App\Models\Book;

/** @phpstan-import-type BookListRow from BookPage */
final readonly class BookReadRepository
{
    public function __construct(
        private BookListReadRepository $list,
        private BookStatisticsReadRepository $statistics,
        private BookDetailReadRepository $detail,
    ) {}

    /** @return array{books: list<BookListRow>, total: int, page: int, per_page: int, pages: int} */
    public function index(BookQueryInput $input): array
    {
        return $this->list->index($input)->toArray();
    }

    /** @return array<string, int|float> */
    public function stats(): array
    {
        return $this->statistics->stats();
    }

    /** @return list<int> */
    public function years(): array
    {
        return $this->statistics->years();
    }

    /** @return array<string, mixed> */
    public function show(Book $book): array
    {
        return $this->detail->show($book);
    }

    /** @return array<string, mixed> */
    public function prices(Book $book): array
    {
        return $this->detail->prices($book);
    }
}
