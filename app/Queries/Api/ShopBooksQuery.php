<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\DTO\Request\ShopBookQueryInput;
use App\Models\ShopBook;
use App\Repositories\ShopBookReadRepository;

final readonly class ShopBooksQuery
{
    public function __construct(private ShopBookReadRepository $books) {}

    /** @return array<string, mixed> */
    public function index(ShopBookQueryInput $input): array
    {
        return $this->books->index($input);
    }

    /** @return array<string, mixed> */
    public function show(ShopBook $book): array
    {
        return $this->books->show($book);
    }
}
