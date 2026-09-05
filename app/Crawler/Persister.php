<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Repositories\Contracts\CrawlerPersistenceRepositoryInterface;
use App\Repositories\CrawlerPersistenceRepository;
use App\Repositories\DiscoveredUrlRepository;
use App\Repositories\ShopBookRepository;
use App\Repositories\UpsertResult;
use InvalidArgumentException;

/**
 * @phpstan-import-type ParsedItem from CrawlerTypes
 * @phpstan-import-type AttributeSchema from CrawlerTypes
 */
final readonly class Persister
{
    /** @param AttributeSchema|null $attributeSchema */
    public function __construct(
        private ShopBookRepository $shopBooks = new ShopBookRepository,
        private DiscoveredUrlRepository $urls = new DiscoveredUrlRepository,
        private CrawlerPersistenceRepositoryInterface $persistence = new CrawlerPersistenceRepository,
        private ?array $attributeSchema = null,
        private IssueBuffer $issues = new IssueBuffer,
    ) {}

    /**
     * @param  ParsedItem  $parsed
     * @return array{result: UpsertResult, price_written: bool}
     */
    public function persist(
        int $shopId,
        string $url,
        array $parsed,
        ?int $runId = null,
    ): array {

        ['item' => $parsed, 'reject' => $reject] = ItemValidator::apply(
            $parsed,
            $url,
            $this->attributeSchema,
            $this->issues,
        );
        if ($reject !== null) {
            throw new InvalidArgumentException("{$reject} ({$url})");
        }

        $title = $parsed['title'] ?? null;
        if (! is_string($title) || trim($title) === '') {
            throw new InvalidArgumentException("Parsed page for {$url} has no title");
        }
        $title = trim($title);

        ['data' => $data, 'properties' => $properties] = ItemBuilder::fromParsed($parsed);

        return $this->persistence->transaction(function () use ($shopId, $url, $title, $data, $properties, $runId): array {
            $result = $this->shopBooks->upsert($shopId, $url, $title, $data, $properties, $runId);

            $this->persistence->recordChanges($result, $runId);
            $this->recordClearedFields($result, $url);
            $priceWritten = $this->persistence->appendPrice($result, $data, $runId);

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

    private function recordClearedFields(UpsertResult $result, string $url): void
    {
        if ($result->changes === []) {
            return;
        }

        foreach ($result->changes as $change) {
            if ($change['old'] !== null && $change['new'] === null) {
                $this->issues->add(
                    'field_cleared',
                    $change['field'],
                    $url,
                    'was: '.$this->displayValue($change['old'])
                );
            }
        }
    }

    private function displayValue(mixed $value): string
    {
        if (is_string($value)) {
            return $value;
        }
        if (is_int($value) || is_float($value)) {
            return (string) $value;
        }
        if (is_bool($value)) {
            return $value ? 'true' : 'false';
        }

        $encoded = json_encode($value);

        return is_string($encoded) ? $encoded : get_debug_type($value);
    }
}
