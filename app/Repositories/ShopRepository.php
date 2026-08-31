<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\Shop;

final class ShopRepository
{
    public function byName(string $name): Shop
    {
        return Shop::where('name', $name)->firstOrFail();
    }
}
