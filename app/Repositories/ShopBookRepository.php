<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\BookIsbn;
use App\Models\ShopAuthor;
use App\Models\ShopBook;
use App\Models\ShopBookAttribute;
use App\Support\UrlUtils;
use App\Parsers\Vaga\Parser;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Psr\Log\LoggerInterface;
use Psr\Log\NullLogger;

/**
 * Port of upsert_shop_book() in book_scraper/db/repo.py.
 *
 * Every branch here exists because of a production incident; none of it is
 * defensive padding. Read the Python before changing any of it.
 */
final class ShopBookRepository
{
    /**
     * Fields always written, with a change row when the value moves.
     * `url` is here because a SKU match can find a row whose slug has
     * since been renamed.
     */
    private const TRACKED_FIELDS = ['url', 'title'];

    /**
     * Fields written ONLY when the scrape supplied a value. A lightweight
     * category-page scrape must not clobber metadata captured from the
     * full product page.
     */
    private const CONDITIONAL_FIELDS = [
        'author', 'sku', 'isbn', 'publisher', 'year', 'format', 'description',
    ];

    /** Separators seen in shop author strings. `ir` is Lithuanian "and". */
    private const MULTI_AUTHOR_PATTERN = '/(?:,\s|;|\s&\s|\s\/\s|\s+and\s+|\s+ir\s+)/iu';

    public function __construct(private readonly LoggerInterface $logger = new NullLogger()) {}

