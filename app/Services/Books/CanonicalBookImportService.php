<?php

declare(strict_types=1);

namespace App\Services\Books;

use App\Parsers\Ibiblioteka\Parser;
use App\Repositories\CanonicalBookRepository;
use GuzzleHttp\Client;
use GuzzleHttp\Exception\GuzzleException;
use RuntimeException;

final readonly class CanonicalBookImportService
{
    public function __construct(
        private CanonicalBookRepository $books,
        private Client $http,
    ) {}

    /** @return array{id: int, title: string} */
    public function import(string $url, ?string $file): array
    {
        $body = $file === null ? $this->fetch($url) : $this->read($file);
        $parsed = Parser::parseProductPage($body);
        $title = $parsed['title'] ?? null;
        if (! is_string($title) || $title === '') {
            throw new RuntimeException('No title parsed; the response may be the SPA shell');
        }
        $parsed['source_url'] = $url;

        return ['id' => $this->books->upsert($parsed), 'title' => $title];
    }

    private function fetch(string $url): string
    {
        try {
            $response = $this->http->get($url, [
                'headers' => ['Accept' => 'application/json'],
                'http_errors' => false,
                'timeout' => 30,
            ]);
        } catch (GuzzleException $exception) {
            throw new RuntimeException('Fetch failed: '.$exception->getMessage(), 0, $exception);
        }
        if ($response->getStatusCode() >= 400) {
            throw new RuntimeException("Source returned HTTP {$response->getStatusCode()}");
        }

        return (string) $response->getBody();
    }

    private function read(string $file): string
    {
        if (! is_file($file)) {
            throw new RuntimeException("No such file: {$file}");
        }
        $body = file_get_contents($file);
        if ($body === false) {
            throw new RuntimeException("Could not read file: {$file}");
        }

        return $body;
    }
}
