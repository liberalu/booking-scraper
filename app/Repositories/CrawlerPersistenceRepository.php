<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\Price;
use App\Repositories\Contracts\CrawlerPersistenceRepositoryInterface;
use Closure;
use Illuminate\Database\Connection;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;

final class CrawlerPersistenceRepository implements CrawlerPersistenceRepositoryInterface
{
    private const array TRACKED_FIELDS = [
        'price', 'description', 'image_url', 'author', 'isbn', 'publisher',
        'year', 'format',
    ];

    /**
     * @template T
     *
     * @param  Closure(): T  $operation
     * @return T
     */
    public function transaction(Closure $operation): mixed
    {
        return DB::connection()->transaction(
            static fn (Connection $connection): mixed => $operation(),
        );
    }

    /** @param array<string, mixed> $data */
    public function appendPrice(UpsertResult $result, array $data, ?int $runId): bool
    {
        $price = $data['price'] ?? null;
        if ($price === null || $price === '') {
            return false;
        }

        Price::create([
            'shop_book_id' => $result->shopBook->id,
            'price' => $price,
            'price_original' => $data['price_original'] ?? null,
            'in_stock' => (bool) ($data['in_stock'] ?? true),
            'scraped_at' => Date::now('UTC'),
            'scrape_run_id' => $runId,
        ]);

        return true;
    }

    public function recordChanges(UpsertResult $result, ?int $runId): void
    {
        if ($result->changes === []) {
            return;
        }

        $now = Date::now('UTC');
        $rows = [];
        foreach ($result->changes as $change) {
            $rows[] = [
                'shop_book_id' => $result->shopBook->id,
                'scrape_run_id' => $runId,
                'field' => $change['field'],
                'old_value' => $change['old'],
                'new_value' => $change['new'],
                'changed_at' => $now,
            ];
        }
        DB::table('shop_book_changes')->insert($rows);

        $fields = array_values(array_unique(array_filter(
            array_map(static fn (array $change): string => $change['field'], $result->changes),
            static fn (string $field): bool => in_array($field, self::TRACKED_FIELDS, true),
        )));

        foreach ($fields as $field) {
            DB::table('shop_book_field_updates')->updateOrInsert(
                ['shop_book_id' => $result->shopBook->id, 'field' => $field],
                ['updated_at' => $now],
            );
        }
    }
}
