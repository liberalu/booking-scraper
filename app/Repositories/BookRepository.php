<?php

declare(strict_types=1);

namespace App\Repositories;

use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\DatabaseManager;

final readonly class BookRepository
{
    public function __construct(private DatabaseManager $database) {}

    public function ownerIdForIsbn(string $isbn): ?int
    {
        $id = $this->connection()->table('book_isbns')->where('isbn', $isbn)->value('book_id');

        return DatabaseRow::from(['id' => $id])->nullableInt('id');
    }

    public function createManual(
        string $title,
        ?string $isbn,
        string $author,
        string $publisher,
        ?int $year,
    ): int {
        return $this->connection()->transaction(function () use ($title, $isbn, $author, $publisher, $year): int {
            $publisherId = $this->publisherId($publisher);
            $bookId = $this->connection()->table('books')->insertGetId([
                'data_source' => 'manual',
                'title' => $title,
                'year' => $year,
                'publisher_id' => $publisherId,
            ], 'id');

            if ($isbn !== null) {
                $this->connection()->table('book_isbns')->insert([
                    'book_id' => $bookId,
                    'isbn' => $isbn,
                    'isbn_type' => strlen($isbn) === 13 ? 'isbn13' : 'isbn10',
                ]);
            }

            $this->attachAuthor($bookId, $author);

            return $bookId;
        });
    }

    private function publisherId(string $publisher): ?int
    {
        $name = trim($publisher);
        if ($name === '') {
            return null;
        }

        $id = $this->connection()->table('publishers')->where('name', $name)->value('id');

        return $id !== null
            ? DatabaseRow::from(['id' => $id])->int('id')
            : $this->connection()->table('publishers')->insertGetId(['name' => $name], 'id');
    }

    private function attachAuthor(int $bookId, string $author): void
    {
        $name = trim($author);
        if ($name === '') {
            return;
        }

        $normalised = preg_replace('/\s+/', ' ', mb_strtolower($name)) ?? $name;
        $authorId = $this->connection()->table('authors')
            ->where('normalized_name', $normalised)
            ->value('id');
        $authorId = $authorId !== null
            ? DatabaseRow::from(['id' => $authorId])->int('id')
            : $this->connection()->table('authors')->insertGetId([
                'name' => $name,
                'normalized_name' => $normalised,
            ], 'id');

        $this->connection()->table('book_authors')->insert([
            'book_id' => $bookId,
            'author_id' => $authorId,
            'role' => 'author',
            'position' => 0,
        ]);
    }

    private function connection(): ConnectionInterface
    {
        return $this->database->connection();
    }
}
