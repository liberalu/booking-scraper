<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\ReadModel\ShopUrlBatch;
use App\DTO\Request\LegacyFormInput;
use App\Models\DiscoveredUrl;
use App\Models\Shop;
use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\DatabaseManager;
use Illuminate\Database\Query\Builder;

final readonly class LegacyFormsRepository
{
    public function __construct(private DatabaseManager $database) {}

    public function saveRateSettings(int $shopId, float $delay, int $concurrency): void
    {
        $this->upsertSetting($shopId, 'download_delay', $this->floatValue($delay), 'float');
        $this->upsertSetting(
            $shopId,
            'concurrent_requests_per_domain',
            (string) $concurrency,
            'int',
        );
    }

    public function shopNameForUrl(DiscoveredUrl $url): ?string
    {
        $name = Shop::whereKey($url->shop_id)->value('name');

        return is_string($name) ? $name : null;
    }

    /** @return list<ShopUrlBatch> */
    public function unknownUrlBatches(string $shopName): array
    {
        $query = $this->connection()->table('discovered_urls as du')
            ->join('shops as s', 's.id', '=', 'du.shop_id')
            ->where('du.url_type', 'unknown');

        if ($shopName !== '') {
            $query->where('s.name', $shopName);
        }

        $rows = $query->orderBy('s.name')
            ->orderBy('du.id')
            ->get(['s.name as shop', 'du.url']);

        return $this->toBatches($rows);
    }

    /** @return list<ShopUrlBatch> */
    public function filteredShopBookBatches(LegacyFormInput $input, int $limit): array
    {
        $query = $this->connection()->table('shop_books as sb')
            ->join('shops as s', 's.id', '=', 'sb.shop_id');

        if ($input->shop !== '') {
            $query->where('s.name', $input->shop);
        }
        if ($input->search !== '') {
            $term = '%'.$input->search.'%';
            $query->where(function (Builder $nested) use ($term): void {
                $nested->where('sb.title', 'ilike', $term)
                    ->orWhere('sb.author', 'ilike', $term);
            });
        }
        foreach (['author' => 'author', 'publisher' => 'publisher'] as $property => $column) {
            $value = $input->{$property};
            if ($value !== '') {
                $query->where('sb.'.$column, 'ilike', '%'.$value.'%');
            }
        }
        if ($input->category !== '') {
            $query->whereRaw('? = any(sb.categories)', [$input->category]);
        }
        if ($input->format !== '') {
            $query->where('sb.format', $input->format);
        }
        if ($input->missing !== '' && preg_match('/^[a-z_]+$/', $input->missing) === 1) {
            $query->whereNull('sb.'.$input->missing);
        }
        if ($input->active === 'true') {
            $query->where('sb.is_active', true);
        } elseif ($input->active === 'false') {
            $query->where('sb.is_active', false);
        }
        if ($input->hasIsbn) {
            $query->whereNotNull('sb.isbn');
        }

        $rows = $query->orderBy('sb.id')
            ->limit($limit)
            ->get(['s.name as shop', 'sb.url']);

        return $this->toBatches($rows);
    }

    public function shopExists(string $shop): bool
    {
        return $this->connection()->table('shops')->where('name', $shop)->exists();
    }

    private function upsertSetting(int $shopId, string $key, string $value, string $type): void
    {
        $this->connection()->table('shop_settings')->updateOrInsert(
            ['shop_id' => $shopId, 'key' => $key],
            ['value' => $value, 'type' => $type],
        );
    }

    private function floatValue(float $value): string
    {
        $text = json_encode($value, JSON_THROW_ON_ERROR);

        return str_contains($text, '.') || str_contains($text, 'e') ? $text : $text.'.0';
    }

    /**
     * @param  iterable<mixed>  $rows
     * @return list<ShopUrlBatch>
     */
    private function toBatches(iterable $rows): array
    {
        $grouped = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $grouped[$row->string('shop')][] = $row->string('url');
        }

        $batches = [];
        foreach ($grouped as $shop => $urls) {
            $batches[] = new ShopUrlBatch($shop, $urls);
        }

        return $batches;
    }

    private function connection(): ConnectionInterface
    {
        return $this->database->connection();
    }
}
