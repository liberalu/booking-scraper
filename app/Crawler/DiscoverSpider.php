<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Discovery\GraphQlUrls;
use App\Discovery\IbibliotekaApiUrls;
use App\Discovery\LupaSearchUrls;
use App\Parsers\DiscoveryParser;
use App\Parsers\IbibliotekaSearchParser;
use App\Parsers\LupaSearchParser;
use App\Parsers\ProductParser;
use App\Runs\RunEvent;
use App\Runs\RunFailsafe;
use App\Support\ParserRegistry;
use App\Support\UrlUtils;
use Generator;
use RoachPHP\Extensions\LoggerExtension;
use RoachPHP\Extensions\StatsCollectorExtension;
use RoachPHP\Http\Request;
use RoachPHP\Http\Response;
use RoachPHP\Spider\BasicSpider;
use RoachPHP\Spider\ParseResult;
use RuntimeException;

final class DiscoverSpider extends BasicSpider
{
    public function __construct(private readonly CrawlerContext $crawler = new CrawlerContext)
    {
        parent::__construct();
    }

    public array $itemProcessors = [PersistItemProcessor::class];

    public array $extensions = [
        LoggerExtension::class,
        StatsCollectorExtension::class,
        ActivityExtension::class,
    ];

    private function passesFilter(string $url): bool
    {
        $pattern = $this->context['url_include_pattern'] ?? null;
        if (! is_string($pattern) || $pattern === '') {
            return true;
        }

        return preg_match('#'.$pattern.'#', $url) === 1;
    }

    private const LISTING_FIELDS = [
        'title', 'author', 'price', 'price_original', 'image_url',
        'type', 'sku', 'isbn', 'publisher', 'year', 'format',
        'description', 'categories',
    ];

    /** @return class-string<ProductParser&DiscoveryParser> */
    private function parser(): string
    {
        $parser = ParserRegistry::for($this->contextString('shop', 'vaga'));
        if (! is_a($parser, DiscoveryParser::class, true)) {
            throw new RuntimeException("Parser {$parser} does not support discovery.");
        }

        return $parser;
    }

    protected function initialRequests(): array
    {
        $strategy = $this->contextString('strategy', 'sitemap');

        $seeds = $this->stringList($this->context['seed_urls'] ?? null);
        if ($seeds !== []) {
            $requests = [];
            foreach ($seeds as $seed) {
                $requests[] = $this->seedRequest($strategy, $seed);
            }

            return $requests;
        }

        $url = $this->context['start_url'] ?? null;
        if (! is_string($url) || $url === '') {
            return [];
        }

        return [$this->seedRequest($strategy, $url)];
    }

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
     * @param  array{body: string, headers: array<string, string>}  $request
     * @return array{body: string, headers: array<string, string>}
     */
    private static function guzzleOptions(array $request): array
    {
        return ['body' => $request['body'], 'headers' => $request['headers']];
    }

