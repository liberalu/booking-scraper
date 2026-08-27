<?php

declare(strict_types=1);

namespace App\Crawler;

use RoachPHP\Events\ItemScraped;
use RoachPHP\Events\ResponseReceived;
use RoachPHP\Extensions\ExtensionInterface;
use RoachPHP\Support\Configurable;

/**
 * Reports crawl progress to the Watchdog.
 *
 * Mirrors the signals the Python StallDetector watches — `response_received`
 * and `item_scraped`. A response alone is enough: a crawl that is fetching
 * but dropping everything is slow, not stalled.
 *
 * The watchdog lives in another process, so this writes to a marker file
 * rather than shared state. Static binding because roach constructs
 * extensions through the container.
 */
final class ActivityExtension implements ExtensionInterface
{
    use Configurable;

    private static ?Watchdog $watchdog = null;

    public static function bind(?Watchdog $watchdog): void
    {
        self::$watchdog = $watchdog;
    }

    public static function getSubscribedEvents(): array
    {
        return [
            ResponseReceived::NAME => ['onActivity', 0],
            ItemScraped::NAME => ['onActivity', 0],
        ];
    }

    public function onActivity(object $event): void
    {
        self::$watchdog?->recordActivity();
    }
}
