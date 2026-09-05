<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Books\BookClassifier;
use App\Models\ShopBook;
use App\Support\UrlUtils;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use Psr\Log\LoggerInterface;
use Psr\Log\NullLogger;

/**
 * @phpstan-type NormalizedData array{
 *     sku?: string|null,
 *     type?: string|null,
 *     author?: string|null,
 *     isbn?: string|null,
 *     publisher?: string|null,
 *     year?: int|null,
 *     format?: string|null,
 *     description?: string|null,
 *     image_url?: string|null,
 *     categories?: list<string>|null,
 *     price?: numeric-string|null,
 *     price_original?: numeric-string|null,
 *     planned_availability_date?: string|null,
 *     rating?: numeric-string|null,
 *     review_count?: int|null,
 *     in_stock?: bool
 * }
 */
final readonly class ShopBookRepository
{
    private const array TRACKED_FIELDS = ['url', 'title'];

    public function __construct(
        private LoggerInterface $logger = new NullLogger,
        private ShopBookRelationsRepository $relations = new ShopBookRelationsRepository,
    ) {}

    public function unlinkCanonical(ShopBook $shopBook): void
    {
        ShopBook::whereKey($shopBook->getKey())->update(['book_id' => null]);
    }

    /**
     * @param  array<string, mixed>  $data
     * @param  array<string, mixed>|null  $properties
     */
    public function upsert(
        int $shopId,
        string $url,
        string $title,
        array $data = [],
        ?array $properties = null,
        ?int $runId = null,
    ): UpsertResult {
        $url = UrlUtils::normalize($url);
        $data = $this->normalizeData($data);
        $sku = $data['sku'] ?? null;

        $shopBook = $this->locate($shopId, $url, is_string($sku) ? $sku : null);
        $now = Date::now('UTC');

        return $shopBook instanceof ShopBook
            ? $this->update($shopBook, $url, $title, $data, $properties, $runId, $now)
            : $this->create($shopId, $url, $title, $data, $properties, $runId, $now);
    }

    private function locate(int $shopId, string $url, ?string $sku): ?ShopBook
    {
        $shopBook = null;

        if ($sku !== null && $sku !== '') {
            $shopBook = ShopBook::where('shop_id', $shopId)->where('sku', $sku)->first();
        }

        if ($shopBook !== null && $shopBook->url !== $url) {
            $urlOwner = ShopBook::where('shop_id', $shopId)->where('url', $url)->first();
            if ($urlOwner !== null && $urlOwner->id !== $shopBook->id) {
                $this->logger->warning(
                    'upsert_shop_book: stale SKU {sku} detached from shop_book {stale} '
                    .'(url={staleUrl}) — URL {url} already owned by shop_book {owner}. '
                    .'Likely cause: shop reassigned slug after wrong slug was scraped.',
                    [
                        'sku' => $sku,
                        'stale' => $shopBook->id,
                        'staleUrl' => $shopBook->url,
                        'url' => $url,
                        'owner' => $urlOwner->id,
                    ]
                );
                $shopBook->sku = null;
                $shopBook->save();
                $shopBook = $urlOwner;
            }
        }

        return $shopBook
            ?? ShopBook::where('shop_id', $shopId)->where('url', $url)->first();
    }

    /**
     * @param  NormalizedData  $data
     * @param  array<string, mixed>|null  $properties
     */
    private function create(
        int $shopId,
        string $url,
        string $title,
        array $data,
        ?array $properties,
        ?int $runId,
        Carbon $now,
    ): UpsertResult {
        $shopBook = new ShopBook;
        $shopBook->shop_id = $shopId;
        $shopBook->url = $url;
        $shopBook->title = $title;
        $shopBook->type = $data['type'] ?? $this->inferType($title, $data, $properties);
        $shopBook->author = $data['author'] ?? null;
        $shopBook->sku = $data['sku'] ?? null;
        $shopBook->isbn = $data['isbn'] ?? null;
        $shopBook->publisher = $data['publisher'] ?? null;
        $shopBook->year = $data['year'] ?? null;
        $shopBook->format = $data['format'] ?? null;
        $shopBook->description = $data['description'] ?? null;
        $shopBook->image_url = $data['image_url'] ?? null;
        $shopBook->categories = $data['categories'] ?? null;
        $shopBook->price = $data['price'] ?? null;
        $shopBook->price_original = $data['price_original'] ?? null;
        $shopBook->planned_availability_date = $data['planned_availability_date'] ?? null;
        $shopBook->rating = $data['rating'] ?? null;
        $shopBook->review_count = $data['review_count'] ?? null;
        $shopBook->in_stock = $data['in_stock'] ?? true;
        $shopBook->last_run_id = $runId;
        $shopBook->last_run_action = 'created';
        $shopBook->created_run_id = $runId;
        $shopBook->first_seen_at = $now;
        $shopBook->last_seen_at = $now;
        $shopBook->is_active = true;
        $shopBook->save();

        if ($properties !== null && $properties !== []) {
            $this->relations->syncAttributes($shopBook->id, $properties);
        }
        if (($data['author'] ?? null) !== null) {
            $this->relations->syncAuthors($shopBook->id, $data['author']);
        }

        return new UpsertResult($shopBook, true, null, []);
    }

    /**
     * @param  NormalizedData  $data
     * @param  array<string, mixed>|null  $properties
     */
    private function update(
        ShopBook $shopBook,
        string $url,
        string $title,
        array $data,
        ?array $properties,
        ?int $runId,
        Carbon $now,
    ): UpsertResult {
        $oldPrice = $shopBook->price;

        $oldIsbn = $shopBook->isbn;

        $shopBook->last_run_id = $runId;
        $shopBook->last_run_action = 'updated';

        $changes = [];
        $incoming = ['url' => $url, 'title' => $title];

        foreach (self::TRACKED_FIELDS as $field) {
            $new = $incoming[$field];
            if ($shopBook->{$field} !== $new) {
                $changes[] = $this->change($field, $shopBook->{$field}, $new);
            }
            $shopBook->{$field} = $new;
        }

        if (($data['author'] ?? null) !== null) {
            $changes = $this->track($changes, 'author', $shopBook->author, $data['author']);
            $shopBook->author = $data['author'];
        }
        if (($data['sku'] ?? null) !== null) {
            $changes = $this->track($changes, 'sku', $shopBook->sku, $data['sku']);
            $shopBook->sku = $data['sku'];
        }
        if (($data['isbn'] ?? null) !== null) {
            $changes = $this->track($changes, 'isbn', $shopBook->isbn, $data['isbn']);
            $shopBook->isbn = $data['isbn'];
        }
        if (($data['publisher'] ?? null) !== null) {
            $changes = $this->track($changes, 'publisher', $shopBook->publisher, $data['publisher']);
            $shopBook->publisher = $data['publisher'];
        }
        if (($data['year'] ?? null) !== null) {
            $changes = $this->track($changes, 'year', $shopBook->year, $data['year']);
            $shopBook->year = $data['year'];
        }
        if (($data['format'] ?? null) !== null) {
            $changes = $this->track($changes, 'format', $shopBook->format, $data['format']);
            $shopBook->format = $data['format'];
        }
        if (($data['description'] ?? null) !== null) {
            $changes = $this->track($changes, 'description', $shopBook->description, $data['description']);
            $shopBook->description = $data['description'];
        }

        if (($data['image_url'] ?? null) !== null) {
            $shopBook->image_url = $data['image_url'];
        }

        $changes = [...$changes, ...$this->guardIsbnDrift($shopBook, $data['isbn'] ?? null, $oldIsbn)];

        if (($data['type'] ?? null) !== null) {
            $shopBook->type = $data['type'];
        } elseif (($data['format'] ?? null) !== null) {
            $categories = $data['categories'] ?? $shopBook->categories;
            $shopBook->type = $this->inferType($shopBook->title, [
                'author' => $shopBook->author,
                'isbn' => $shopBook->isbn,
                'year' => $shopBook->year,
                'format' => $shopBook->format,
                'categories' => $categories,
            ], $properties);
        }

        if (($data['categories'] ?? null) !== null) {
            $shopBook->categories = $data['categories'];
        }
        if (($data['price'] ?? null) !== null) {
            $shopBook->price = $data['price'];
        }
        if (($data['price_original'] ?? null) !== null) {
            $shopBook->price_original = $data['price_original'];
        }
        if (($data['planned_availability_date'] ?? null) !== null) {
            $shopBook->planned_availability_date = $data['planned_availability_date'];
        }
        if (($data['rating'] ?? null) !== null) {
            $shopBook->rating = $data['rating'];
        }
        if (($data['review_count'] ?? null) !== null) {
            $shopBook->review_count = $data['review_count'];
        }
        $shopBook->in_stock = $data['in_stock'] ?? true;
        $shopBook->last_seen_at = $now;
        $shopBook->is_active = true;

        $shopBook->inactive_since = null;
        $shopBook->save();

        if ($properties !== null) {
            $this->relations->syncAttributes($shopBook->id, $properties);
        }
        if (($data['author'] ?? null) !== null) {
            $this->relations->syncAuthors($shopBook->id, $data['author']);
        }

        return new UpsertResult($shopBook, false, $oldPrice, $changes);
    }

    /** @return list<array{field: string, old: string|null, new: string|null}> */
    private function guardIsbnDrift(ShopBook $shopBook, ?string $isbn, ?string $oldIsbn): array
    {
        if ($isbn === null || $shopBook->book_id === null || $isbn === $oldIsbn) {
            return [];
        }

        $stillValid = DB::table('book_isbns')->where('book_id', $shopBook->book_id)
            ->where('isbn', $isbn)
            ->exists();
        if ($stillValid) {
            return [];
        }

        $changes = [$this->change('book_id', (string) $shopBook->book_id, null)];
        if ($shopBook->match_status !== 'unmatched') {
            $changes[] = $this->change('match_status', $shopBook->match_status, 'unmatched');
        }
        $shopBook->book_id = null;
        $shopBook->match_status = 'unmatched';

        return $changes;
    }

    /** @return list<string> */
    public static function splitAuthors(?string $raw): array
    {
        return ShopBookRelationsRepository::splitAuthors($raw);
    }

    public static function normalizeAuthor(string $name): string
    {
        return ShopBookRelationsRepository::normalizeAuthor($name);
    }

    /**
     * @param  NormalizedData  $data
     * @param  array<string, mixed>|null  $properties
     */
    private function inferType(string $title, array $data, ?array $properties): string
    {
        $properties ??= [];

        return BookClassifier::inferType([
            'title' => $title,
            'author' => $data['author'] ?? null,
            'isbn' => $data['isbn'] ?? null,
            'year' => $data['year'] ?? null,
            'format' => $data['format'] ?? null,
            'categories' => $data['categories'] ?? [],
            'pages' => $properties['pages'] ?? null,
            'cover_type' => $properties['cover_type'] ?? null,
            'translator' => $properties['translator'] ?? null,
            'narrator' => $properties['narrator'] ?? null,
            'duration' => $properties['duration'] ?? null,
            'schema_types' => [],
        ]);
    }

    /** @return array{field: string, old: string|null, new: string|null} */
    private function change(string $field, mixed $old, mixed $new): array
    {
        return [
            'field' => $field,
            'old' => $this->changeValue($old),
            'new' => $this->changeValue($new),
        ];
    }

    /**
     * @param  list<array{field: string, old: string|null, new: string|null}>  $changes
     * @return list<array{field: string, old: string|null, new: string|null}>
     */
    private function track(array $changes, string $field, mixed $old, mixed $new): array
    {
        if ($old !== $new) {
            $changes[] = $this->change($field, $old, $new);
        }

        return $changes;
    }

    private function changeValue(mixed $value): ?string
    {
        if ($value === null) {
            return null;
        }
        if (is_string($value)) {
            return $value;
        }

        return json_encode($value, JSON_THROW_ON_ERROR);
    }

    /**
     * @param  array<string, mixed>  $data
     * @return NormalizedData
     */
    private function normalizeData(array $data): array
    {
        $row = DatabaseRow::from($data);
        $normalized = [];
        foreach (['sku', 'type', 'author', 'isbn', 'publisher', 'format', 'description',
            'image_url', 'planned_availability_date'] as $field) {
            if ($row->has($field)) {
                $normalized[$field] = $row->nullableString($field);
            }
        }
        foreach (['year', 'review_count'] as $field) {
            if ($row->has($field)) {
                $normalized[$field] = $row->nullableInt($field);
            }
        }
        foreach (['price', 'price_original', 'rating'] as $field) {
            if ($row->has($field)) {
                $normalized[$field] = $this->numericString($row->value($field));
            }
        }
        if ($row->has('in_stock')) {
            $normalized['in_stock'] = $row->nullableBool('in_stock') ?? true;
        }
        if ($row->has('categories')) {
            $normalized['categories'] = $this->stringList($row->value('categories'));
        }

        return $normalized;
    }

    /** @return numeric-string|null */
    private function numericString(mixed $value): ?string
    {
        if ($value === null) {
            return null;
        }
        if (is_string($value) && is_numeric($value)) {
            return $value;
        }
        if (is_int($value) || is_float($value)) {
            return (string) $value;
        }

        return null;
    }

    /** @return list<string>|null */
    private function stringList(mixed $value): ?array
    {
        if ($value === null) {
            return null;
        }
        if (! is_array($value)) {
            return [];
        }

        return array_values(array_filter($value, is_string(...)));
    }
}
