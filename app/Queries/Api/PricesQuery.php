<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\DTO\Request\PriceQueryInput;
use App\Repositories\PriceReadRepository;

final readonly class PricesQuery
{
    public function __construct(private PriceReadRepository $prices) {}

    /** @return array<string, mixed> */
    public function __invoke(PriceQueryInput $input): array
    {
        return ($this->prices)($input);
    }
}
