<?php

declare(strict_types=1);

namespace App\Services\Books;

use App\DTO\Request\BookStoreInput;
use App\Exceptions\ActionFailed;
use App\Repositories\BookRepository;

final readonly class CreateBookService
{
    public function __construct(private BookRepository $books) {}

    /** @return array{id: int, title: string} */
    public function create(BookStoreInput $input): array
    {
        $title = trim($input->title);
        if ($title === '') {
            throw ActionFailed::unprocessable(['detail' => 'title is required']);
        }

        $isbn = null;
        $rawIsbn = trim($input->isbn);
        if ($rawIsbn !== '') {
            $isbn = $this->normaliseIsbn($rawIsbn);
            if ($isbn === null) {
                throw ActionFailed::unprocessable([
                    'detail' => 'Invalid ISBN format (expected 10 or 13 digits)',
                ]);
            }
        }

        if ($isbn !== null) {
            $owner = $this->books->ownerIdForIsbn($isbn);
            if ($owner !== null) {
                throw ActionFailed::conflict([
                    'detail' => [
                        'message' => 'ISBN already belongs to another book.',
                        'existing_book_id' => $owner,
                    ],
                ]);
            }
        }

        $bookId = $this->books->createManual(
            $title,
            $isbn,
            $input->author,
            $input->publisher,
            $input->year,
        );

        return ['id' => $bookId, 'title' => $title];
    }

    private function normaliseIsbn(string $value): ?string
    {
        $normalised = strtoupper(str_replace(['-', ' '], '', $value));
        if ($normalised === '') {
            return null;
        }

        return preg_match('/^(?:\d{9}[\dX]|\d{13})$/', $normalised) === 1
            ? $normalised
            : null;
    }
}
