<?php

declare(strict_types=1);

namespace BookScraper\Crawler;

use RoachPHP\Http\ClientInterface;
use RoachPHP\Http\RequestException;

/**
 * Turns a failed fetch into a recorded issue instead of a dead run.
 *
 * roach's downloader calls `pool()` without a rejection handler, so Guzzle's
 * pool re-throws the first `RequestException` out of `wait()` — one unreachable
 * URL aborts the whole crawl. Upstream instead logs a `discover_fetch_failed`
 * issue per URL through its errback and keeps going, which is what a
 * multi-thousand-URL discovery run needs: a single DNS blip must not discard
 * every page already queued.
 *
 * The interface already accepts an `onRejected`; only the caller omits it.
 */
final class RecordingClient implements ClientInterface
{
    public function __construct(private readonly ClientInterface $inner) {}

    public function pool(
        array $requests,
        ?callable $onFulfilled = null,
        ?callable $onRejected = null,
    ): void {
        $this->inner->pool(
            $requests,
            $onFulfilled,
            $onRejected ?? static function (RequestException $exception): void {
                $request = $exception->getRequest();
                IssueBuffer::add(
                    'discover_fetch_failed',
                    'url',
                    $request->getUri(),
                    self::detail($exception),
                );
            },
        );
    }

    /**
     * The HTTP status when there was one, otherwise the exception class —
     * matching the shape upstream records ("HTTP 503" / "ConnectionError").
     */
    private static function detail(RequestException $exception): string
    {
        $previous = $exception->getPrevious();
        if ($previous instanceof \GuzzleHttp\Exception\BadResponseException) {
            return 'HTTP ' . $previous->getResponse()->getStatusCode();
        }
        $class = $previous === null ? $exception : $previous;

        return (new \ReflectionClass($class))->getShortName();
    }
}