    /**
     * @param  array<string, mixed>  $data  Parsed product fields.
     * @param  array<string, mixed>|null  $properties  Format-specific extras.
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
        $sku = $data['sku'] ?? null;

        $shopBook = $this->locate($shopId, $url, is_string($sku) ? $sku : null);
        $now = Carbon::now('UTC');

        return $shopBook === null
            ? $this->create($shopId, $url, $title, $data, $properties, $runId, $now)
            : $this->update($shopBook, $url, $title, $data, $properties, $runId, $now);
    }

    /**
     * SKU first — it is durable across slug changes on shops that expose
     * one — then URL.
     */
    private function locate(int $shopId, string $url, ?string $sku): ?ShopBook
    {
        $shopBook = null;

        if ($sku !== null && $sku !== '') {
            $shopBook = ShopBook::where('shop_id', $shopId)->where('sku', $sku)->first();
        }

        // Stale-SKU split identity: the SKU matched a row sitting at a
        // DIFFERENT url, and the incoming url already belongs to another
        // row. Writing the url onto the SKU-matched row would violate
        // uq_shop_book_shop_url. Detach the SKU from the stale row and use
        // the url's owner instead. Seen when a shop fixes a wrong slug and
        // recycles the old one for a different product.
        if ($shopBook !== null && $shopBook->url !== $url) {
            $urlOwner = ShopBook::where('shop_id', $shopId)->where('url', $url)->first();
            if ($urlOwner !== null && $urlOwner->id !== $shopBook->id) {
                $this->logger->warning(
                    'upsert_shop_book: stale SKU {sku} detached from shop_book {stale} '
                    . '(url={staleUrl}) — URL {url} already owned by shop_book {owner}. '
                    . 'Likely cause: shop reassigned slug after wrong slug was scraped.',
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

    /** @param array<string, mixed> $data */
    private function create(
        int $shopId,
        string $url,
        string $title,
        array $data,
        ?array $properties,
        ?int $runId,
        Carbon $now,
    ): UpsertResult {
        $shopBook = new ShopBook();
        $shopBook->shop_id = $shopId;
        $shopBook->url = $url;
        $shopBook->title = $title;
        $shopBook->type = $data['type'] ?? self::inferType($title, $data, $properties);

        foreach (['author', 'sku', 'isbn', 'publisher', 'year', 'format', 'description',
                  'image_url', 'categories', 'price', 'price_original',
                  'planned_availability_date', 'rating', 'review_count'] as $field) {
            $shopBook->{$field} = $data[$field] ?? null;
        }
        $shopBook->in_stock = (bool) ($data['in_stock'] ?? true);
        $shopBook->last_run_id = $runId;
        $shopBook->last_run_action = 'created';
        $shopBook->created_run_id = $runId;
        $shopBook->first_seen_at = $now;
        $shopBook->last_seen_at = $now;
        $shopBook->is_active = true;
        $shopBook->save();

        if ($properties) {
            $this->syncAttributes($shopBook->id, $properties);
        }
        if (($data['author'] ?? null) !== null) {
            $this->syncAuthors($shopBook->id, (string) $data['author']);
        }

        return new UpsertResult($shopBook, true, null, []);
    }

    /** @param array<string, mixed> $data */
    private function update(
        ShopBook $shopBook,
        string $url,
        string $title,
        array $data,
        ?array $properties,
        ?int $runId,
        Carbon $now,
    ): UpsertResult {
        $oldPrice = $shopBook->price === null ? null : (string) $shopBook->price;
        // Captured before the conditional loop overwrites it — the drift
        // guard below must compare against the pre-scrape value.
        $oldIsbn = $shopBook->isbn;

        $shopBook->last_run_id = $runId;
        $shopBook->last_run_action = 'updated';

        $changes = [];
        $incoming = ['url' => $url, 'title' => $title];

        foreach (self::TRACKED_FIELDS as $field) {
            $new = $incoming[$field];
            if ($shopBook->{$field} !== $new) {
                $changes[] = self::change($field, $shopBook->{$field}, $new);
            }
            $shopBook->{$field} = $new;
        }

        foreach (self::CONDITIONAL_FIELDS as $field) {
            $new = $data[$field] ?? null;
            if ($new === null) {
                continue;
            }
            if ($shopBook->{$field} != $new) {
                $changes[] = self::change($field, $shopBook->{$field}, $new);
            }
            $shopBook->{$field} = $new;
        }

        if (($data['image_url'] ?? null) !== null) {
            $shopBook->image_url = $data['image_url'];
        }

        $changes = [...$changes, ...$this->guardIsbnDrift($shopBook, $data['isbn'] ?? null, $oldIsbn)];

        if (($data['type'] ?? null) !== null) {
            $shopBook->type = $data['type'];
        } elseif (($data['format'] ?? null) !== null) {
            $categories = $data['categories'] ?? $shopBook->categories;
            $shopBook->type = self::inferType(
                $shopBook->title,
                [
                    'author' => $shopBook->author,
                    'isbn' => $shopBook->isbn,
                    'year' => $shopBook->year,
                    'format' => $shopBook->format,
                    'categories' => $categories,
                ],
                $properties
            );
        }

        if (($data['categories'] ?? null) !== null) {
            $shopBook->categories = $data['categories'];
        }
        foreach (['price', 'price_original', 'planned_availability_date', 'rating', 'review_count'] as $field) {
            if (($data[$field] ?? null) !== null) {
                $shopBook->{$field} = $data[$field];
            }
        }
        $shopBook->in_stock = (bool) ($data['in_stock'] ?? true);
        $shopBook->last_seen_at = $now;
        $shopBook->is_active = true;
        // A returning shop_book clears its vanish stamp, so "inactive since"
        // keeps meaning the last transition rather than the first ever.
        $shopBook->inactive_since = null;
        $shopBook->save();

        if ($properties !== null) {
            $this->syncAttributes($shopBook->id, $properties);
        }
        if (($data['author'] ?? null) !== null) {
            $this->syncAuthors($shopBook->id, (string) $data['author']);
        }

        return new UpsertResult($shopBook, false, $oldPrice, $changes);
    }

    /**
     * When a linked shop_book's ISBN changes to one the canonical book
     * doesn't own, the link is stale. Null book_id and reset match_status
     * so match step 1 can re-link by the corrected ISBN — its
     * `WHERE book_id IS NULL` guard means an existing link is never
     * re-evaluated, which is how match_isbn_drift accumulates.
     *
     * @return list<array{field: string, old: string|null, new: string|null}>
     */
    private function guardIsbnDrift(ShopBook $shopBook, mixed $isbn, ?string $oldIsbn): array
    {
        if ($isbn === null || $shopBook->book_id === null || $isbn === $oldIsbn) {
            return [];
        }

        $stillValid = BookIsbn::where('book_id', $shopBook->book_id)
            ->where('isbn', $isbn)
            ->exists();
        if ($stillValid) {
            return [];
        }

        $changes = [self::change('book_id', (string) $shopBook->book_id, null)];
        if ($shopBook->match_status !== 'unmatched') {
            $changes[] = self::change('match_status', $shopBook->match_status, 'unmatched');
        }
        $shopBook->book_id = null;
        $shopBook->match_status = 'unmatched';

        return $changes;
    }

    /**
     * Only the supplied keys are touched: a partial scrape must not drop
     * attributes an earlier full scrape captured.
     *
     * @param array<string, mixed> $properties
     */
    private function syncAttributes(int $shopBookId, array $properties): void
    {
        if ($properties === []) {
            return;
        }

        $existing = ShopBookAttribute::where('shop_book_id', $shopBookId)
            ->get()
            ->keyBy('key');

        foreach ($properties as $key => $value) {
            $stringValue = self::pythonStr($value);
            $row = $existing->get($key);
            if ($row === null) {
                ShopBookAttribute::create([
                    'shop_book_id' => $shopBookId,
                    'key' => $key,
                    'value' => $stringValue,
                ]);
            } elseif ($row->value !== $stringValue) {
                $row->value = $stringValue;
                $row->save();
            }
        }
    }

    /**
     * The string Python's `str()` would produce for an attribute value.
     *
     * The column is text, and the Python writer stores `str(value)` — so a
     * boolean lands as 'True'/'False', not PHP's '1'/''. Getting this wrong
     * is invisible until something reads the value back: `is_new` would read
     * as absent for every new book pegasas reports.
     */
    private static function pythonStr(mixed $value): ?string
    {
        if ($value === null) {
            return null;
        }
        if (is_bool($value)) {
            return $value ? 'True' : 'False';
        }
        if (is_float($value)) {
            if (is_nan($value)) {
                return 'nan';
            }
            if (is_infinite($value)) {
                return $value > 0 ? 'inf' : '-inf';
            }
            // json_encode gives the shortest round-tripping form, which is
            // what repr() gives — but drops the '.0' on whole numbers.
            $text = (string) json_encode($value);

            return preg_match('/[.eE]/', $text) === 1 ? $text : $text . '.0';
        }
        if (is_array($value)) {
            // Python renders a list as "['a', 'b']". Attributes are scalars in
            // practice; encode rather than silently writing "Array".
            return (string) json_encode($value);
        }

        return (string) $value;
    }

    /**
     * Reconcile shop_authors + shop_book_authors so the book points at the
     * right authors in the right order. Called only when the scrape
     * actually supplied an author string.
     */
    private function syncAuthors(int $shopBookId, ?string $authorRaw): void
    {
        $desired = [];
        $seen = [];
        $position = 0;

        foreach (self::splitAuthors($authorRaw) as $name) {
            $normalized = self::normalizeAuthor($name);
            if ($normalized === '') {
                continue;
            }

            $author = ShopAuthor::where('normalized_name', $normalized)->first();
            if ($author === null) {
                $author = ShopAuthor::create([
                    'name' => $name,
                    'normalized_name' => $normalized,
                    'created_at' => Carbon::now('UTC'),
                ]);
            }
            // Keep only the first occurrence so (shop_book_id, author_id)
            // stays unique when a shop repeats a name.
            if (isset($seen[$author->id])) {
                continue;
            }
            $seen[$author->id] = true;
            $desired[$author->id] = $position++;
        }

        $existing = DB::table('shop_book_authors')
            ->where('shop_book_id', $shopBookId)
            ->pluck('position', 'author_id')
            ->all();

        foreach ($existing as $authorId => $currentPosition) {
            if (!array_key_exists($authorId, $desired)) {
                DB::table('shop_book_authors')
                    ->where('shop_book_id', $shopBookId)
                    ->where('author_id', $authorId)
                    ->delete();
            }
        }
        foreach ($desired as $authorId => $wanted) {
            if (!array_key_exists($authorId, $existing)) {
                DB::table('shop_book_authors')->insert([
                    'shop_book_id' => $shopBookId,
                    'author_id' => $authorId,
                    'position' => $wanted,
                ]);
            } elseif ((int) $existing[$authorId] !== $wanted) {
                DB::table('shop_book_authors')
                    ->where('shop_book_id', $shopBookId)
                    ->where('author_id', $authorId)
                    ->update(['position' => $wanted]);
            }
        }
    }

    /** @return list<string> */
    public static function splitAuthors(?string $raw): array
    {
        if ($raw === null || trim($raw) === '') {
            return [];
        }

        $parts = array_values(array_filter(
            array_map('trim', preg_split(self::MULTI_AUTHOR_PATTERN, $raw) ?: []),
            static fn (string $p): bool => $p !== ''
        ));

        // A single-author string still yields one item so callers can
        // always iterate.
        return $parts !== [] ? $parts : [trim($raw)];
    }

    public static function normalizeAuthor(string $name): string
    {
        return trim(preg_replace('/\s+/u', ' ', mb_strtolower(trim($name), 'UTF-8')) ?? '');
    }

    /** @param array<string, mixed> $data */
    private static function inferType(string $title, array $data, ?array $properties): string
    {
        $properties ??= [];

        return Parser::inferShopBookType([
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
    private static function change(string $field, mixed $old, mixed $new): array
    {
        return [
            'field' => $field,
            'old' => $old === null ? null : (string) $old,
            'new' => $new === null ? null : (string) $new,
        ];
    }
}
