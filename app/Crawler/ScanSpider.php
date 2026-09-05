<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Parsers\ProductParser;
use App\Parsers\ScanUrlRewriter;
use App\Support\CrawlerUrlPolicy;
use App\Support\ParserRegistry;
use Closure;
use Generator;
use Psr\Http\Message\RequestInterface;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\UriInterface;
use RoachPHP\Extensions\LoggerExtension;
use RoachPHP\Extensions\StatsCollectorExtension;
use RoachPHP\Http\Request;
use RoachPHP\Http\Response;
use RoachPHP\Spider\BasicSpider;
use RoachPHP\Spider\ParseResult;
use RuntimeException;

final class ScanSpider extends BasicSpider
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

    protected function initialRequests(): array
    {
        $urls = $this->strings($this->context['urls'] ?? null);
        $baseUrl = $this->baseUrl();
        foreach ($urls as $url) {
            CrawlerUrlPolicy::assertAllowed($url, $baseUrl);
        }

        $parser = $this->parser();

        return array_map(
            function (string $url) use ($parser): Request {

                $options = $this->requestOptions();
                if (is_a($parser, ScanUrlRewriter::class, true)) {
                    $rewrite = $parser::rewriteScanUrl($url);
                    if ($rewrite !== null) {
                        CrawlerUrlPolicy::assertAllowed($rewrite['url'], $this->baseUrl());

                        return new Request('GET', $rewrite['url'], $this->parse(...), [
                            ...$options,
                            'headers' => $rewrite['headers'],
                            'canonical_url' => $url,
                        ]);
                    }
                }

                return new Request('GET', $url, $this->parse(...), $options);
            },
            $urls
        );
    }

    /** @return class-string<ProductParser> */
    private function parser(): string
    {
        $shop = $this->context['shop'] ?? null;

        return ParserRegistry::for(is_string($shop) ? $shop : 'vaga');
    }

    /** @return array{allow_redirects: array{max: int, strict: bool, on_redirect: Closure}} */
    private function requestOptions(): array
    {
        $baseUrl = $this->baseUrl();

        return ['allow_redirects' => [
            'max' => 5,
            'strict' => true,
            'on_redirect' => static function (
                RequestInterface $request,
                ResponseInterface $response,
                UriInterface $uri,
            ) use ($baseUrl): void {
                CrawlerUrlPolicy::assertAllowed((string) $uri, $baseUrl);
            },
        ]];
    }

    private function baseUrl(): string
    {
        $baseUrl = $this->context['base_url'] ?? null;
        if (! is_string($baseUrl) || $baseUrl === '') {
            throw new RuntimeException('Crawler base URL is missing');
        }

        return $baseUrl;
    }

    /** @return Generator<mixed, ParseResult, mixed, mixed> */
    public function parse(Response $response): Generator
    {
        $request = $response->getRequest();

        $canonicalUrl = $request->getOptions()['canonical_url'] ?? null;
        $url = is_string($canonicalUrl) ? $canonicalUrl : $request->getUri();

        $parser = $this->parser();
        $body = $response->getBody();

        if (strlen($body) < 1024) {
            $this->crawler->issues()->add('empty_response', 'response', $url, 'len='.strlen($body));
        }

        $rewritten = ($request->getOptions()['canonical_url'] ?? null) !== null;
        if (! $rewritten) {
            $requestUrl = explode('?', $request->getUri())[0];
            $responseUri = $response->getUri();
            $finalUrl = is_string($responseUri) ? $responseUri : '';
            if ($finalUrl !== '' && $finalUrl !== $requestUrl) {
                $contextBase = $this->context['base_url'] ?? null;
                $base = rtrim(is_string($contextBase) ? $contextBase : '', '/');
                $path = str_replace($base, '', $finalUrl);
                if ($path === '' || $path === '/' || substr_count($path, '/') === 1) {
                    $this->crawler->issues()->add(
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
        if (! is_string($title) || trim($title) === '') {

            return;
        }

        if (($parsed['_emit_as'] ?? null) === 'book') {
            yield $this->item(['kind' => 'canonical', 'url' => $url, 'parsed' => $parsed]);

            return;
        }

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

    /** @return list<string> */
    private function strings(mixed $values): array
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
}
