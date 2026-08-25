<?php

declare(strict_types=1);

namespace BookScraper\Crawler;

use BookScraper\Discovery\GraphQlUrls;
use BookScraper\Runs\RunEvent;
use BookScraper\Runs\RunFailsafe;
use BookScraper\Discovery\IbibliotekaApiUrls;
use BookScraper\Discovery\LupaSearchUrls;
use BookScraper\ParserRegistry;
use BookScraper\UrlUtils;
use Generator;
use RoachPHP\Http\Request;
use RoachPHP\Http\Response;
use RoachPHP\Spider\BasicSpider;

/**
 * Finds URLs for any ported shop. Five strategies, chosen by the CLI
 * through context:
 *
 *  - `sitemap`         — one fetch of sitemap.xml, emits every URL it lists.
 *  - `categories`      — walks the paginated catalogue, emitting product URLs
 *                        plus partial book rows (title/author/price) for the
 *                        listings that carry them.
 *  - `graphql`         — Magento 2's GraphQL endpoint. Full metadata inline,
 *                        so the scan phase is a no-op for these shops.
 *  - `lupasearch`      — a third-party search index. Fast, but carries no
 *                        ISBN/year/pages; used for daily price rescans.
 *  - `ibiblioteka_api` — the national library's POST search API, walked in
 *                        monthly bands.
 *  - `full_crawl`      — follows every internal link from one seed. The
 *                        fallback for shops with neither a usable sitemap nor
 *                        a paginated listing.
 *
 * The last three are JSON APIs whose every request input is encoded into the
 * URL (see BookScraper\Discovery), so a queued URL is a complete request and
 * a resumed run reissues exactly what the original sent.
 *
 * Item processors receive a `kind` discriminator ('url' or 'book') because
 * discovery emits both shapes, mirroring the Python spider's
 * DiscoveredUrlItem / ShopBookItem pair.
 */
