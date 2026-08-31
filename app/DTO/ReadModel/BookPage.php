<?php

declare(strict_types=1);

namespace App\DTO\ReadModel;

/**
 * @phpstan-type BookListRow array{id: int, title: string, year: int|null, data_source: string, libis_code: string|null, publisher: string|null, primary_isbn: string|null, authors: list<string>, shop_count: int, price_min: float|null, price_max: float|null, has_conflicts: bool}
 */
final readonly class BookPage
{
    public int $pages;

    /** @param list<BookListRow> $books */
    public function __construct(
        public array $books,
        public int $total,
        public int $page,
        public int $perPage,
    ) {
        $this->pages = $perPage > 0 ? intdiv($total + $perPage - 1, $perPage) : 1;
    }

    /** @return array{books: list<BookListRow>, total: int, page: int, per_page: int, pages: int} */
    public function toArray(): array
    {
        return [
            'books' => $this->books,
            'total' => $this->total,
            'page' => $this->page,
            'per_page' => $this->perPage,
            'pages' => $this->pages,
        ];
    }
}
