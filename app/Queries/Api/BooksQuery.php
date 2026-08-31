<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\DTO\ReadModel\BookPage;
use App\DTO\Request\BookQueryInput;
use App\DTO\Response\DownloadResponse;
use App\Models\Book;
use App\Repositories\BookReadRepository;
use RuntimeException;

/** @phpstan-import-type BookListRow from BookPage */
final readonly class BooksQuery
{
    public function __construct(private BookReadRepository $books) {}

    /** @return array{books: list<BookListRow>, total: int, page: int, per_page: int, pages: int} */
    public function index(BookQueryInput $input): array
    {
        return $this->books->index($input);
    }

    /** @return array<string, int|float> */
    public function stats(): array
    {
        return $this->books->stats();
    }

    /** @return list<int> */
    public function years(): array
    {
        return $this->books->years();
    }

    /** @return array<string, mixed> */
    public function show(Book $book): array
    {
        return $this->books->show($book);
    }

    /** @return array<string, mixed> */
    public function prices(Book $book): array
    {
        return $this->books->prices($book);
    }

    public function export(BookQueryInput $input): DownloadResponse
    {
        $columns = [
            'id', 'title', 'author', 'isbn', 'year', 'publisher',
            'shop_count', 'price_min', 'price_max', 'data_source', 'has_conflicts',
        ];

        return new DownloadResponse(function () use ($input, $columns): void {
            $handle = fopen('php://output', 'wb');
            if ($handle === false) {
                throw new RuntimeException('Could not open the CSV output stream.');
            }
            fputcsv($handle, $columns, ',', '"', '\\', "\r\n");

            $page = 1;
            do {
                $result = $this->books->index($input->withPagination($page, 500));

                foreach ($result['books'] as $book) {
                    fputcsv($handle, [
                        $book['id'],
                        $book['title'],
                        $book['authors'][0] ?? '',
                        $book['primary_isbn'] ?? '',
                        $book['year'] ?? '',
                        $book['publisher'] ?? '',
                        $book['shop_count'],
                        $this->csvNumber($book['price_min']),
                        $this->csvNumber($book['price_max']),
                        $book['data_source'],
                        $book['has_conflicts'] ? 'yes' : 'no',
                    ], ',', '"', '\\', "\r\n");
                }

                flush();
                $page++;
            } while ($page <= $result['pages']);

            fclose($handle);
        }, 'books.csv', ['Content-Type' => 'text/csv']);
    }

    private function csvNumber(?float $value): string
    {
        if ($value === null || $value === 0.0) {
            return '';
        }

        return $value === floor($value) && is_finite($value)
            ? sprintf('%.1f', $value)
            : (string) $value;
    }
}
