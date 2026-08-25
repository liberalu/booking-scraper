<?php

declare(strict_types=1);

namespace BookScraper\Crawler;

use BookScraper\Models\Price;
use BookScraper\Repository\DiscoveredUrlRepository;
use BookScraper\Repository\ShopBookRepository;
use BookScraper\Repository\UpsertResult;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * The item pipeline: turns one parsed product page into the rows the
 * Python PostgresPipeline would write.
 *
 * Everything for one item happens in a single transaction — a half-written
 * item (shop_book saved, price missing) would look like a real price gap to
 * the validator.
 */
final class Persister
{
    /** Fields whose last-changed timestamp is tracked per book. */
    private const TRACKED_FIELDS = [
        'price', 'description', 'image_url', 'author', 'isbn', 'publisher',
        'year', 'format',
    ];

    /**
     * @param array{allowed_keys: list<string>, rules: array<string, array<string, mixed>>}|null $attributeSchema
     */
    public function __construct(
        private readonly ShopBookRepository $shopBooks = new ShopBookRepository(),
        private readonly DiscoveredUrlRepository $urls = new DiscoveredUrlRepository(),
        private readonly ?array $attributeSchema = null,
    ) {}

    /**
     * @param  array<string, mixed>  $parsed  Output of Parser::parseProductPage.
     * @return array{result: UpsertResult, price_written: bool}
     */
    public function persist(
        int $shopId,
        string $url,
        array $parsed,
        ?int $runId = null,
    ): array {
        // Validation runs before storage, as ValidationPipeline does: it
        // rewrites the item (description to Markdown, year unswapped, invalid
        // ISBN dropped, whitespace trimmed) and records what it noticed. A
        // rejected item is not stored at all.
        ['item' => $parsed, 'reject' => $reject] = ItemValidator::apply(
            $parsed,
            $url,
            $this->attributeSchema,
        );
        if ($reject !== null) {
            throw new \InvalidArgumentException("{$reject} ({$url})");
        }

        $title = $parsed['title'] ?? null;
        if (!is_string($title) || trim($title) === '') {
            throw new \InvalidArgumentException("Parsed page for {$url} has no title");
        }
        $title = trim($title);

        ['data' => $data, 'properties' => $properties] = ItemBuilder::fromParsed($parsed);

        return DB::transaction(function () use ($shopId, $url, $title, $data, $properties, $runId): array {
            $result = $this->shopBooks->upsert($shopId, $url, $title, $data, $properties, $runId);

            $this->recordChanges($result, $url, $runId);
            $priceWritten = $this->appendPrice($result, $data, $runId);

            // is_partial reads the PERSISTED isbn, not the incoming data:
            // a lighter item that only refreshes price must not mark a row
            // partial when an earlier scrape already captured the ISBN.
            $this->urls->linkToShopBook(
                $shopId,
                $url,
                $result->shopBook->id,
                $runId,
                isPartial: $result->shopBook->isbn === null,
            );

            return ['result' => $result, 'price_written' => $priceWritten];
        });
    }

    /**
     * `prices` is append-only and a row goes in on EVERY scrape that
     * carries a price — no change detection. That is deliberate upstream:
     * the table is the price history, and "we looked and it was still
     * 12.34" is a data point. It is also why the table is ~1.7M rows.
     *
     * @param array<string, mixed> $data
     */
    private function appendPrice(UpsertResult $result, array $data, ?int $runId): bool
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
            'scraped_at' => Carbon::now('UTC'),
            'scrape_run_id' => $runId,
        ]);

        return true;
    }

    /** One shop_book_changes row per tracked field that moved. */
    private function recordChanges(UpsertResult $result, string $url, ?int $runId): void
    {
        if ($result->changes === []) {
            return;
        }

        $now = Carbon::now('UTC');
        DB::table('shop_book_changes')->insert(array_map(
            fn (array $change): array => [
                'shop_book_id' => $result->shopBook->id,
                'scrape_run_id' => $runId,
                'field' => $change['field'],
                'old_value' => $change['old'],
                'new_value' => $change['new'],
                'changed_at' => $now,
            ],
            $result->changes
        ));

        $this->touchFieldUpdates($result->shopBook->id, $result->changes, $now);

        // A field going from a value to nothing is usually the shop dropping
        // data, not the book changing — worth an issue rather than a silent
        // overwrite.
        foreach ($result->changes as $change) {
            if ($change['old'] !== null && $change['new'] === null) {
                IssueBuffer::add(
                    'field_cleared',
                    (string) $change['field'],
                    $url,
                    'was: ' . $change['old']
                );
            }
        }
    }

    /**
     * Per-field "last changed" timestamps.
     *
     * Only the tracked fields, and only when the value actually moved — the
     * point is to answer "when did this book's price last change", which a
     * row-level updated_at cannot.
     *
     * @param list<array{field: string, old: string|null, new: string|null}> $changes
     */
    private function touchFieldUpdates(int $shopBookId, array $changes, Carbon $now): void
    {
        $fields = array_values(array_unique(array_filter(
            array_map(static fn (array $c): string => (string) $c['field'], $changes),
            static fn (string $field): bool => in_array($field, self::TRACKED_FIELDS, true)
        )));
        if ($fields === []) {
            return;
        }

        foreach ($fields as $field) {
            DB::table('shop_book_field_updates')->updateOrInsert(
                ['shop_book_id' => $shopBookId, 'field' => $field],
                ['updated_at' => $now],
            );
        }
    }
}