final class DiscoverSpider extends BasicSpider
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

    /**
     * URLs excluded by the shop's include pattern this run.
     *
     * Static because the CLI reads it after the crawl to record one
     * `url_pattern_filtered` issue for the run, the way the Python spider
     * does at close.
     */
    private static int $filtered = 0;

    /**
     * Every internal URL this run has queued, for `full_crawl`.
     *
     * Static for the same reason as $filtered: roach builds the spider through
     * its container, so there is no instance the CLI can reach. It doubles as
     * the follow budget — `max_pages` caps the size of this set.
     *
     * @var array<string, true>
     */
    private static array $seen = [];

    public static function resetFiltered(): void
    {
        self::$filtered = 0;
        self::$seen = [];
    }

    public static function filteredCount(): int
    {
        return self::$filtered;
    }

    /**
     * Whether a URL looks like a product for this shop.
     *
     * `url_include_pattern` is a Python regex in the TOML; it is used
     * unanchored, as `re.match` is, so it matches from the start of the URL.
     */
    private function passesFilter(string $url): bool
    {
        $pattern = $this->context['url_include_pattern'] ?? null;
        if (!is_string($pattern) || $pattern === '') {
            return true;
        }

        // `#` as the delimiter: the URL patterns are full of `/` and none
        // contain `#`, so nothing needs escaping and the pattern stays the
        // same string Python compiles.
        return preg_match('#' . $pattern . '#', $url) === 1;
    }

    /** Product fields the category listing can supply. */
    private const LISTING_FIELDS = [
        'title', 'author', 'price', 'price_original', 'image_url',
        'type', 'sku', 'isbn', 'publisher', 'year', 'format',
        'description', 'categories',
    ];

    /** @return class-string */
    private function parser(): string
    {
        return ParserRegistry::for((string) ($this->context['shop'] ?? 'vaga'));
    }

    /** @return array<array-key, Request> */
    protected function initialRequests(): array
    {
        $strategy = (string) ($this->context['strategy'] ?? 'sitemap');

        // The JSON APIs seed from a list: ibiblioteka opens one request per
        // calendar month, the others a single first page.
        $seeds = $this->context['seed_urls'] ?? null;
        if (is_array($seeds) && $seeds !== []) {
            $requests = [];
            foreach ($seeds as $seed) {
                $requests[] = $this->seedRequest($strategy, (string) $seed);
            }

            return $requests;
        }

        $url = $this->context['start_url'] ?? null;
        if (!is_string($url) || $url === '') {
            return [];
        }

        return [$this->seedRequest($strategy, $url)];
    }

    /** One seed request, with the method/body/headers its strategy needs. */
    private function seedRequest(string $strategy, string $url): Request
    {
        return match ($strategy) {
            'categories' => new Request('GET', $url, [$this, 'parseCategories'], ['page' => 1]),
            'graphql' => new Request('GET', $url, [$this, 'parseGraphQl'], [
                'page' => 1,
                'headers' => ['Accept' => 'application/json'],
            ]),
            'lupasearch' => new Request('POST', $url, [$this, 'parseLupaSearch'],
                ['page' => 1] + self::guzzleOptions(LupaSearchUrls::postRequest($url))),
            'ibiblioteka_api' => new Request('POST', $url, [$this, 'parseIbiblioteka'],
                ['page' => 1] + self::guzzleOptions(IbibliotekaApiUrls::postRequest($url))),
            'full_crawl' => new Request('GET', $url, [$this, 'parseFullCrawl'], ['page' => 1]),
            default => new Request('GET', $url, [$this, 'parseSitemap'], ['page' => 1]),
        };
    }

    /**
     * roach hands its request options straight to Guzzle, which understands
     * `body` and `headers` — so a POST needs no changes to roach itself.
     *
     * @param array{method: string, body: string, headers: array<string, string>} $request
     *
     * @return array{body: string, headers: array<string, string>}
     */
    private static function guzzleOptions(array $request): array
    {
        return ['body' => $request['body'], 'headers' => $request['headers']];
    }

    /**
     * A child sitemap, fetched synchronously.
     *
     * Blocking on purpose, matching upstream: discovery runs weekly, two
     * child sitemaps cost a couple of seconds, and threading them back
     * through the scheduler would mean a shop-specific hook in the generic
     * spider. The browser UA is deliberate — the shop serves an error page to
     * anything that looks like a crawler on this path.
     */
    private static function fetchChildSitemap(string $url): string
    {
        $context = stream_context_create(['http' => [
            'header' => "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                . "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\r\n",
            'timeout' => 30,
        ]]);
        $body = @file_get_contents($url, false, $context);
        if ($body === false) {
            IssueBuffer::add('discover_fetch_failed', 'url', $url, 'child sitemap fetch failed');

            return '';
        }

        return $body;
    }

    /**
     * roach requires `parse` on every spider. Discovery has two entry
     * points, so this dispatches on the configured strategy; the explicit
     * callbacks are still used for the paginated follow-up requests.
     */
    public function parse(Response $response): Generator
    {
        yield from match ((string) ($this->context['strategy'] ?? 'sitemap')) {
            'categories' => $this->parseCategories($response),
            'graphql' => $this->parseGraphQl($response),
            'lupasearch' => $this->parseLupaSearch($response),
            'ibiblioteka_api' => $this->parseIbiblioteka($response),
            'full_crawl' => $this->parseFullCrawl($response),
            default => $this->parseSitemap($response),
        };
    }

    // ---------------------------------------------------------------- sitemap

    public function parseSitemap(Response $response): Generator
    {
        // The child fetcher is for shops whose sitemap is an index of
        // sitemaps (patogupirkti: 61k product URLs across two children).
        // Parsers that take one argument ignore the extra one, and without it
        // an index parses to zero URLs and the run reports success having
        // discovered nothing.
        $urls = ($this->parser())::parseSitemapUrls(
            $response->getBody(),
            self::fetchChildSitemap(...),
        );

        // Deduplicate before emitting. A sitemap listing the same URL twice
        // is a shop-side bug worth surfacing, not a reason to write it twice.
        $unique = array_values(array_unique($urls));
        $duplicates = count($urls) - count($unique);
        if ($duplicates > 0) {
            IssueBuffer::add(
                'duplicate_sitemap_url',
                'url',
                (string) $response->getUri(),
                sprintf('%d duplicates in %d URLs', $duplicates, count($urls))
            );
        }

        foreach ($unique as $url) {
            if (!$this->passesFilter($url)) {
                self::$filtered++;
                continue;
            }
            yield $this->item(['kind' => 'url', 'url' => $url, 'source' => 'sitemap']);
        }
    }

    // ------------------------------------------------------------- categories

    public function parseCategories(Response $response): Generator
    {
        $result = ($this->parser())::parseCategoryPage($response->getBody());
        $products = $result['products'];
        $page = (int) ($response->getRequest()->getOptions()['page'] ?? 1);

        if ($products === []) {
            // An empty page 1 means the configured URL pattern is broken.
            // Worth shouting about: the alternative is another silent
            // "completed with 0 URLs" run.
            if ($page === 1) {
                IssueBuffer::add(
                    'discover_empty_first_page',
                    'url',
                    (string) $response->getUri(),
                    'page 1 returned 0 products (len=' . strlen($response->getBody()) . ')'
                );
            }

            return;
        }

        yield from $this->emitProducts($products);

        if ($page !== 1) {
            // Every page was enqueued from page 1; nothing to chain.
            return;
        }

        $total = $result['total'];
        if ($total === null || $total <= 0) {
            // No reliable count: fall back to chaining page+1.
            yield from $this->chainNextPage($response, $page + 1);

            return;
        }

        yield from $this->enqueueRemainingPages($total);
    }

    /**
     * Enqueue pages 2..N from page 1 so `concurrent_requests_per_domain`
     * actually engages. Chaining page+1 (yielded only after page N parses)
     * serialises discovery no matter what the concurrency is set to.
     */
    private function enqueueRemainingPages(int $total): Generator
    {
        $pageSize = max(1, (int) ($this->context['page_size'] ?? 100));
        $lastPage = (int) ceil($total / $pageSize);

        $maxPages = (int) ($this->context['max_pages'] ?? 0);
        if ($maxPages > 0) {
            $lastPage = min($lastPage, $maxPages);
        }

        $template = (string) ($this->context['url_template'] ?? '');
        if ($template === '') {
            return;
        }

        for ($page = 2; $page <= $lastPage; $page++) {
            yield $this->request(
                'GET',
                str_replace('{page}', (string) $page, $template),
                'parseCategories',
                ['page' => $page]
            );
        }
    }

    /** Bumps the page parameter in the response URL, as Python does. */
    private function chainNextPage(Response $response, int $nextPage): Generator
    {
        $maxPages = (int) ($this->context['max_pages'] ?? 0);
        if ($maxPages > 0 && $nextPage > $maxPages) {
            return;
        }

        $current = $response->getRequest()->getUri();
        $next = preg_replace('/([?&](?:page|cntnt01page)=)\d+/', '${1}' . $nextPage, $current);

        if ($next === null || $next === $current) {
            $template = (string) ($this->context['url_template'] ?? '');
            if ($template === '') {
                return;
            }
            $next = str_replace('{page}', (string) $nextPage, $template);
        }

        yield $this->request('GET', $next, 'parseCategories', ['page' => $nextPage]);
    }

    // ----------------------------------------------------------- graphql

    /**
     * A page of Magento's GraphQL products query.
     *
     * A 5xx is not parsed but subdivided: Magento's full-page cache misses on
     * deep pages produce transient 503s at pageSize=50, and refetching the
     * same range as several small pages usually slips through.
     */
    public function parseGraphQl(Response $response): Generator
    {
        if ($response->getStatus() >= 500 && $response->getStatus() < 600) {
            yield from $this->subdivideFailedGraphQlPage($response);

            return;
        }

        $result = ($this->parser())::parseCategoryPage($response->getBody());
        $products = $result['products'];
        $page = (int) ($response->getRequest()->getOptions()['page'] ?? 1);

        if ($products === []) {
            if ($page === 1) {
                IssueBuffer::add(
                    'discover_empty_first_page',
                    'url',
                    (string) $response->getUri(),
                    'page 1 returned 0 products (len=' . strlen($response->getBody()) . ')'
                );
            }

            return;
        }

        yield from $this->emitProducts($products);

        // A sub-page covers a slice of a page that already failed; the
        // handler that created it owns pagination, so stop here or the next
        // normal page gets enqueued once per sub-page.
        if (GraphQlUrls::parsePageUrl($response->getRequest()->getUri())['subdivision_depth'] >= 1) {
            return;
        }

        $total = $result['total'];
        if ($page === 1 && $total !== null && $total > 0) {
            yield from $this->enqueueRemainingGraphQlPages($total);

            return;
        }
        if ($total !== null) {
            // Upfront mode: page 1 queued the rest.
            return;
        }

        $next = $page + 1;
        $maxPages = (int) ($this->context['max_pages'] ?? 0);
        if ($maxPages > 0 && $next > $maxPages) {
            return;
        }
        yield $this->graphQlRequest($next, null, 0);
    }

    private function enqueueRemainingGraphQlPages(int $total): Generator
    {
        $pageSize = max(1, (int) ($this->context['page_size'] ?? 50));
        $lastPage = (int) ceil($total / $pageSize);
        $maxPages = (int) ($this->context['max_pages'] ?? 0);
        if ($maxPages > 0) {
            $lastPage = min($lastPage, $maxPages);
        }
        for ($page = 2; $page <= $lastPage; $page++) {
            yield $this->graphQlRequest($page, null, 0);
        }
    }

    /**
     * Refetch a 5xx page as N smaller ones.
     *
     * An already-subdivided page that fails again is not split further —
     * that would recurse without bound. Pagination continues either way, so
     * one bad range does not end the crawl.
     */
    private function subdivideFailedGraphQlPage(Response $response): Generator
    {
        $url = $response->getRequest()->getUri();
        $meta = GraphQlUrls::parsePageUrl($url);
        $page = $meta['page'] ?: (int) ($response->getRequest()->getOptions()['page'] ?? 1);
        $pageSize = $meta['page_size'] ?: max(1, (int) ($this->context['page_size'] ?? 50));
        $depth = $meta['subdivision_depth'];

        IssueBuffer::add(
            'discover_backend_5xx',
            'url',
            $url,
            sprintf(
                'HTTP %d on page %d (size %d, depth %d)',
                $response->getStatus(),
                $page,
                $pageSize,
                $depth
            )
        );

        if ($depth >= 1) {
            fwrite(STDERR, sprintf(
                "  subdivided page %d (size %d) failed again — leaving it for the next run\n",
                $page,
                $pageSize
            ));
            $this->recordSubdivision('micro_range_failed', $page, $pageSize, $depth,
                $response->getStatus(), 0, null);

            return;
        }

        $factor = max(2, (int) ($this->context['subdivide_factor'] ?? 5));
        $minSize = max(1, (int) ($this->context['subdivide_min_page_size'] ?? 1));
        $subSize = max($minSize, intdiv($pageSize, $factor));
        $ratio = max(1, intdiv($pageSize, $subSize));
        $firstSub = ($page - 1) * $ratio + 1;

        printf(
            "  subdividing page %d (size %d) into %d × pageSize=%d\n",
            $page,
            $pageSize,
            $ratio,
            $subSize
        );
        for ($i = 0; $i < $ratio; $i++) {
            yield $this->graphQlRequest($firstSub + $i, $subSize, 1);
        }
        $this->recordSubdivision('subdivided', $page, $pageSize, $depth,
            $response->getStatus(), $ratio, $subSize);

        $normal = $page + 1;
        $maxPages = (int) ($this->context['max_pages'] ?? 0);
        if ($maxPages > 0 && $normal > $maxPages) {
            return;
        }
        yield $this->graphQlRequest($normal, null, 0);
    }

    /**
     * Put each subdivision on the run's Timeline card.
     *
     * Without it the run goes quiet while the spider works around a
     * struggling backend, and the only visible sign is the stall that
     * follows if it doesn't recover.
     */
    private function recordSubdivision(
        string $outcome,
        int $page,
        int $pageSize,
        int $depth,
        int $httpStatus,
        int $subCount,
        ?int $subSize,
    ): void {
        $runId = $this->context['run_id'] ?? null;
        if (!is_int($runId)) {
            return;
        }
        try {
            RunFailsafe::recordEvent($runId, RunEvent::SUBDIVIDED, [
                'outcome' => $outcome,
                'page' => $page,
                'page_size' => $pageSize,
                'depth' => $depth,
                'http_status' => $httpStatus,
                'sub_count' => $subCount,
                'sub_size' => $subSize,
            ]);
        } catch (\Throwable $e) {
            fwrite(STDERR, "  could not record subdivision event: {$e->getMessage()}\n");
        }
    }

    private function graphQlRequest(int $page, ?int $pageSizeOverride, int $depth): mixed
    {
        /** @var list<string> $categoryIds */
        $categoryIds = (array) ($this->context['category_ids'] ?? []);
        $url = GraphQlUrls::buildPageUrl(
            (string) ($this->context['base_url'] ?? ''),
            $categoryIds,
            $pageSizeOverride ?? max(1, (int) ($this->context['page_size'] ?? 50)),
            $page,
            $depth,
        );

        return $this->request('GET', $url, 'parseGraphQl', [
            'page' => $page,
            'headers' => ['Accept' => 'application/json'],
        ]);
    }

    // -------------------------------------------------------- lupasearch

    /**
     * A page of the LupaSearch index.
     *
     * Upfront pagination keys off the URL's offset rather than the request's
     * page number: a re-dispatched page from a resumed run carries no page
     * number, and mistaking it for page 1 would re-enqueue the whole tail.
     */
    public function parseLupaSearch(Response $response): Generator
    {
        $result = ($this->parser())::parseLupasearchResponse($response->getBody());
        $products = $result['products'];
        $page = (int) ($response->getRequest()->getOptions()['page'] ?? 1);

        if ($products === []) {
            if ($page === 1) {
                IssueBuffer::add(
                    'discover_empty_first_page',
                    'url',
                    (string) $response->getUri(),
                    'page 1 returned 0 products (len=' . strlen($response->getBody()) . ')'
                );
            }

            return;
        }

        yield from $this->emitProducts($products);

        $url = $response->getRequest()->getUri();
        [$offset, $limit] = LupaSearchUrls::parseOffsets($url);
        $total = $result['total'];
        if ($offset !== 0 || $total <= 0 || $limit <= 0) {
            return;
        }

        $maxPages = (int) ($this->context['max_pages'] ?? 0);
        $nextPage = 2;
        for ($next = $limit; $next < $total; $next += $limit) {
            if ($maxPages > 0 && $nextPage > $maxPages) {
                return;
            }
            $nextUrl = LupaSearchUrls::advance($url, $next);
            yield $this->request('POST', $nextUrl, 'parseLupaSearch',
                ['page' => $nextPage] + self::guzzleOptions(LupaSearchUrls::postRequest($nextUrl)));
            $nextPage++;
        }
    }

    // ---------------------------------------------------- ibiblioteka_api

    /**
     * A page of the library search API.
     *
     * URLs only — the full record comes from the scan phase, which fetches
     * each detail endpoint. Chained rather than enqueued upfront because the
     * response carries no total, and the server caps a search at
     * pageStartIndex ~9,900.
     */
    public function parseIbiblioteka(Response $response): Generator
    {
        $result = ($this->parser())::parseSearchResponse($response->getBody());
        $products = $result['products'];
        $page = (int) ($response->getRequest()->getOptions()['page'] ?? 1);

        if ($products === []) {
            if ($page === 1) {
                IssueBuffer::add(
                    'discover_empty_first_page',
                    'url',
                    (string) $response->getUri(),
                    'page 1 returned 0 products (len=' . strlen($response->getBody()) . ')'
                );
            }

            return;
        }

        foreach ($products as $product) {
            $url = $product['url'] ?? null;
            if (is_string($url) && $url !== '') {
                yield $this->item(['kind' => 'url', 'url' => $url, 'source' => 'category']);
            }
        }

        $url = $response->getRequest()->getUri();
        [$psi, $ps] = IbibliotekaApiUrls::parseParams($url);
        $count = count($products);
        // A short page is the last one, and the server refuses to look past
        // ~9,900 records in a single search.
        if ($count < $ps || $psi + $count >= 9900) {
            return;
        }

        $maxPages = (int) ($this->context['max_pages'] ?? 0);
        if ($maxPages > 0 && $page >= $maxPages) {
            return;
        }

        $nextUrl = IbibliotekaApiUrls::advance($url, $psi + $count);
        yield $this->request('POST', $nextUrl, 'parseIbiblioteka',
            ['page' => $page + 1] + self::guzzleOptions(IbibliotekaApiUrls::postRequest($nextUrl)));
    }

    // -------------------------------------------------------- full_crawl

    /**
     * Follow every internal link from one seed.
     *
     * The fallback for shops with neither a usable sitemap nor a paginated
     * listing. Two rules carry the weight:
     *
     *  * The include pattern decides *classification*, not just whether to
     *    emit. A page whose URL matches is parsed as a product; one that does
     *    not is followed purely as crawl frontier and stamped `non_product`,
     *    so the scan phase stops revisiting it.
     *  * `max_pages` caps the number of URLs queued, not the number fetched.
     *    Pages already in flight are still classified once the budget is
     *    spent — the response is paid for, so throwing away its verdict would
     *    be worse than recording it.
     */
    public function parseFullCrawl(Response $response): Generator
    {
        $baseUrl = rtrim((string) ($this->context['base_url'] ?? ''), '/');
        $currentUrl = explode('?', (string) $response->getUri())[0];

        if ($this->passesFilter($currentUrl)) {
            $parsed = ($this->parser())::parseProductPage($response->getBody());
            // A title is enough: the page was reachable and looks like a
            // product, and the scan phase will settle the details.
            if (($parsed['is_book_product'] ?? false) === true || ($parsed['title'] ?? null) !== null) {
                yield from $this->emitProducts([['url' => $currentUrl] + $parsed]);
            } else {
                yield $this->item([
                    'kind' => 'non_product',
                    'url' => $currentUrl,
                    'book_score' => $parsed['book_score'] ?? 0,
                    'book_score_reasons' => $parsed['book_score_reasons'] ?? [],
                ]);
            }
        } else {
            yield $this->item([
                'kind' => 'non_product',
                'url' => $currentUrl,
                'book_score' => 0,
                'book_score_reasons' => [['reason' => 'url_pattern_filtered']],
            ]);
        }

        $maxPages = (int) ($this->context['max_pages'] ?? 0);
        if ($maxPages > 0 && count(self::$seen) >= $maxPages) {
            return;
        }

        /** @var array<string, true> $stable */
        $stable = $this->context['stable_urls'] ?? [];

        foreach ($this->internalLinks($response, $baseUrl) as $link) {
            if (isset(self::$seen[$link])) {
                continue;
            }
            self::$seen[$link] = true;

            // Already classified recently: follow it to find new outgoing
            // links, but don't re-emit the URL row.
            if (isset($stable[UrlUtils::normalize($link)])) {
                yield $this->request('GET', $link, 'parseFullCrawl', ['page' => 1]);
                continue;
            }

            if ($this->passesFilter($link)) {
                yield $this->item(['kind' => 'url', 'url' => $link, 'source' => 'full_crawl']);
            }
            yield $this->request('GET', $link, 'parseFullCrawl', ['page' => 1]);
        }
    }

    /**
     * Absolute internal links on the page, deduplicated in document order.
     *
     * Hrefs are trimmed, which is what a browser does. vaga's homepage carries
     * 65 whitespace-padded hrefs (`href="/atmosfera "`), and untrimmed, 62 of
     * them are distinct URLs from their clean twins — so each of those products
     * is fetched twice and can get a duplicate `discovered_urls` row. Measured
     * on the same bytes: 629 links untrimmed, 565 here, the 64-link gap being
     * those plus the bare-host and fragment-only forms.
     *
     * This started as a deliberate divergence; Python trims too now
     * (`spiders/discover.py`), so the two agree. Nothing here calls trim()
     * explicitly — DomCrawler's link resolution does it — which is why
     * DiscoverEmitTest pins it.
     *
     * @return list<string>
     */
    private function internalLinks(Response $response, string $baseUrl): array
    {
        $links = [];
        foreach ($response->filter('a')->links() as $link) {
            $href = $link->getUri();
            if ($baseUrl !== '' && !str_starts_with($href, $baseUrl)) {
                continue;
            }
            $links[explode('#', $href)[0]] = true;
        }

        return array_keys($links);
    }

    /** @param list<array<string, mixed>> $products */
    private function emitProducts(array $products): Generator
    {
        $baseUrl = (string) ($this->context['base_url'] ?? '');

        foreach ($products as $product) {
            $url = $product['url'] ?? null;
            if (!is_string($url) || $url === '') {
                continue;
            }
            if (!str_starts_with($url, 'http')) {
                $url = $baseUrl . $url;
            }

            if (!$this->passesFilter($url)) {
                self::$filtered++;
                continue;
            }

            yield $this->item(['kind' => 'url', 'url' => $url, 'source' => 'category']);

            // Don't create a shop_book row for something the parser already
            // called a non-book. The URL is still tracked above, so the scan
            // will fetch the page and set url_type authoritatively. Writing
            // one here produces url_type='product' / type='non_book'
            // mismatches that persist until the next scan corrects them.
            if (($product['is_book_product'] ?? null) === false) {
                continue;
            }

            // A listing row is only worth persisting with at least a title
            // and a price; anything thinner would just be a stub.
            if (($product['title'] ?? null) === null || ($product['price'] ?? null) === null) {
                continue;
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

            yield $this->item(['kind' => 'book', 'url' => $url, 'parsed' => $parsed]);
        }
    }
}