    private function fetchChildSitemap(string $url): string
    {
        $context = stream_context_create(['http' => [
            'header' => 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                ."AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\r\n",
            'timeout' => 30,
        ]]);
        $body = @file_get_contents($url, false, $context);
        if ($body === false) {
            $this->crawler->issues()->add('discover_fetch_failed', 'url', $url, 'child sitemap fetch failed');

            return '';
        }

        return $body;
    }

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    public function parse(Response $response): Generator
    {
        yield from match ($this->contextString('strategy', 'sitemap')) {
            'categories' => $this->parseCategories($response),
            'graphql' => $this->parseGraphQl($response),
            'lupasearch' => $this->parseLupaSearch($response),
            'ibiblioteka_api' => $this->parseIbiblioteka($response),
            'full_crawl' => $this->parseFullCrawl($response),
            default => $this->parseSitemap($response),
        };
    }

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    public function parseSitemap(Response $response): Generator
    {

        $urls = ($this->parser())::parseSitemapUrls(
            $response->getBody(),
            $this->fetchChildSitemap(...),
        );

        $unique = array_values(array_unique($urls));
        $duplicates = count($urls) - count($unique);
        if ($duplicates > 0) {
            $this->crawler->issues()->add(
                'duplicate_sitemap_url',
                'url',
                $this->responseUrl($response),
                sprintf('%d duplicates in %d URLs', $duplicates, count($urls))
            );
        }

        foreach ($unique as $url) {
            if (! $this->passesFilter($url)) {
                $this->crawler->incrementFiltered();

                continue;
            }
            yield $this->item(['kind' => 'url', 'url' => $url, 'source' => 'sitemap']);
        }
    }

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    public function parseCategories(Response $response): Generator
    {
        $result = ($this->parser())::parseCategoryPage($response->getBody());
        $products = $result['products'];
        $page = $this->requestOptionInt($response, 'page', 1);

        if ($products === []) {

            if ($page === 1) {
                $this->crawler->issues()->add(
                    'discover_empty_first_page',
                    'url',
                    $this->responseUrl($response),
                    'page 1 returned 0 products (len='.strlen($response->getBody()).')'
                );
            }

            return;
        }

        yield from $this->emitProducts($products);

        if ($page !== 1) {

            return;
        }

        $total = $result['total'];
        if ($total === null || $total <= 0) {

            yield from $this->chainNextPage($response, $page + 1);

            return;
        }

        yield from $this->enqueueRemainingPages($total);
    }

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    private function enqueueRemainingPages(int $total): Generator
    {
        $pageSize = max(1, $this->contextInt('page_size', 100));
        $lastPage = (int) ceil($total / $pageSize);

        $maxPages = $this->contextInt('max_pages');
        if ($maxPages > 0) {
            $lastPage = min($lastPage, $maxPages);
        }

        $template = $this->contextString('url_template');
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

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    private function chainNextPage(Response $response, int $nextPage): Generator
    {
        $maxPages = $this->contextInt('max_pages');
        if ($maxPages > 0 && $nextPage > $maxPages) {
            return;
        }

        $current = $response->getRequest()->getUri();
        $next = preg_replace('/([?&](?:page|cntnt01page)=)\d+/', '${1}'.$nextPage, $current);

        if ($next === null || $next === $current) {
            $template = $this->contextString('url_template');
            if ($template === '') {
                return;
            }
            $next = str_replace('{page}', (string) $nextPage, $template);
        }

        yield $this->request('GET', $next, 'parseCategories', ['page' => $nextPage]);
    }

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    public function parseGraphQl(Response $response): Generator
    {
        if ($response->getStatus() >= 500 && $response->getStatus() < 600) {
            yield from $this->subdivideFailedGraphQlPage($response);

            return;
        }

        $result = ($this->parser())::parseCategoryPage($response->getBody());
        $products = $result['products'];
        $page = $this->requestOptionInt($response, 'page', 1);

        if ($products === []) {
            if ($page === 1) {
                $this->crawler->issues()->add(
                    'discover_empty_first_page',
                    'url',
                    $this->responseUrl($response),
                    'page 1 returned 0 products (len='.strlen($response->getBody()).')'
                );
            }

            return;
        }

        yield from $this->emitProducts($products);

        if (GraphQlUrls::parsePageUrl($response->getRequest()->getUri())['subdivision_depth'] >= 1) {
            return;
        }

        $total = $result['total'];
        if ($page === 1 && $total !== null && $total > 0) {
            yield from $this->enqueueRemainingGraphQlPages($total);

            return;
        }
        if ($total !== null) {

            return;
        }

        $next = $page + 1;
        $maxPages = $this->contextInt('max_pages');
        if ($maxPages > 0 && $next > $maxPages) {
            return;
        }
        yield $this->graphQlRequest($next, null, 0);
    }

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    private function enqueueRemainingGraphQlPages(int $total): Generator
    {
        $pageSize = max(1, $this->contextInt('page_size', 50));
        $lastPage = (int) ceil($total / $pageSize);
        $maxPages = $this->contextInt('max_pages');
        if ($maxPages > 0) {
            $lastPage = min($lastPage, $maxPages);
        }
        for ($page = 2; $page <= $lastPage; $page++) {
            yield $this->graphQlRequest($page, null, 0);
        }
    }

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    private function subdivideFailedGraphQlPage(Response $response): Generator
    {
        $url = $response->getRequest()->getUri();
        $meta = GraphQlUrls::parsePageUrl($url);
        $page = $meta['page'] !== 0
            ? $meta['page']
            : $this->requestOptionInt($response, 'page', 1);
        $pageSize = $meta['page_size'] !== 0
            ? $meta['page_size']
            : max(1, $this->contextInt('page_size', 50));
        $depth = $meta['subdivision_depth'];

        $this->crawler->issues()->add(
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

        $factor = max(2, $this->contextInt('subdivide_factor', 5));
        $minSize = max(1, $this->contextInt('subdivide_min_page_size', 1));
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
        $maxPages = $this->contextInt('max_pages');
        if ($maxPages > 0 && $normal > $maxPages) {
            return;
        }
        yield $this->graphQlRequest($normal, null, 0);
    }

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
        if (! is_int($runId)) {
            return;
        }
        try {
            (new RunFailsafe)->recordEvent($runId, RunEvent::SUBDIVIDED, [
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

    private function graphQlRequest(int $page, ?int $pageSizeOverride, int $depth): ParseResult
    {

        $categoryIds = $this->stringList($this->context['category_ids'] ?? null);
        $url = GraphQlUrls::buildPageUrl(
            $this->contextString('base_url'),
            $categoryIds,
            $pageSizeOverride ?? max(1, $this->contextInt('page_size', 50)),
            $page,
            $depth,
        );

        return $this->request('GET', $url, 'parseGraphQl', [
            'page' => $page,
            'headers' => ['Accept' => 'application/json'],
        ]);
    }

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    public function parseLupaSearch(Response $response): Generator
    {
        $parser = $this->parser();
        if (! is_a($parser, LupaSearchParser::class, true)) {
            throw new RuntimeException("Parser {$parser} does not support LupaSearch discovery.");
        }
        $result = $parser::parseLupasearchResponse($response->getBody());
        $products = $result['products'];
        $page = $this->requestOptionInt($response, 'page', 1);

        if ($products === []) {
            if ($page === 1) {
                $this->crawler->issues()->add(
                    'discover_empty_first_page',
                    'url',
                    $this->responseUrl($response),
                    'page 1 returned 0 products (len='.strlen($response->getBody()).')'
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

        $maxPages = $this->contextInt('max_pages');
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

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    public function parseIbiblioteka(Response $response): Generator
    {
        $parser = $this->parser();
        if (! is_a($parser, IbibliotekaSearchParser::class, true)) {
            throw new RuntimeException("Parser {$parser} does not support iBiblioteka discovery.");
        }
        $result = $parser::parseSearchResponse($response->getBody());
        $products = $result['products'];
        $page = $this->requestOptionInt($response, 'page', 1);

        if ($products === []) {
            if ($page === 1) {
                $this->crawler->issues()->add(
                    'discover_empty_first_page',
                    'url',
                    $this->responseUrl($response),
                    'page 1 returned 0 products (len='.strlen($response->getBody()).')'
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

        if ($count < $ps || $psi + $count >= 9900) {
            return;
        }

        $maxPages = $this->contextInt('max_pages');
        if ($maxPages > 0 && $page >= $maxPages) {
            return;
        }

        $nextUrl = IbibliotekaApiUrls::advance($url, $psi + $count);
        yield $this->request('POST', $nextUrl, 'parseIbiblioteka',
            ['page' => $page + 1] + self::guzzleOptions(IbibliotekaApiUrls::postRequest($nextUrl)));
    }

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    public function parseFullCrawl(Response $response): Generator
    {
        $baseUrl = rtrim($this->contextString('base_url'), '/');
        $currentUrl = explode('?', $this->responseUrl($response))[0];

        if ($this->passesFilter($currentUrl)) {
            $parsed = ($this->parser())::parseProductPage($response->getBody());

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
                'book_score_reasons' => [['key' => 'url_pattern_filtered', 'points' => 0]],
            ]);
        }

        $maxPages = $this->contextInt('max_pages');
        if ($maxPages > 0 && $this->crawler->seenCount() >= $maxPages) {
            return;
        }

        $stable = $this->stringSet($this->context['stable_urls'] ?? null);

        foreach ($this->internalLinks($response, $baseUrl) as $link) {
            if (! $this->crawler->remember($link)) {
                continue;
            }

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

    /** @return list<string> */
    private function internalLinks(Response $response, string $baseUrl): array
    {
        $links = [];
        foreach ($response->filter('a')->links() as $link) {
            $href = $link->getUri();
            if ($baseUrl !== '' && ! str_starts_with($href, $baseUrl)) {
                continue;
            }
            $links[explode('#', $href)[0]] = true;
        }

        return array_keys($links);
    }

    /**
     * @param  list<array<string, mixed>>  $products
     * @return Generator<mixed, ParseResult, mixed, mixed>
     */
    private function emitProducts(array $products): Generator
    {
        $baseUrl = $this->contextString('base_url');

        foreach ($products as $product) {
            $url = $product['url'] ?? null;
            if (! is_string($url) || $url === '') {
                continue;
            }
            if (! str_starts_with($url, 'http')) {
                $url = $baseUrl.$url;
            }

            if (! $this->passesFilter($url)) {
                $this->crawler->incrementFiltered();

                continue;
            }

            yield $this->item(['kind' => 'url', 'url' => $url, 'source' => 'category']);

            if (($product['is_book_product'] ?? null) === false) {
                continue;
            }

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

    private function contextString(string $key, string $default = ''): string
    {
        $value = $this->context[$key] ?? null;

        return is_string($value) ? $value : $default;
    }

    private function contextInt(string $key, int $default = 0): int
    {
        $value = $this->context[$key] ?? null;

        return is_int($value) ? $value : $default;
    }

    private function requestOptionInt(Response $response, string $key, int $default): int
    {
        $value = $response->getRequest()->getOptions()[$key] ?? null;

        return is_int($value) ? $value : $default;
    }

    private function responseUrl(Response $response): string
    {
        $url = $response->getUri();

        return is_string($url) ? $url : $response->getRequest()->getUri();
    }

    /** @return list<string> */
    private function stringList(mixed $values): array
    {
        if (! is_array($values)) {
            return [];
        }

        $strings = [];
        foreach ($values as $value) {
            if (is_string($value)) {
                $strings[] = $value;
            }
        }

        return $strings;
    }

    /** @return array<string, true> */
    private function stringSet(mixed $values): array
    {
        if (! is_array($values)) {
            return [];
        }

        $set = [];
        foreach ($values as $key => $value) {
            if (is_string($key) && $value === true) {
                $set[$key] = true;
            }
        }

        return $set;
    }
}
