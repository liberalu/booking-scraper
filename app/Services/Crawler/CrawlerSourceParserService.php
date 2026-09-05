<?php

declare(strict_types=1);

namespace App\Services\Crawler;

use App\Parsers\DiscoveryParser;
use App\Support\Config;
use App\Support\ParserRegistry;
use GuzzleHttp\Client;
use GuzzleHttp\Exception\GuzzleException;
use Illuminate\Support\Sleep;
use RuntimeException;

final readonly class CrawlerSourceParserService
{
    public function __construct(private Client $http) {}

    /** @return array<string, mixed>|list<string> */
    public function parse(
        string $shop,
        ?string $url,
        ?string $file,
        ?string $kind,
        ?string $userAgent,
    ): array {
        $parser = ParserRegistry::for($shop);
        [$source, $resolvedKind] = $this->source($shop, $url, $file, $kind, $userAgent);

        return match ($resolvedKind) {
            'product' => $parser::parseProductPage($source),
            'category' => is_subclass_of($parser, DiscoveryParser::class)
                ? $parser::parseCategoryPage($source)
                : throw new RuntimeException("{$shop} does not support category parsing"),
            'sitemap' => is_subclass_of($parser, DiscoveryParser::class)
                ? $parser::parseSitemapUrls($source)
                : throw new RuntimeException("{$shop} does not support sitemap parsing"),
            default => throw new RuntimeException(
                "Unknown parser kind '{$resolvedKind}' (expected product, category, or sitemap)",
            ),
        };
    }

    /** @return array{string, string} */
    private function source(
        string $shop,
        ?string $url,
        ?string $file,
        ?string $kind,
        ?string $userAgent,
    ): array {
        if ($url !== null) {
            $config = Config::forShop($shop);
            Sleep::usleep((int) ($config->downloadDelay() * 1_000_000));

            try {
                $response = $this->http->get($url, [
                    'connect_timeout' => $config->connectTimeout(),
                    'headers' => ['User-Agent' => $userAgent ?? 'BookScraper/1.0'],
                    'http_errors' => false,
                    'timeout' => $config->requestTimeout(),
                ]);
            } catch (GuzzleException $exception) {
                throw new RuntimeException('Request failed: '.$exception->getMessage(), 0, $exception);
            }

            if ($response->getStatusCode() >= 400) {
                throw new RuntimeException("Shop returned HTTP {$response->getStatusCode()}");
            }

            return [(string) $response->getBody(), $kind ?? $this->inferKind($url)];
        }

        if ($file !== null) {
            if (! is_file($file)) {
                throw new RuntimeException("No such file: {$file}");
            }
            $source = file_get_contents($file);
            if ($source === false) {
                throw new RuntimeException("Could not read file: {$file}");
            }

            return [$source, $kind ?? $this->inferKind($file)];
        }

        if ($shop !== 'vaga') {
            throw new RuntimeException('--url or --file is required for shops other than vaga');
        }
        $fixture = base_path('tests/fixtures/vaga_product_page.html');
        $source = file_get_contents($fixture);
        if ($source === false) {
            throw new RuntimeException("Could not read fixture: {$fixture}");
        }

        return [$source, $kind ?? 'product'];
    }

    private function inferKind(string $source): string
    {
        return str_contains($source, 'sitemap') || str_ends_with($source, '.xml')
            ? 'sitemap'
            : 'product';
    }
}
