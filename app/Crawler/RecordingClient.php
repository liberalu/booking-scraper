<?php

declare(strict_types=1);

namespace App\Crawler;

use GuzzleHttp\Exception\BadResponseException;
use RoachPHP\Http\ClientInterface;
use RoachPHP\Http\RequestException;

final class RecordingClient implements ClientInterface
{
    public function __construct(
        private readonly ClientInterface $inner,
        private readonly IssueBuffer $issues = new IssueBuffer,
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
                    self::detail($exception),
                );
            },
        );
    }

    private static function detail(RequestException $exception): string
    {
        $previous = $exception->getPrevious();
        if ($previous instanceof BadResponseException) {
            return 'HTTP '.$previous->getResponse()->getStatusCode();
        }
        $class = $previous === null ? $exception : $previous;

        return (new \ReflectionClass($class))->getShortName();
    }
}
