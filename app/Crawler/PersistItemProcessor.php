<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Repositories\CanonicalBookRepository;
use App\Repositories\DiscoveredUrlRepository;
use App\Runs\ProgressReporter;
use RoachPHP\ItemPipeline\ItemInterface;
use RoachPHP\ItemPipeline\Processors\ItemProcessorInterface;
use RoachPHP\Support\Configurable;
use Throwable;

/**
 * Writes scraped items to the database.
 *
 * Handles the item shapes the spiders emit — `kind: 'url'` from discovery,
 * `kind: 'book'` from a product page or a category listing, `non_product`
 * for a successful scrape of something that isn't a book, and `canonical`
 * for a bibliographic record — mirroring the DiscoveredUrlItem /
 * ShopBookItem / BookItem branches of the Python pipeline.
 *
 * Run-scoped state is static because roach builds processors through the
 * container, so the CLI can't inject into the constructor.
 */
final class PersistItemProcessor implements ItemProcessorInterface
{
    use Configurable;

    private static ?Persister $persister = null;

    private static ?DiscoveredUrlRepository $urls = null;

    private static ?CanonicalBookRepository $canonical = null;

    private static int $shopId = 0;

    private static ?int $runId = null;

    /** @var array<string, int> */
    private static array $counts = [
        'added' => 0, 'updated' => 0, 'urls' => 0, 'non_product' => 0,
        'canonical' => 0, 'failed' => 0,
    ];

    public static function bind(
        Persister $persister,
        int $shopId,
        ?int $runId,
        ?DiscoveredUrlRepository $urls = null,
    ): void {
        self::$persister = $persister;
        self::$urls = $urls ?? new DiscoveredUrlRepository();
        self::$canonical = new CanonicalBookRepository();
        self::$shopId = $shopId;
        self::$runId = $runId;
        self::$counts = [
            'added' => 0, 'updated' => 0, 'urls' => 0, 'non_product' => 0,
            'canonical' => 0, 'failed' => 0,
        ];
    }

    /** @return array<string, int> */
    public static function tally(): array
    {
        return self::$counts;
    }

    public function processItem(ItemInterface $item): ItemInterface
    {
        if (self::$persister === null) {
            return $item;
        }

        $url = (string) $item->get('url');

        try {
            // 'book' is the default so the scan spider needn't tag items.
            match ($item->get('kind', 'book')) {
                'url' => $this->persistUrl($url, (string) $item->get('source', 'sitemap')),
                'non_product' => $this->markNonProduct($url, $item),
                'canonical' => $this->persistCanonical($url, (array) $item->get('parsed')),
                default => $this->persistBook($url, (array) $item->get('parsed')),
            };
        } catch (Throwable $e) {
            // One bad item must not abort the run — the URL simply stays
            // pending, and the reason is surfaced in the CLI summary.
            self::$counts['failed']++;
            fwrite(STDERR, sprintf("  persist failed  %s  %s\n", $url, $e->getMessage()));
        }

        // Let the run's counters move while it is still running. Throttled to
        // every tenth item inside the reporter.
        ProgressReporter::tick(self::$counts);

        return $item;
    }

    /**
     * Record that a URL is not a product.
     *
     * A successful scrape whose outcome is "not a book". The URL row is
     * stamped `non_product` so the delta scan stops revisiting it, and
     * nothing lands in shop_books.
     */
    private function markNonProduct(string $url, ItemInterface $item): void
    {
        self::$urls?->markNonProduct(
            self::$shopId,
            $url,
            self::$runId,
            (int) $item->get('book_score', 0),
            (array) $item->get('book_score_reasons', []),
        );
        self::$counts['non_product']++;
    }

    /**
     * A bibliographic record, not a shop listing.
     *
     * ibiblioteka is the national library: no price, no stock, nothing to
     * buy. Writing one of these to `shop_books` — which is what happens if
     * the parser's `_emit_as` tag is ignored, because the row does have a
     * title and does claim to be a book — invents a shop with 80k books and
     * no prices.
     *
     * @param array<string, mixed> $parsed
     */
    private function persistCanonical(string $url, array $parsed): void
    {
        // The parser only sees the body, so the spider supplies the URL —
        // same as `book["source_url"] = url` in the Python scan spider.
        $parsed['source_url'] = $url;
        self::$canonical?->upsert($parsed);
        self::$counts['canonical']++;
    }

    private function persistUrl(string $url, string $source): void
    {
        self::$urls?->upsert(self::$shopId, $url, $source, self::$runId);
        self::$counts['urls']++;
    }

    /** @param array<string, mixed> $parsed */
    private function persistBook(string $url, array $parsed): void
    {
        ['result' => $result] = self::$persister->persist(
            self::$shopId,
            $url,
            $parsed,
            self::$runId,
        );
        $result->created ? self::$counts['added']++ : self::$counts['updated']++;
    }
}
