<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\Models\Shop;
use App\Repositories\ShopReadRepository;

final readonly class ShopsQuery
{
    public function __construct(private ShopReadRepository $shops) {}

    /** @return array<string, mixed> */
    public function index(): array
    {
        return $this->shops->index();
    }

    /** @return array<string, mixed> */
    public function show(Shop $shop): array
    {
        return $this->shops->show($shop);
    }
}
