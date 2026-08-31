<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Parsers\DiscoveryParser;
use App\Support\Config;
use App\Support\ParserRegistry;
use Throwable;

final readonly class SerialCategoryDiscoverer
{
    private const array LISTING_FIELDS = [
        'title', 'author', 'price', 'price_original', 'image_url',
        'type', 'sku', 'isbn', 'publisher', 'year', 'format',
        'description', 'categories',
    ];

    public function __construct(
        private string $shop,
        private Config $config,
        private CrawlerContext $crawler,
    ) {}

    /**
     * @param  non-empty-list<string>  $templates
     * @return array{added: int, updated: int, urls: int, non_product: int, canonical: int, failed: int}
     */
    public function run(array $templates, int $maxPages): array
    {
        $flareConfig = $this->config->flaresolverr();
        if ($flareConfig === null) {
            throw new \RuntimeException("shop {$this->shop} has no [flaresolverr] block");
        }
        $flareSolverr = new FlareSolverr(
            $flareConfig['endpoint'],
            $flareConfig['max_timeout_ms'],
            $flareConfig['session_ttl_minutes'],
        );
        $parser = ParserRegistry::for($this->shop);
        if (! is_a($parser, DiscoveryParser::class, true)) {
            throw new \RuntimeException("Parser {$parser} does not support category discovery.");
        }
        $delay = (int) ($this->config->downloadDelay() * 1_000_000);
        $first = true;

        try {
            foreach ($templates as $template) {
                for ($page = 1; $maxPages === 0 || $page <= $maxPages; $page++) {
                    if (! $first && $delay > 0) {
                        usleep($delay);
                    }
                    $first = false;
                    $url = str_replace('{page}', (string) $page, $template);
                    $response = $flareSolverr->get($url);
                    $this->crawler->recordActivity();
                    if ($response['status'] !== 200) {
                        $this->crawler->increment('failed');
                        $this->crawler->issues()->add(
                            'discover_fetch_failed',
                            'url',
                            $url,
                            "HTTP {$response['status']}",
                        );
                        break;
                    }

                    $products = $parser::parseCategoryPage($response['body'])['products'];
                    if ($products === []) {
                        if ($page === 1) {
                            $this->crawler->issues()->add(
                                'discover_empty_first_page',
                                'url',
                                $url,
                                'page 1 returned 0 products (len='.strlen($response['body']).')',
                            );
                        }
                        break;
                    }
                    foreach ($products as $product) {
                        $this->persist($product);
                    }
                }
            }
        } finally {
            $flareSolverr->close();
        }

        return $this->crawler->tally();
    }

    /** @param array<string, mixed> $product */
    private function persist(array $product): void
    {
        $url = $product['url'] ?? null;
        if (! is_string($url) || $url === '') {
            return;
        }
        if (! str_starts_with($url, 'http')) {
            $url = $this->config->baseUrl().$url;
        }
        $pattern = $this->config->urlIncludePattern();
        if ($pattern !== null && preg_match('#'.$pattern.'#', $url) !== 1) {
            $this->crawler->incrementFiltered();

            return;
        }

        try {
            $this->crawler->urls()->upsert(
                $this->crawler->shopId(),
                $url,
                'category',
                $this->crawler->runId(),
            );
            $this->crawler->increment('urls');
            if (($product['is_book_product'] ?? null) === false
                || ($product['title'] ?? null) === null
                || ($product['price'] ?? null) === null) {
                $this->crawler->tick();

                return;
            }
            $parsed = ['in_stock' => $product['in_stock'] ?? true];
            foreach (self::LISTING_FIELDS as $field) {
                if (array_key_exists($field, $product)) {
                    $parsed[$field] = $product[$field];
                }
            }
            if (isset($product['properties']) && is_array($product['properties'])) {
                $parsed['properties'] = $product['properties'];
            }
            ['result' => $result] = $this->crawler->persister()?->persist(
                $this->crawler->shopId(),
                $url,
                $parsed,
                $this->crawler->runId(),
            ) ?? throw new \LogicException('crawler persistence is not configured');
            $this->crawler->increment($result->created ? 'added' : 'updated');
        } catch (Throwable $exception) {
            $this->crawler->increment('failed');
            fwrite(STDERR, "  persist failed  {$url}  {$exception->getMessage()}\n");
        }
        $this->crawler->tick();
    }
}
