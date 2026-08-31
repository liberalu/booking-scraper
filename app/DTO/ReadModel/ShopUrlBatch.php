<?php

declare(strict_types=1);

namespace App\DTO\ReadModel;

final readonly class ShopUrlBatch
{
    /** @param list<string> $urls */
    public function __construct(
        public string $shop,
        public array $urls,
    ) {}
}
