<?php

declare(strict_types=1);

namespace App\Repositories;

use Illuminate\Support\Facades\DB;
use UnexpectedValueException;

final class ShopSettingsRepository
{
    /** @return array<string, array{value: string, type: string}> */
    public function forShop(string $shop): array
    {
        $rows = DB::table('shop_settings')
            ->join('shops', 'shops.id', '=', 'shop_settings.shop_id')
            ->where('shops.name', $shop)
            ->get(['shop_settings.key', 'shop_settings.value', 'shop_settings.type']);

        $resolved = [];
        foreach ($rows as $row) {
            if (! is_string($row->key) || ! is_string($row->value) || ! is_string($row->type)) {
                throw new UnexpectedValueException('Invalid shop setting row returned by the database.');
            }
            $resolved[$row->key] = [
                'value' => $row->value,
                'type' => $row->type,
            ];
        }

        return $resolved;
    }
}
