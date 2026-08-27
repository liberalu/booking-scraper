<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Support\ParserRegistry;
use Generator;
use RoachPHP\Http\Request;
use RoachPHP\Http\Response;
use RoachPHP\Spider\BasicSpider;

/**
 * Scans product pages for any ported shop.
 *
 * The work list is a queue in discovered_urls, not a fixed set of seeds, so
 * URLs arrive through roach's spider context. `initialRequests()` is
 * overridden rather than setting `$startUrls`: the parent snapshots
 * startUrls into the run configuration at construction, while
 * `withContext()` runs afterwards, so a context-populated $startUrls is
 * always empty by the time roach reads it.
 *
 * Concurrency and delay come from the shop TOML via Overrides; the
 * sub-second delay is honoured by Scheduling\SubSecondRequestScheduler,
 * which RoachContainer binds over roach's whole-second default.
 */
final class ScanSpider extends BasicSpider
{
    public array $itemProcessors = [PersistItemProcessor::class];

    /**
     * ActivityExtension reports progress to the Watchdog. Roach's defaults
     * are kept: dropping LoggerExtension would also drop the run-statistics
     * line the CLI relies on.
     */
    public array $extensions = [
        \RoachPHP\Extensions\LoggerExtension::class,
        \RoachPHP\Extensions\StatsCollectorExtension::class,
        ActivityExtension::class,
    ];

    /** @return array<array-key, Request> */
    protected function initialRequests(): array
    {
        $urls = $this->context['urls'] ?? [];
        if (!is_array($urls)) {
            return [];
        }

        $parser = $this->parser();

        return array_map(
            function (string $url) use ($parser): Request {
                // pegasas serves a React shell for product pages, so its
                // parser rewrites the URL to a single-SKU GraphQL query.
                // Shops without a rewrite are fetched as-is.
                $options = [];
                if (method_exists($parser, 'rewriteScanUrl')) {
                    $rewrite = $parser::rewriteScanUrl($url);
                    if ($rewrite !== null) {
                        // The original URL is carried through so the row is
                        // keyed on the product page, not the GraphQL call.
                        return new Request('GET', $rewrite['url'], [$this, 'parse'], [
                            'headers' => $rewrite['headers'],
                            'canonical_url' => $url,
                        ]);
                    }
                }

                return new Request('GET', $url, [$this, 'parse'], $options);
            },
            array_values($urls)
        );
    }

    /** @return class-string */
    private function parser(): string
    {
        return ParserRegistry::for((string) ($this->context['shop'] ?? 'vaga'));
    }

    public function parse(Response $response): Generator
    {
        $request = $response->getRequest();
        // A rewritten request carries the product URL it stands in for; the
        // shop_book must be keyed on that, not on the GraphQL endpoint.
        $url = (string) ($request->getOptions()['canonical_url'] ?? $request->getUri());

        $parser = $this->parser();
        $body = $response->getBody();

        // A page this short did not carry a product, whatever the status
        // said. Worth recording: it usually means the shop served an error
        // page with a 200, which no HTTP-level check catches.
        if (strlen($body) < 1024) {
            IssueBuffer::add('empty_response', 'response', $url, 'len=' . strlen($body));
        }

        // A redirect to the homepage or a bare category means the product is
        // gone, and the shop chose to hide that behind a 200. Skipped for a
        // rewritten request: its response URL is the API endpoint by design,
        // so the check would fire on every one.
        $rewritten = ($request->getOptions()['canonical_url'] ?? null) !== null;
        if (!$rewritten) {
            $requestUrl = explode('?', $request->getUri())[0];
            $finalUrl = (string) $response->getUri();
            if ($finalUrl !== '' && $finalUrl !== $requestUrl) {
                $base = rtrim((string) ($this->context['base_url'] ?? ''), '/');
                $path = str_replace($base, '', $finalUrl);
                if ($path === '' || $path === '/' || substr_count($path, '/') === 1) {
                    IssueBuffer::add(
                        'redirect_to_homepage',
                        'url',
                        $requestUrl,
                        "redirected to {$finalUrl}"
                    );
                }
            }
        }

        $parsed = $parser::parseProductPage($body);

        $title = $parsed['title'] ?? null;
        if (!is_string($title) || trim($title) === '') {
            // Not a product page, or the layout moved. Skipped rather than
            // persisted: a titleless row trips NOT NULL on shop_books.title
            // and would read as a parser regression in the validator.
            return;
        }

        // A bibliographic record rather than a shop listing: ibiblioteka's
        // parser tags these `_emit_as: 'book'` because they belong in the
        // canonical `books` table, not in `shop_books`. Checked before the
        // is_book_product gate, which such a record also passes.
        if (($parsed['_emit_as'] ?? null) === 'book') {
            yield $this->item(['kind' => 'canonical', 'url' => $url, 'parsed' => $parsed]);

            return;
        }

        // The parser classified this as not a book — a category page, an
        // author listing, or genuine non-book merchandise (almalittera sells
        // Mažasis Princas water bottles alongside the books). That is a
        // SUCCESSFUL scrape whose outcome is "not a product", so the URL is
        // stamped non_product and nothing is written to shop_books.
        // Persisting it anyway is how a water bottle ends up in the
        // catalogue as type='non_book'.
        if (($parsed['is_book_product'] ?? false) !== true) {
            yield $this->item([
                'kind' => 'non_product',
                'url' => $url,
                'book_score' => $parsed['book_score'] ?? 0,
                'book_score_reasons' => $parsed['book_score_reasons'] ?? [],
            ]);

            return;
        }

        yield $this->item(['kind' => 'book', 'url' => $url, 'parsed' => $parsed]);
    }
}
