<?php

declare(strict_types=1);

namespace App\Services;

use App\Repositories\MatchingRepository;

final readonly class MatchService
{
    public function __construct(private MatchingRepository $matching) {}

    /** @return array{books_linked: int, authors_linked: int, books_synthesized: int} */
    public function run(string $shopName, ?bool $synthesis = null): array
    {
        return $this->matching->run($shopName, $synthesis);
    }

    public function isbnMatch(string $shopName): int
    {
        return $this->matching->isbnMatch($shopName);
    }

    public function authorBackfill(string $shopName): int
    {
        return $this->matching->authorBackfill($shopName);
    }

    public function synthesise(): int
    {
        return $this->matching->synthesise();
    }
}
