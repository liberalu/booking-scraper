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
        private ?CrawlerContext $context = null,
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
                $detail = $this->detail($exception);
                $this->issues->add(
                    'discover_fetch_failed',
                    'url',
                    $request->getUri(),
                    $detail,
                );
                if ($this->context instanceof CrawlerContext) {
                    $status = $this->httpStatus($exception);
                    $this->context->increment('failed');
                    $this->context->markFetchFailed(
                        $request->getUri(),
                        $status === null ? 'transport_error' : "http_{$status}",
                        $status,
                        $detail,
                    );
                }
            },
        );
    }

    private function httpStatus(RequestException $exception): ?int
    {
        $previous = $exception->getPrevious();

        return $previous instanceof BadResponseException
            ? $previous->getResponse()->getStatusCode()
            : null;
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
