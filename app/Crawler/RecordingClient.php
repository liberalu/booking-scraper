<?php

declare(strict_types=1);

namespace App\Crawler;

use GuzzleHttp\Exception\BadResponseException;
use ReflectionClass;
use RoachPHP\Http\ClientInterface;
use RoachPHP\Http\RequestException;

final readonly class RecordingClient implements ClientInterface
{
    public function __construct(
        private ClientInterface $inner,
        private IssueBuffer $issues = new IssueBuffer,
    ) {}

    public function pool(
        array $requests,
        ?callable $onFulfilled = null,
        ?callable $onRejected = null,
    ): void {
        $this->inner->pool(
            $requests,
            $onFulfilled,
            $onRejected ?? function (RequestException $exception): void {
                $request = $exception->getRequest();
                $this->issues->add(
                    'discover_fetch_failed',
                    'url',
                    $request->getUri(),
                    $this->detail($exception),
                );
            },
        );
    }

    private function detail(RequestException $exception): string
    {
        $previous = $exception->getPrevious();
        if ($previous instanceof BadResponseException) {
            return 'HTTP '.$previous->getResponse()->getStatusCode();
        }
        $class = $previous ?? $exception;

        return (new ReflectionClass($class))->getShortName();
    }
}
