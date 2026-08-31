<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class BookStoreInput
{
    public function __construct(
        public string $title,
        public string $isbn,
        public ?int $year,
        public string $author,
        public string $publisher,
    ) {}
}
