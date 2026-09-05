<?php

declare(strict_types=1);

namespace App\Crawler;

use LogicException;
use RoachPHP\ItemPipeline\ItemInterface;
use RoachPHP\ItemPipeline\Processors\ItemProcessorInterface;
use RoachPHP\Support\Configurable;
use Throwable;
use UnexpectedValueException;

/**
 * @phpstan-import-type ParsedItem from CrawlerTypes
 * @phpstan-import-type BookScoreReason from CrawlerTypes
 */
final class PersistItemProcessor implements ItemProcessorInterface
{
    use Configurable;

    public function __construct(private readonly CrawlerContext $context = new CrawlerContext) {}

    public function processItem(ItemInterface $item): ItemInterface
    {
        if (! $this->context->persister() instanceof Persister) {
            return $item;
        }

        try {
            $url = $this->requiredString($item->get('url'), 'url');
            $kind = $item->get('kind', 'book');
            $kind = is_string($kind) ? $kind : 'book';

            match ($kind) {
                'url' => $this->persistUrl(
                    $url,
                    $this->string($item->get('source', 'sitemap'), 'sitemap'),
                ),
                'non_product' => $this->markNonProduct($url, $item),
                'canonical' => $this->persistCanonical($url, $this->parsed($item->get('parsed'))),
                default => $this->persistBook($url, $this->parsed($item->get('parsed'))),
            };
        } catch (Throwable $e) {

            $this->context->increment('failed');
            fwrite(STDERR, sprintf(
                "  persist failed  %s  %s\n",
                $url ?? '<missing-url>',
                $e->getMessage(),
            ));
        }

        $this->context->tick();

        return $item;
    }

    private function markNonProduct(string $url, ItemInterface $item): void
    {
        $this->context->urls()->markNonProduct(
            $this->context->shopId(),
            $url,
            $this->context->runId(),
            $this->integer($item->get('book_score', 0), 0),
            $this->scoreReasons($item->get('book_score_reasons', [])),
        );
        $this->context->increment('non_product');
    }

    /** @param ParsedItem $parsed */
    private function persistCanonical(string $url, array $parsed): void
    {

        $parsed['source_url'] = $url;
        $this->context->canonical()->upsert($parsed);
        $this->context->increment('canonical');
    }

    private function persistUrl(string $url, string $source): void
    {
        $this->context->urls()->upsert(
            $this->context->shopId(),
            $url,
            $source,
            $this->context->runId(),
        );
        $this->context->increment('urls');
    }

    /** @param ParsedItem $parsed */
    private function persistBook(string $url, array $parsed): void
    {
        ['result' => $result] = $this->context->persister()?->persist(
            $this->context->shopId(),
            $url,
            $parsed,
            $this->context->runId(),
        ) ?? throw new LogicException('crawler persistence is not configured');
        $this->context->increment($result->created ? 'added' : 'updated');
    }

    private function requiredString(mixed $value, string $field): string
    {
        if (! is_string($value) || $value === '') {
            throw new UnexpectedValueException("Crawler item has no {$field}.");
        }

        return $value;
    }

    private function string(mixed $value, string $default): string
    {
        return is_string($value) ? $value : $default;
    }

    private function integer(mixed $value, int $default): int
    {
        return is_int($value) ? $value : $default;
    }

    /** @return ParsedItem */
    private function parsed(mixed $value): array
    {
        if (! is_array($value)) {
            return [];
        }

        $parsed = [];
        foreach ($value as $key => $item) {
            if (is_string($key)) {
                $parsed[$key] = $item;
            }
        }

        return $parsed;
    }

    /** @return list<BookScoreReason> */
    private function scoreReasons(mixed $value): array
    {
        if (! is_array($value)) {
            return [];
        }

        $reasons = [];
        foreach ($value as $reason) {
            if (! is_array($reason)) {
                continue;
            }
            $key = $reason['key'] ?? null;
            $points = $reason['points'] ?? null;
            if (is_string($key) && is_int($points)) {
                $reasons[] = ['key' => $key, 'points' => $points];
            }
        }

        return $reasons;
    }
}
